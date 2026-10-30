"""A small local PDF structure and content-stream explorer."""

from __future__ import annotations

import re
import os
import math
import hashlib
import tempfile
from io import BytesIO
import zlib
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from pypdf import PdfReader
from pypdf.generic import DictionaryObject, NameObject
from pypdf._codecs.symbol import _symbol_encoding
from pypdf._crypt_providers import rc4_encrypt


OPERATORS = {
    "BT", "ET", "Tf", "Tm", "Td", "TD", "T*", "Tc", "Tw", "Tz", "TL",
    "Ts", "Tr", "Tj", "TJ", "Do", "q", "Q", "cm", "w", "J", "j",
    "M", "d", "ri", "i", "gs", "CS", "cs", "SC", "SCN", "sc", "scn",
    "G", "g", "RG", "rg", "K", "k", "m", "l", "c", "v", "y", "h",
    "re", "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n", "W",
    "W*", "sh", "MP", "DP", "BMC", "BDC", "EMC", "BX", "EX", "MP", "'", '"',
}


def decode_literal(raw: bytes) -> bytes:
    """Decode a PDF literal string body, including escapes and octal bytes."""
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c != 0x5C:
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            break
        c = raw[i]
        escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8,
                   ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
        if c in escapes:
            out.append(escapes[c])
            i += 1
        elif c in b"\r\n":
            if c == 13 and i + 1 < len(raw) and raw[i + 1] == 10:
                i += 1
            i += 1
        elif ord("0") <= c <= ord("7"):
            octal = bytearray([c])
            i += 1
            for _ in range(2):
                if i < len(raw) and ord("0") <= raw[i] <= ord("7"):
                    octal.append(raw[i])
                    i += 1
                else:
                    break
            out.append(int(octal, 8) & 0xFF)
        else:
            out.append(c)
            i += 1
    return bytes(out)


def _literal_byte_spans(token: bytes):
    """Return raw token spans corresponding to decoded bytes in a literal string."""
    spans = []
    i = 1
    end = max(1, len(token) - 1)
    while i < end:
        start = i
        value = token[i]
        if value != 0x5C:
            i += 1
        else:
            i += 1
            if i >= end:
                break
            value = token[i]
            if value in b"\r\n":
                if value == 13 and i + 1 < end and token[i + 1] == 10:
                    i += 1
                i += 1
                continue
            if ord("0") <= value <= ord("7"):
                i += 1
                for _ in range(2):
                    if i < end and ord("0") <= token[i] <= ord("7"):
                        i += 1
                    else:
                        break
            else:
                i += 1
        spans.append((start, i))
    return spans


def replace_pdf_string_bytes(token: bytes, data: bytes) -> bytes:
    """Replace a PDF string payload while retaining its literal/hex representation."""
    old_data = decode_literal(token[1:-1]) if token.startswith(b"(") else None
    if old_data is not None:
        if len(data) != len(old_data):
            encoded = bytearray(b"(")
            for value in data:
                if value in b"()\\":
                    encoded.extend(b"\\" + bytes([value]))
                elif value in (8, 9, 10, 12, 13):
                    encoded.extend(b"\\" + {8: b"b", 9: b"t", 10: b"n", 12: b"f", 13: b"r"}[value])
                else:
                    encoded.append(value)
            encoded.append(41)
            return bytes(encoded)
        spans = _literal_byte_spans(token)
        if len(spans) != len(old_data):
            raise ValueError("Could not map the literal string bytes to the decoded stream.")
        result = token
        for index in range(min(len(old_data), len(data)) - 1, -1, -1):
            if old_data[index] == data[index]:
                continue
            start, end = spans[index]
            value = data[index]
            span_length = end - start
            if span_length == 1 and value not in b"()\\\r\n":
                replacement = bytes([value])
            elif span_length >= 4:
                replacement = f"\\{value:03o}".encode("ascii")
            else:
                raise ValueError("The replacement would change the literal string token length.")
            if len(replacement) != span_length:
                raise ValueError("The replacement would change the literal string token length.")
            result = result[:start] + replacement + result[end:]
        return result

    if token.startswith(b"<") and not token.startswith(b"<<"):
        body = re.sub(rb"\s+", b"", token[1:-1])
        old_length = (len(body) + 1) // 2
        if len(data) != old_length:
            return b"<" + data.hex().upper().encode("ascii") + b">"
        positions = [i for i in range(1, len(token) - 1) if token[i] not in b" \t\r\n\f"]
        result = bytearray(token)
        for index in range(min(old_length, len(data))):
            encoded = f"{data[index]:02X}".encode("ascii")
            for nibble in range(2):
                position_index = index * 2 + nibble
                if position_index < len(positions):
                    original = token[positions[position_index]]
                    result[positions[position_index]] = encoded[nibble] + 32 if 97 <= original <= 102 else encoded[nibble]
        return bytes(result)
    raise ValueError("Selected string is not a literal or hexadecimal PDF string.")


def scan_tokens(data: bytes):
    """Yield (kind, start, end, value) tokens from a content stream."""
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c in b"\x00\t\n\x0c\r ":
            i += 1
            continue
        if c == ord("%"):
            while i < n and data[i] not in b"\r\n":
                i += 1
            continue
        start = i
        if c == ord("("):
            i += 1
            depth = 1
            body_start = i
            while i < n and depth:
                if data[i] == ord("\\"):
                    i += 2
                    continue
                if data[i] == ord("("):
                    depth += 1
                elif data[i] == ord(")"):
                    depth -= 1
                i += 1
            body_end = i - 1 if depth == 0 else i
            yield "string", start, i, decode_literal(data[body_start:body_end])
            continue
        if c == ord("<") and i + 1 < n and data[i + 1] != ord("<"):
            i += 1
            end = data.find(b">", i)
            if end < 0:
                end = n
                i = n
            else:
                body = re.sub(rb"\s+", b"", data[i:end])
                i = end + 1
                if len(body) % 2:
                    body += b"0"
                try:
                    value = bytes.fromhex(body.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    value = b""
                yield "string", start, i, value
                continue
            yield "string", start, i, b""
            continue
        if c == ord("["):
            i += 1
            yield "array_start", start, i, "["
            continue
        if c == ord("]"):
            i += 1
            yield "array_end", start, i, "]"
            continue
        if c == ord("/"):
            i += 1
            while i < n and data[i] not in b"\x00\t\n\x0c\r ()<>[]{}/%":
                i += 1
            yield "name", start, i, data[start:i].decode("latin1")
            continue
        while i < n and data[i] not in b"\x00\t\n\x0c\r ()<>[]{}/%":
            i += 1
        if i == start:
            i += 1
        raw = data[start:i]
        word = raw.decode("latin1")
        if word in OPERATORS:
            yield "operator", start, i, word
        else:
            yield "operand", start, i, word


def parse_operations(data: bytes):
    operations = []
    pending = []
    array_depth = 0
    for kind, start, end, value in scan_tokens(data):
        if kind == "array_start":
            array_depth += 1
        elif kind == "array_end":
            array_depth = max(0, array_depth - 1)
        if kind == "operator" and array_depth == 0:
            operations.append({"operator": value, "operands": pending, "start": pending[0]["start"] if pending else start,
                               "end": end})
            pending = []
        else:
            pending.append({"kind": kind, "start": start, "end": end, "value": value,
                            "raw": data[start:end]})
    return operations


def map_cmap(data: bytes):
    """Read common ToUnicode bfchar and bfrange mappings."""
    text = data.decode("latin1", errors="replace")
    mapping = {}
    for block in re.findall(r"\d+\s+beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            try:
                mapping[bytes.fromhex(src)] = bytes.fromhex(dst).decode("utf-16-be", "replace")
            except ValueError:
                pass
    for block in re.findall(r"\d+\s+beginbfrange(.*?)endbfrange", text, re.S):
        for first, last, target in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            try:
                lo, hi, dest = int(first, 16), int(last, 16), int(target, 16)
                width = len(bytes.fromhex(first))
                out_width = len(bytes.fromhex(target))
                for code in range(lo, hi + 1):
                    mapping[code.to_bytes(width, "big")] = (dest + code - lo).to_bytes(out_width, "big").decode("utf-16-be", "replace")
            except (ValueError, OverflowError):
                pass
    return mapping


def obj_ref(obj):
    ref = getattr(obj, "indirect_reference", None)
    return f"{ref.idnum} {ref.generation} R" if ref else "inline object"


def safe_repr(obj, limit=3000):
    text = repr(obj)
    return text if len(text) <= limit else text[:limit] + " ..."


def replace_inline_dictionary(data, key, replacement):
    """Replace a direct PDF dictionary value while respecting nested dictionaries."""
    marker = key.encode("ascii")
    start = data.find(marker)
    if start < 0:
        return data, False
    value_start = start + len(marker)
    while value_start < len(data) and data[value_start] in b" \t\r\n":
        value_start += 1
    if not data.startswith(b"<<", value_start):
        return data, False
    depth = 0
    cursor = value_start
    while cursor + 1 < len(data):
        if data[cursor:cursor + 2] == b"<<":
            depth += 1
            cursor += 2
        elif data[cursor:cursor + 2] == b">>":
            depth -= 1
            cursor += 2
            if depth == 0:
                return data[:start] + marker + b" " + replacement + data[cursor:], True
        else:
            cursor += 1
    return data, False


def dictionary_end(data, start):
    """Return the end offset of a nested PDF dictionary beginning at start."""
    if not data.startswith(b"<<", start):
        return -1
    depth = 0
    cursor = start
    while cursor + 1 < len(data):
        if data[cursor] == ord("%"):
            newline = data.find(b"\n", cursor)
            cursor = len(data) if newline < 0 else newline + 1
            continue
        if data[cursor] == ord("("):
            cursor += 1
            string_depth = 1
            while cursor < len(data) and string_depth:
                if data[cursor] == ord("\\"):
                    cursor += 2
                    continue
                if data[cursor] == ord("("):
                    string_depth += 1
                elif data[cursor] == ord(")"):
                    string_depth -= 1
                cursor += 1
            continue
        if data[cursor] == ord("<") and data[cursor:cursor + 2] != b"<<":
            end = data.find(b">", cursor + 1)
            cursor = len(data) if end < 0 else end + 1
            continue
        if data[cursor:cursor + 2] == b"<<":
            depth += 1
            cursor += 2
        elif data[cursor:cursor + 2] == b">>":
            depth -= 1
            cursor += 2
            if depth == 0:
                return cursor
        else:
            cursor += 1
    return -1


def pdf_object_end(data, offset, reader):
    """Find endobj while skipping literal/hex strings and stream payloads."""
    header = re.match(rb"\d+\s+\d+\s+obj\b", data[offset:])
    if not header:
        raise ValueError(f"No indirect-object header at file offset {offset}.")
    cursor = offset + header.end()
    dict_start = data.find(b"<<", cursor)
    token_end = data.find(b"endobj", cursor)
    if dict_start >= 0 and (token_end < 0 or dict_start < token_end):
        dict_end = dictionary_end(data, dict_start)
        if dict_end < 0:
            raise ValueError(f"Unterminated object dictionary at file offset {offset}.")
        probe = dict_end
        while probe < len(data) and data[probe] in b"\x00\t\n\x0c\r ":
            probe += 1
        if re.match(rb"stream\b", data[probe:]):
            stream_start = probe + len(b"stream")
            if data[stream_start:stream_start + 2] == b"\r\n":
                stream_start += 2
            elif data[stream_start:stream_start + 1] in (b"\r", b"\n"):
                stream_start += 1
            ref_match = re.search(rb"/Length\s+(\d+)\s+(\d+)\s+R", data[dict_start:dict_end])
            if ref_match:
                from pypdf.generic import IndirectObject
                length = int(IndirectObject(int(ref_match.group(1)), int(ref_match.group(2)), reader).get_object())
            else:
                length_match = re.search(rb"/Length\s+(\d+)\b", data[dict_start:dict_end])
                if not length_match:
                    raise ValueError(f"Cannot resolve stream /Length at file offset {offset}.")
                length = int(length_match.group(1))
            after_stream = stream_start + length
            endstream = re.match(rb"[\r\n]*endstream\b", data[after_stream:])
            if not endstream:
                raise ValueError(f"Stream length does not reach endstream at file offset {offset}.")
            endobj = data.find(b"endobj", after_stream + endstream.end())
            if endobj < 0:
                raise ValueError(f"No endobj after stream at file offset {offset}.")
            return endobj + len(b"endobj"), dict_start, dict_end, stream_start, after_stream

    cursor = offset + header.end()
    literal_depth = 0
    while cursor < len(data):
        byte = data[cursor]
        if byte == ord("%"):
            newline = data.find(b"\n", cursor)
            cursor = len(data) if newline < 0 else newline + 1
            continue
        if byte == ord("("):
            literal_depth = 1
            cursor += 1
            while cursor < len(data) and literal_depth:
                if data[cursor] == ord("\\"):
                    cursor += 2
                    continue
                if data[cursor] == ord("("):
                    literal_depth += 1
                elif data[cursor] == ord(")"):
                    literal_depth -= 1
                cursor += 1
            continue
        if byte == ord("<") and data[cursor:cursor + 2] != b"<<":
            end = data.find(b">", cursor + 1)
            cursor = len(data) if end < 0 else end + 1
            continue
        if data[cursor:cursor + 6] == b"endobj" and (cursor + 6 == len(data) or data[cursor + 6] in b"\x00\t\n\x0c\r ()<>[]{}/%"):
            return cursor + 6, None, None, None, None
        cursor += 1
    raise ValueError(f"No endobj at file offset {offset}.")


def rewrite_length_in_dictionary(data, dict_start, dict_end, length):
    """Replace the /Length entry inside an object dictionary with a new value."""
    region = data[dict_start:dict_end]
    updated, count = re.subn(rb"/Length\s+\d+", b"/Length " + str(length).encode("ascii"), region, count=1)
    if count != 1:
        raise ValueError("Object dictionary has no numeric /Length entry to update.")
    return data[:dict_start] + updated + data[dict_end:]


def replace_font_entries_in_dictionary(data, dict_start, dict_end, removed_keys):
    """Remove font keys from an inline /Resources dictionary in raw bytes."""
    region = data[dict_start:dict_end]
    resources_match = re.search(rb"/Resources\s*<<", region)
    if not resources_match:
        raise ValueError("Page object has no inline /Resources dictionary.")
    resources_start = dict_start + resources_match.end() - 2
    resources_end = dictionary_end(data, resources_start)
    if resources_end < 0:
        raise ValueError("Page /Resources dictionary is unterminated.")
    resources = bytearray(data[resources_start:resources_end])
    for key in removed_keys:
        pattern = re.compile(re.escape(key.encode("ascii")) + rb"\s+\d+\s+\d+\s+R")
        resources, count = pattern.subn(b"", bytes(resources), count=1)
        if count != 1:
            raise ValueError(f"Font key {key} is not an indirect reference to remove.")
    return data[:resources_start] + bytes(resources) + data[resources_end:]


def resources_indirect_reference(reader, page):
    """Return the indirect object number of a page's /Resources dictionary."""
    resources = page.raw_get("/Resources")
    if hasattr(resources, "idnum"):
        return resources.idnum
    return None


def encode_stream_data(stream_obj, decoded):
    """Re-encode decoded stream bytes using the source stream's filters."""
    filters = stream_obj.get("/Filter")
    params = stream_obj.get("/DecodeParms")
    if hasattr(params, "get_object"):
        params = params.get_object()
    params_items = list(params) if isinstance(params, (list, tuple)) else [params]
    for item in params_items:
        if hasattr(item, "get_object"):
            item = item.get_object()
        if hasattr(item, "get") and int(item.get("/Predictor", 1)) not in (0, 1):
            raise ValueError("Content streams using PNG/TIFF predictors cannot be re-encoded without changing filter parameters.")
    if filters is None:
        return decoded
    if hasattr(filters, "get_object"):
        filters = filters.get_object()
    filter_names = list(filters) if isinstance(filters, (list, tuple)) else [filters]
    data = decoded
    for filter_name in reversed(filter_names):
        name = str(filter_name)
        if name == "/FlateDecode":
            data = zlib.compress(data)
        else:
            raise ValueError(f"Cannot re-encode content stream filter {name} without changing its filter semantics.")
    return data


class PdfExplorer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("openPdfEditor")
        self.geometry("1440x920")
        self.minsize(1080, 700)
        self.configure(bg="#f6f8fc")
        self.reader = None
        self.path = None
        self.password = ""
        self.page_index = 0
        self.operations = []
        self.stream = b""
        self.edited_streams = {}
        self.removed_font_resources = {}
        self.undo_stack = []
        self.resources = None
        self.font = None
        self.current_font_name = None
        self.current_font_size = None
        self.current_tm = None
        self.unsaved_edits = False
        self.preview_visible = True
        self._style()
        self._layout()
        self.protocol("WM_DELETE_WINDOW", self._close_window)
        self.bind_all("<Control-z>", lambda _event: self.undo_last_edit())

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#ffffff")
        style.configure("Panel.TFrame", background="#ffffff", relief="solid", borderwidth=1, bordercolor="#e2e7ef")
        style.configure("Header.TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff", foreground="#202124", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#ffffff", font=("Segoe UI Semibold", 16), foreground="#202124")
        style.configure("HeaderTitle.TLabel", background="#ffffff", foreground="#202124", font=("Segoe UI Semibold", 16))
        style.configure("Sub.TLabel", background="#ffffff", foreground="#687078", font=("Segoe UI", 9))
        style.configure("HeaderSub.TLabel", background="#ffffff", foreground="#687078", font=("Segoe UI", 9))
        style.configure("Section.TLabel", background="#ffffff", foreground="#5f6368", font=("Segoe UI Semibold", 8))
        style.configure("BrandMark.TLabel", background="#0866ff", foreground="#ffffff", font=("Segoe UI Semibold", 11), padding=(8, 6))
        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(12, 8), background="#ffffff", foreground="#344054", borderwidth=1, bordercolor="#d0d7e2", focusthickness=2, focuscolor="#0866ff")
        style.map("TButton", background=[("active", "#f3f6fb"), ("pressed", "#e9eef7"), ("disabled", "#f7f8fa")], foreground=[("disabled", "#9aa1aa")])
        style.configure("Small.TButton", font=("Segoe UI Semibold", 9), padding=(8, 5), background="#ffffff", foreground="#344054", borderwidth=1, bordercolor="#d0d7e2")
        style.map("Small.TButton", background=[("active", "#f3f6fb"), ("pressed", "#e9eef7")])
        style.configure("Accent.TButton", background="#0866ff", foreground="#ffffff", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#075ce5"), ("pressed", "#064fc7"), ("disabled", "#a8c7fa")], foreground=[("disabled", "#ffffff")])
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=29, background="#ffffff", fieldbackground="#ffffff", foreground="#202124", borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#174ea6")])
        style.configure("Page.Treeview", font=("Segoe UI Semibold", 9), rowheight=31, background="#f3f6fb", fieldbackground="#f3f6fb", foreground="#174ea6")
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9), background="#f8fafd", foreground="#5f6368", padding=(8, 8), relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", "#eef3fb")])
        style.configure("Explorer.Vertical.TScrollbar", background="#d5dce7", troughcolor="#f3f6fa", bordercolor="#e2e7ef", arrowcolor="#5f6368", width=13)
        style.map("Explorer.Vertical.TScrollbar", background=[("active", "#aebbd0")])
        style.configure("TNotebook", background="#ffffff", borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", font=("Segoe UI Semibold", 9), padding=(13, 10), background="#f6f8fc", foreground="#5f6368", borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("active", "#edf3fb")], foreground=[("selected", "#0866ff")])
        style.configure("TEntry", padding=(8, 7), fieldbackground="#ffffff", foreground="#202124", bordercolor="#d0d7e2", lightcolor="#d0d7e2", darkcolor="#d0d7e2")
        style.map("TEntry", bordercolor=[("focus", "#0866ff")], lightcolor=[("focus", "#0866ff")], darkcolor=[("focus", "#0866ff")])
        style.configure("TCombobox", padding=(7, 6), fieldbackground="#ffffff", background="#ffffff", foreground="#202124", bordercolor="#d0d7e2", arrowcolor="#5f6368")
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff"), ("disabled", "#f7f8fa")], foreground=[("disabled", "#9aa1aa")])
        style.configure("TLabelframe", background="#ffffff", bordercolor="#e2e7ef", relief="solid")
        style.configure("TLabelframe.Label", background="#ffffff", foreground="#5f6368", font=("Segoe UI Semibold", 9))
        style.configure("Status.TLabel", background="#f6f8fc", foreground="#687078", font=("Segoe UI", 9))

    def _layout(self):
        top = ttk.Frame(self, style="Header.TFrame", padding=(20, 12, 20, 12))
        top.pack(fill="x")
        ttk.Label(top, text="PDF", style="BrandMark.TLabel").pack(side="left", padx=(0, 12))
        titlebox = ttk.Frame(top)
        titlebox.pack(side="left", fill="x", expand=True)
        ttk.Label(titlebox, text="openPdfEditor", style="HeaderTitle.TLabel").pack(anchor="w")
        self.file_label = ttk.Label(titlebox, text="Open a PDF to inspect its decoded structure", style="HeaderSub.TLabel")
        self.file_label.pack(anchor="w", pady=(3, 0))
        actions = ttk.Frame(top, style="Header.TFrame")
        actions.pack(side="right")
        ttk.Button(actions, text="Open PDF", command=self.open_pdf).pack(side="left", padx=(0, 8))
        self.undo_button = ttk.Button(actions, text="Undo", command=self.undo_last_edit)
        self.undo_button.pack(side="left", padx=(0, 8))
        self.undo_button.state(["disabled"])
        self.unused_button = ttk.Button(actions, text="Delete Unused Fonts/Strokes", command=self.clean_confirmed_unused)
        self.unused_button.pack(side="left", padx=(0, 8))
        self.unused_button.state(["disabled"])
        self.save_button = ttk.Button(actions, text="Save All Edits", style="Accent.TButton", command=self.save_edited_copy)
        self.save_button.pack(side="left")
        self.save_button.state(["disabled"])

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=(10, 8))
        left = ttk.Frame(body, style="Panel.TFrame", padding=12)
        right = ttk.Frame(body, style="Panel.TFrame", padding=10)
        body.add(left, weight=1)
        body.add(right, weight=3)

        row = ttk.Frame(left, style="Panel.TFrame")
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Page", background="#ffffff").pack(side="left")
        self.page_var = tk.StringVar(value="-")
        self.page_combo = ttk.Combobox(row, textvariable=self.page_var, width=8, state="readonly")
        self.page_combo.pack(side="right")
        self.page_combo.bind("<<ComboboxSelected>>", self.change_page)
        ttk.Label(left, text="DOCUMENT MAP", style="Section.TLabel").pack(anchor="w", pady=(6, 8))
        search_row = ttk.Frame(left, style="Panel.TFrame")
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text="Search all pages", background="#ffffff", foreground="#5f6368").pack(side="left", padx=(0, 7))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.insert(0, "")
        self.search_entry.bind("<Return>", lambda _event: self._apply_operation_filter())
        ttk.Button(search_row, text="Clear", style="Small.TButton", command=lambda: self.search_var.set("")).pack(side="left", padx=(6, 0))
        self.search_var.trace_add("write", lambda *_args: self._apply_operation_filter())
        self.show_paths_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_row, text="Paths", variable=self.show_paths_var, command=self._populate_ops).pack(side="right", padx=(6, 0))
        ttk.Label(left, text="Every page · operations sorted top to bottom, then left to right", style="Sub.TLabel", background="#ffffff").pack(anchor="w", pady=(2, 7))
        ops_frame = ttk.Frame(left, style="Panel.TFrame")
        ops_frame.pack(fill="both", expand=True)
        self.ops_tree = ttk.Treeview(ops_frame, columns=("op", "font", "text"), show="headings", selectmode="browse")
        self.ops_tree.heading("op", text="Operator")
        self.ops_tree.heading("font", text="Font")
        self.ops_tree.heading("text", text="Text / position")
        self.ops_tree.column("op", width=62, stretch=False)
        self.ops_tree.column("font", width=56, stretch=False)
        self.ops_tree.column("text", width=170)
        ops_scrollbar = tk.Scrollbar(ops_frame, orient="vertical", command=self.ops_tree.yview,
                                     bg="#d5dce7", troughcolor="#f3f6fa", activebackground="#8ea4c4",
                                     highlightthickness=0, bd=0, width=14)
        self.ops_tree.configure(yscrollcommand=ops_scrollbar.set)
        self.ops_tree.pack(side="left", fill="both", expand=True)
        ops_scrollbar.pack(side="right", fill="y")
        self.ops_tree.tag_configure("state", foreground="#174ea6", background="#f4f8ff")
        self.ops_tree.tag_configure("alt", background="#f8fafd")
        self.ops_tree.tag_configure("page", foreground="#174ea6", background="#eef3fb", font=("Segoe UI Semibold", 9))
        self.ops_tree.bind("<<TreeviewSelect>>", self.select_operation)
        self.ops_tree.bind("<MouseWheel>", self._scroll_operations)
        self.ops_tree.bind("<Button-4>", lambda _event: self.ops_tree.yview_scroll(-3, "units"))
        self.ops_tree.bind("<Button-5>", lambda _event: self.ops_tree.yview_scroll(3, "units"))

        right_body = ttk.Panedwindow(right, orient="horizontal")
        self.right_body = right_body
        preview_bar = ttk.Frame(right, style="Panel.TFrame")
        preview_bar.pack(fill="x", pady=(0, 6))
        self.preview_toggle = ttk.Button(preview_bar, text="Hide preview", style="Small.TButton", command=self.toggle_preview)
        self.preview_toggle.pack(side="right")
        right_body.pack(fill="both", expand=True)
        self.tabs = ttk.Notebook(right_body)
        right_body.add(self.tabs, weight=4)
        side_preview = ttk.Frame(right_body, style="Panel.TFrame", padding=(10, 8, 4, 8))
        self.side_preview = side_preview
        right_body.add(side_preview, weight=2)
        ttk.Label(side_preview, text="PAGE PREVIEW", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(side_preview, text="Selected origin", style="Title.TLabel", background="#ffffff").pack(anchor="w", pady=(0, 7))
        self.side_canvas = tk.Canvas(side_preview, bg="#f8fafd", highlightthickness=1, highlightbackground="#e2e7ef")
        self.side_canvas.pack(fill="both", expand=True)
        self.side_canvas.bind("<Configure>", lambda _event: self._draw_page_view())
        self.side_page_image = None
        self.content_tab = ttk.Frame(self.tabs, padding=10)
        self.resources_tab = ttk.Frame(self.tabs, padding=10)
        self.page_text_tab = ttk.Frame(self.tabs, padding=10)
        self.structure_tab = ttk.Frame(self.tabs, padding=10)
        self.audit_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.content_tab, text="Content & Bytes")
        self.tabs.add(self.resources_tab, text="Resources & Fonts")
        self.tabs.add(self.page_text_tab, text="Full Page Text")
        self.tabs.add(self.structure_tab, text="PDF Structure")
        self.detail_title = ttk.Label(self.content_tab, text="Select a text operation", style="Title.TLabel")
        self.detail_title.pack(anchor="w")
        self.detail_summary = ttk.Label(self.content_tab, text="Operators and operands will be explained here.", style="Sub.TLabel")
        self.detail_summary.pack(anchor="w", pady=(4, 10))
        edit = ttk.LabelFrame(self.content_tab, text="Edit selected operation", padding=8)
        edit.pack(fill="x", pady=(0, 10))
        self.edit_hex_var = tk.StringVar()
        self.edit_font_var = tk.StringVar()
        self.edit_size_var = tk.StringVar()
        self.edit_x_var = tk.StringVar()
        self.edit_y_var = tk.StringVar()
        for col, label, var, width in [(0, "String bytes (hex)", self.edit_hex_var, 30), (1, "Font", self.edit_font_var, 8), (2, "Size", self.edit_size_var, 8), (3, "X", self.edit_x_var, 8), (4, "Y", self.edit_y_var, 8)]:
            ttk.Label(edit, text=label).grid(row=0, column=col, sticky="w", padx=(0, 6))
            ttk.Entry(edit, textvariable=var, width=width).grid(row=1, column=col, sticky="ew", padx=(0, 6))
        ttk.Button(edit, text="Apply fields", command=self.apply_selected_fields).grid(row=1, column=5, sticky="e")
        ttk.Button(edit, text="Remove selected op", command=self.remove_selected_text).grid(row=1, column=6, sticky="e", padx=(6, 0))
        edit.columnconfigure(0, weight=3)
        ttk.Label(edit, text="Tj/TJ edits string bytes · Tf edits font and size · Tm edits x and y. Other fields stay unchanged.", style="Sub.TLabel", wraplength=680, justify="left").grid(row=2, column=0, columnspan=7, sticky="w", pady=(6, 0))
        self.byte_view = tk.Text(self.content_tab, height=7, wrap="none", font=("Cascadia Mono", 10), bg="#17212b", fg="#e8eef7", insertbackground="#ffffff", relief="flat", padx=12, pady=10, selectbackground="#315b91")
        self.byte_view.pack(fill="x", pady=(0, 10))
        self.byte_view.configure(state="disabled")
        self.explain = tk.Text(self.content_tab, wrap="word", font=("Segoe UI", 10), bg="#ffffff", fg="#202124", relief="flat", padx=8, pady=6)
        self.explain.pack(fill="both", expand=True)
        self.explain.configure(state="disabled")

        fontrow = ttk.Frame(self.resources_tab)
        fontrow.pack(fill="x", pady=(0, 9))
        ttk.Label(fontrow, text="Page resources and font objects", style="Title.TLabel").pack(side="left")
        self.font_combo = ttk.Combobox(fontrow, state="readonly", width=14)
        self.font_combo.pack(side="right")
        self.font_combo.bind("<<ComboboxSelected>>", self.select_font)
        self.resource_text = tk.Text(self.resources_tab, wrap="word", font=("Consolas", 9), bg="#ffffff", fg="#202124", relief="flat", padx=8, pady=8)
        self.resource_text.pack(fill="both", expand=True)
        self.resource_text.configure(state="disabled")

        ttk.Label(self.page_text_tab, text="Extracted text for the entire page", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        self.page_text = tk.Text(self.page_text_tab, wrap="word", font=("Consolas", 10), bg="#ffffff", fg="#202124", relief="flat", padx=8, pady=8)
        self.page_text.pack(fill="both", expand=True)
        self.page_text.configure(state="disabled")

        self.page_pixmap = None

        ttk.Label(self.structure_tab, text="File and page structure", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        self.structure_text = tk.Text(self.structure_tab, wrap="word", font=("Consolas", 10), bg="#ffffff", fg="#202124", relief="flat", padx=8, pady=8)
        self.structure_text.pack(fill="both", expand=True)
        self.structure_text.configure(state="disabled")

        self.page_transform = None
        self.selected_origin = None
        self.preview_path = None
        self.preview_tempdir = None
        self.selected_operation_index = None
        self.selected_operation_page = None
        self.visible_operations = {}
        self.reselect_signature = None

        self.workspace_body = body
        self.welcome_frame = ttk.Frame(self, style="Panel.TFrame", padding=(40, 44))
        ttk.Label(self.welcome_frame, text="openPdfEditor", style="Title.TLabel").pack(anchor="center", pady=(90, 8))
        ttk.Label(self.welcome_frame, text="Open a PDF to inspect its byte order, decoded operators, fonts, and page positions.", style="Sub.TLabel", wraplength=700, justify="center").pack(anchor="center", pady=(0, 18))
        ttk.Button(self.welcome_frame, text="Open a PDF", style="Accent.TButton", command=self.open_pdf).pack(anchor="center")
        body.pack_forget()
        self.welcome_frame.pack(fill="both", expand=True, padx=14, pady=(10, 8))

        ttk.Separator(self).pack(fill="x")
        self.status = ttk.Label(self, text="Local only · PDF data is read from disk and not uploaded", style="Status.TLabel", padding=(18, 8, 18, 8))
        self.status.pack(fill="x")

    def open_pdf(self):
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not path:
            return
        try:
            reader = PdfReader(path)
            password = ""
            if reader.is_encrypted:
                result = reader.decrypt(password)
                if not result:
                    password = simpledialog.askstring("Encrypted PDF", "Enter the PDF password:", show="*", parent=self)
                    if password is None or not reader.decrypt(password):
                        return
            self.reader, self.path, self.password = reader, path, password
            self.edited_streams = {}
            self.removed_font_resources = {}
            self.undo_stack = []
            self.unsaved_edits = False
            self._clear_preview()
            self.unused_button.state(["!disabled"])
            self.undo_button.state(["disabled"])
            self.save_button.state(["disabled"])
            self.file_label.configure(text=f"{path}  ·  {len(reader.pages)} pages")
            self.welcome_frame.pack_forget()
            self.workspace_body.pack(fill="both", expand=True, padx=14, pady=(10, 8))
            self.page_combo.configure(values=[str(i + 1) for i in range(len(reader.pages))])
            self.page_combo.current(0)
            self.load_page(0)
        except Exception as exc:
            messagebox.showerror("Could not open PDF", str(exc), parent=self)

    def toggle_preview(self):
        if self.preview_visible:
            self.right_body.forget(self.side_preview)
            self.preview_toggle.configure(text="Show preview")
        else:
            self.right_body.add(self.side_preview, weight=2)
            self.preview_toggle.configure(text="Hide preview")
        self.preview_visible = not self.preview_visible

    def _capture_edit_state(self):
        return {
            "edited_streams": dict(self.edited_streams),
            "removed_font_resources": {page: set(names) for page, names in self.removed_font_resources.items()},
            "page_index": self.page_index,
            "selected_page": self.selected_operation_page,
            "selected_index": self.selected_operation_index,
        }

    def undo_last_edit(self):
        if not self.undo_stack:
            return
        snapshot = self.undo_stack.pop()
        self.edited_streams = snapshot["edited_streams"]
        self.removed_font_resources = snapshot["removed_font_resources"]
        self.page_index = snapshot["page_index"]
        self.selected_operation_page = snapshot["selected_page"]
        self.selected_operation_index = snapshot["selected_index"]
        self.reselect_signature = None
        self._clear_preview()
        if self.edited_streams:
            self.preview_tempdir = tempfile.TemporaryDirectory(prefix="pdf-byte-explorer-")
            self.preview_path = os.path.join(self.preview_tempdir.name, "preview.pdf")
            try:
                self._write_rebuilt_pdf(self.edited_streams, self.preview_path, self.removed_font_resources)
            except Exception as exc:
                self._clear_preview()
                self.undo_stack.append(snapshot)
                messagebox.showerror("Could not undo", str(exc), parent=self)
                return
        self.unsaved_edits = bool(self.edited_streams)
        self.page_combo.current(self.page_index)
        self.load_page(self.page_index)
        self.save_button.state(["!disabled"] if self.edited_streams else ["disabled"])
        self.undo_button.state(["!disabled"] if self.undo_stack else ["disabled"])
        self.status.configure(text=f"Undid last change · {len(self.edited_streams)} page(s) still have pending edits")

    def change_page(self, _event=None):
        if self.page_combo.current() >= 0:
            self.load_page(self.page_combo.current())

    def _clear_preview(self):
        if self.preview_tempdir:
            self.preview_tempdir.cleanup()
        self.preview_tempdir = None
        self.preview_path = None

    @staticmethod
    def _read_page_stream(page):
        contents = page.get("/Contents")
        if contents is None:
            return b""
        if isinstance(contents, list):
            return b"\n".join(item.get_object().get_data() for item in contents)
        # Do not use truthiness here: pypdf's ContentStream can be falsey
        # despite containing bytes, which silently hides the whole page.
        return contents.get_object().get_data()

    def load_page(self, index):
        self.page_index = index
        page = self.reader.pages[index]
        self.stream = self.edited_streams.get(index, self._read_page_stream(page))
        self.operations = parse_operations(self.stream)
        self.resources = page.get("/Resources", {})
        self._show_pdf_structure(page)
        self._set_text(self.page_text, page.extract_text() or "No extractable text was found on this page.")
        self.current_font_name = None
        self.current_font_size = None
        self.current_tm = None
        self._populate_ops()
        self._render_page_view()
        fonts = self.resources.get("/Font", {})
        names = list(fonts.keys())
        self.font_combo.configure(values=names)
        if names:
            chosen = self.current_font_name if self.current_font_name in names else names[0]
            self.font_combo.set(chosen)
            self.render_font(chosen)
        else:
            self._set_text(self.resource_text, "This page has no font resources.\n\nPDF resources are referenced by page dictionaries. This page has no /Font entries to map from Tf operators.")
        pending = f"  ·  {len(self.edited_streams)} page(s) with pending edits" if self.edited_streams else ""
        self.status.configure(text=f"Page {index + 1} of {len(self.reader.pages)}  ·  decoded content stream: {len(self.stream):,} bytes{pending}")
        target = self._operation_id(index, self.selected_operation_index) if self.selected_operation_page == index else None
        if target and self.ops_tree.exists(target):
            self.ops_tree.selection_set(target)
            self.ops_tree.focus(target)
            self.ops_tree.see(target)
            self.select_operation()
        else:
            first = next((item for item in self.ops_tree.get_children() if item.startswith(f"p{index}:o")), None)
            if first:
                self.ops_tree.selection_set(first)
                self.select_operation()

    @staticmethod
    def _operation_id(page_index, operation_index):
        return f"p{page_index}:o{operation_index}"

    @staticmethod
    def _parse_operation_id(item_id):
        match = re.fullmatch(r"p(\d+):o(\d+)", item_id or "")
        return (int(match.group(1)), int(match.group(2))) if match else (None, None)

    def _populate_ops(self):
        if not self.reader:
            return
        saved = (self.page_index, self.stream, self.operations, self.resources)
        page_operations = {}
        self.ops_tree.delete(*self.ops_tree.get_children())
        for page_number, page in enumerate(self.reader.pages):
            self.page_index = page_number
            self.stream = self.edited_streams.get(page_number, self._read_page_stream(page))
            self.operations = parse_operations(self.stream)
            page_operations[page_number] = self.operations
            self.resources = page.get("/Resources", {})
            self.ops_tree.insert("", "end", iid=f"page:{page_number}", values=("PAGE", str(page_number + 1), f"Page {page_number + 1}  ·  {len(self.stream):,} decoded bytes"), tags=("page",))
            self._populate_current_ops_rows(page_number)
        self.page_index, self.stream, _, self.resources = saved
        self.operations = page_operations.get(self.page_index, [])

    def _scroll_operations(self, event):
        delta = -1 if event.delta > 0 else 1
        self.ops_tree.yview_scroll(delta * max(1, abs(event.delta) // 120), "units")
        return "break"

    def _populate_current_ops_rows(self, page_number):
        font = None
        size = None
        leading = 0.0
        matrix = [1, 0, 0, 1, 0, 0]
        line_matrix = matrix.copy()
        rows = []
        path_points = []
        path_bounds = None
        path_operators = {"m", "l", "c", "v", "y", "re"}
        path_paint_operators = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
        for idx, op in enumerate(self.operations):
            name = op["operator"]
            vals = [x["value"] for x in op["operands"]]
            if name == "Tf" and len(vals) >= 2:
                font, size = str(vals[-2]), str(vals[-1])
                op["text_origin"] = (float(matrix[4]), float(matrix[5]))
                rows.append((idx, name, font, f"{font} at size {size}", f"{font} {size} Tf", (float(matrix[4]), float(matrix[5]))))
            elif name == "TL" and vals:
                leading = float(vals[-1])
            if name == "Tm" and len(vals) >= 6:
                matrix = vals[-6:]
                line_matrix = matrix.copy()
                try:
                    origin = (float(matrix[4]), float(matrix[5]))
                except (TypeError, ValueError):
                    origin = (0.0, 0.0)
                op["text_origin"] = origin
                rows.append((idx, name, font or "?", f"x={origin[0]:g}, y={origin[1]:g}", " ".join(str(value) for value in matrix) + " Tm", origin))
            elif name in ("Td", "TD") and len(vals) >= 2:
                line_matrix[4] += float(vals[-2])
                line_matrix[5] += float(vals[-1])
                matrix = line_matrix.copy()
            elif name == "T*":
                line_matrix[5] -= leading
                matrix = line_matrix.copy()
            if name in path_operators:
                numbers = []
                try:
                    numbers = [float(value) for value in vals]
                except (TypeError, ValueError):
                    numbers = []
                if name == "re" and len(numbers) >= 4:
                    x, y, width, height = numbers[-4:]
                    path_points.extend([(x, y), (x + width, y + height)])
                elif name in ("m", "l") and len(numbers) >= 2:
                    path_points.append((numbers[-2], numbers[-1]))
                elif name == "c" and len(numbers) >= 6:
                    path_points.extend([(numbers[-6], numbers[-5]), (numbers[-4], numbers[-3]), (numbers[-2], numbers[-1])])
                elif name in ("v", "y") and len(numbers) >= 4:
                    path_points.extend([(numbers[-4], numbers[-3]), (numbers[-2], numbers[-1])])
                if path_points:
                    xs, ys = zip(*path_points)
                    path_bounds = (min(xs), min(ys), max(xs), max(ys))
            if name in path_paint_operators and self.show_paths_var.get():
                if path_bounds:
                    x0, y0, x1, y1 = path_bounds
                    summary = f"{name}: {x0:g},{y0:g} to {x1:g},{y1:g}"
                    origin = (x0, y1)
                else:
                    summary = f"{name}: path bounds unavailable"
                    origin = (0.0, 0.0)
                rows.append((idx, name, "PATH", summary, summary, origin))
                path_points = []
                path_bounds = None
            if name in ("Tj", "TJ"):
                full_text = "".join(
                    self._decode_bytes(item["value"], font)[0]
                    for item in op["operands"] if item["kind"] == "string"
                )
                preview = full_text.strip()[:45]
                origin = (float(matrix[4]), float(matrix[5]))
                op["text_origin"] = origin
                rows.append((idx, name, font or "?", preview, full_text, origin))
        try:
            pattern = re.compile(self.search_var.get(), re.IGNORECASE) if self.search_var.get() else None
        except re.error as exc:
            self.status.configure(text=f"Invalid regex: {exc}")
            pattern = None
        rows.sort(key=lambda row: (-row[5][1], row[5][0], row[0]))
        for row_number, (idx, name, font_name, preview, full_text, origin) in enumerate(rows):
            searchable = f"{name} {font_name} {full_text} x={origin[0]:g} y={origin[1]:g}"
            if pattern and not pattern.search(searchable):
                continue
            location = f"x={origin[0]:g}, y={origin[1]:g} pt"
            summary = preview if name == "Tm" or font_name == "PATH" else f"{preview}  ·  {location}"
            tags = ("state",) if name in ("Tm", "Tf") else (("alt",) if row_number % 2 else ())
            self.ops_tree.insert("", "end", iid=self._operation_id(page_number, idx), values=(name, font_name, summary), tags=tags)

    def _apply_operation_filter(self):
        selected_page = self.selected_operation_page
        selected = self.selected_operation_index
        query = self.search_var.get()
        self._populate_ops()
        selected_id = self._operation_id(selected_page, selected) if selected_page is not None and selected is not None else None
        if selected_id and self.ops_tree.exists(selected_id):
            self.ops_tree.selection_set(selected_id)
            self.ops_tree.focus(selected_id)
            self.ops_tree.see(selected_id)
        if query:
            try:
                re.compile(query, re.IGNORECASE)
            except re.error:
                return
            result_count = sum(1 for item in self.ops_tree.get_children() if self._parse_operation_id(item)[0] is not None)
            self.status.configure(text=f"{result_count:,} matching operations across {len(self.reader.pages):,} pages")
        elif self.reader:
            self.status.configure(text=f"Page {self.page_index + 1} of {len(self.reader.pages)}  ·  decoded content stream: {len(self.stream):,} bytes")

    def _text_preview(self, op, font_name):
        strings = []
        for operand in op["operands"]:
            if operand["kind"] == "string":
                strings.append(self._decode_bytes(operand["value"], font_name)[0])
        return "".join(strings).strip()[:45]

    def select_operation(self, _event=None):
        selection = self.ops_tree.selection()
        if not selection:
            return
        selected_page, index = self._parse_operation_id(selection[0])
        if selected_page is None:
            if selection[0].startswith("page:"):
                page_number = int(selection[0].split(":", 1)[1])
                if page_number != self.page_index:
                    self.page_combo.current(page_number)
                    self.load_page(page_number)
            return
        if selected_page != self.page_index:
            self.selected_operation_page = selected_page
            self.selected_operation_index = index
            self.page_combo.current(selected_page)
            self.load_page(selected_page)
            item_id = self._operation_id(selected_page, index)
            if self.ops_tree.exists(item_id):
                self.ops_tree.selection_set(item_id)
                self.ops_tree.focus(item_id)
                self.ops_tree.see(item_id)
            return
        self.selected_operation_index = index
        self.selected_operation_page = selected_page
        op = self.operations[index]
        font_name = None
        font_size = None
        matrix = None
        for prev in self.operations[:index + 1]:
            vals = [x["value"] for x in prev["operands"]]
            if prev["operator"] == "Tf" and len(vals) >= 2:
                font_name, font_size = str(vals[-2]), str(vals[-1])
            elif prev["operator"] == "Tm" and len(vals) >= 6:
                matrix = vals[-6:]
        self.current_font_name, self.current_font_size, self.current_tm = font_name, font_size, matrix
        string_bytes = b"".join(item["value"] for item in op["operands"] if item["kind"] == "string")
        self.edit_hex_var.set(string_bytes.hex(" ").upper())
        self.edit_font_var.set(font_name or "")
        self.edit_size_var.set(str(font_size or ""))
        if matrix and len(matrix) >= 6:
            self.edit_x_var.set(str(matrix[4]))
            self.edit_y_var.set(str(matrix[5]))
        raw = self.stream[op["start"]:op["end"]]
        offset = op["start"]
        byte_lines = []
        for start in range(0, len(raw), 16):
            chunk = raw[start:start + 16]
            hexpart = " ".join(f"{b:02X}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            byte_lines.append(f"{offset + start:08X}  {hexpart:<47}  {ascii_part}")
        self._set_text(self.byte_view, "Decoded-stream offset   Hex bytes                                         ASCII\n" + "\n".join(byte_lines))
        label = f"{op['operator']} at decoded-stream offset 0x{op['start']:X}"
        self.detail_title.configure(text=label)
        self.detail_summary.configure(text=f"Page {self.page_index + 1}  ·  current font {font_name or 'not selected'}  ·  size {font_size or 'unknown'}")
        content_start = op["start"]
        content_end = op["end"]
        lines = [f"Operator: {op['operator']}", ""]
        lines += [f"Operation bytes in decoded page content stream: [{content_start}, {content_end})", f"Length: {content_end - content_start} bytes. These offsets are not offsets in the original PDF file because the stream may be compressed/filtered.", ""]
        vals = [x["value"] for x in op["operands"]]
        if op["operator"] == "Tm" and len(vals) >= 6:
            a, b, c, d, e, f = vals[-6:]
            lines += ["Text matrix (a b c d e f):", f"  {a} {b} {c} {d} {e} {f}",
                      "  The first four values control rotation, skew, and scale.",
                      f"  The last two place the text origin at x={e}, y={f} in user-space points.",
                      "  Here, 1 0 0 1 is the identity transform: no rotation, skew, or scaling."]
        elif op["operator"] == "Tf" and len(vals) >= 2:
            lines += [f"Font resource: {vals[-2]}", f"Font size: {vals[-1]} user-space units", "Tf selects this page resource and size for subsequent text-showing operators."]
        elif op["operator"] in ("Tj", "TJ"):
            origin = op.get("text_origin")
            lines += [f"Text: {self._text_preview(op, font_name)!r}", f"Current font: {font_name or 'not selected'} at size {font_size or 'unknown'}", f"Text origin: x={origin[0]:g}, y={origin[1]:g} PDF points" if origin else "Text origin: unavailable", "This is the start of the text baseline (the point where glyph placement begins), not the top-left or center of a text box. Glyphs extend above and below it according to the font; the string advances from this point.", "Tj shows one string. TJ shows strings plus spacing adjustments.", "Each byte is interpreted using the selected font's encoding. ToUnicode is commonly used for text extraction.", ""]
            for operand in op["operands"]:
                if operand["kind"] == "string":
                    text, mapping = self._decode_bytes(operand["value"], font_name)
                    lines.append(f"String bytes: {operand['value'].hex(' ').upper() or '(empty)'}")
                    lines.append(f"Decoded text: {text!r}")
                    lines.append(f"Font used: {font_name or 'not selected'} at size {font_size or 'unknown'}")
                    lines.extend("  " + detail for detail in mapping)
                    lines.extend("  " + detail for detail in self._glyph_width_details(operand["value"], font_name, font_size))
                    lines.append("")
        elif op["operator"] in {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}:
            lines += ["Path painting operator:", "  m/l/c/re operators construct a vector path from coordinates; this operator strokes it, fills it, or ends/clips it.", "  The Paths checkbox adds these path endpoints to the operations list with approximate bounds.", "  Path coordinate editing is not available yet; a path must be edited as a complete set of connected segments.", "", f"Operands: {vals!r}"]
        else:
            lines.append("Operands are the tokens before this operator. This operation is part of the page's drawing instructions.")
        self._set_text(self.explain, "\n".join(lines))
        if op.get("text_origin"):
            self._draw_page_view(op["text_origin"])
        if font_name and font_name in self.resources.get("/Font", {}):
            self.font_combo.set(font_name)
            self.render_font(font_name)

    def _glyph_width_details(self, data, font_name, font_size):
        if not font_name or font_name not in self.resources.get("/Font", {}):
            return ["Glyph advance unavailable: no selected font resource."]
        font = self.resources["/Font"][font_name].get_object()
        first = font.get("/FirstChar")
        widths = font.get("/Widths")
        if first is None or widths is None:
            return ["Glyph advance unavailable from /FirstChar and /Widths for this font."]
        widths = widths.get_object() if hasattr(widths, "get_object") else widths
        font_matrix = font.get("/FontMatrix", [0.001, 0, 0, 0.001, 0, 0])
        horizontal_scale = float(font_matrix[0]) if len(font_matrix) >= 4 else 0.001
        details = []
        for byte in data:
            code = byte
            index = code - int(first)
            if 0 <= index < len(widths):
                units = float(widths[index])
                if font_size is not None:
                    advance = units * float(font_size) * horizontal_scale
                    details.append(f"byte {byte:02X} -> glyph advance {units:g} units × size {font_size} × FontMatrix {horizontal_scale:g} = {advance:g} pt")
                else:
                    details.append(f"byte {byte:02X} -> glyph width {units:g} font units; font size unavailable")
            else:
                details.append(f"byte {byte:02X} -> width unavailable from this font dictionary")
        return details

    def remove_selected_text(self):
        index = self.selected_operation_index
        if index is None or index >= len(self.operations):
            return
        op = self.operations[index]
        if op["operator"] not in ("Tj", "TJ", "Tf", "Tm"):
            messagebox.showerror("Editable operation required", "Select a Tj, TJ, Tf, or Tm row first.", parent=self)
            return
        start = op["start"]
        if op["operator"] in ("Tj", "TJ") and index > 0 and self.operations[index - 1]["operator"] == "Tm":
            tm = self.operations[index - 1]
            between = self.stream[tm["end"]:op["start"]]
            if not between.strip():
                start = tm["start"]
        if op["operator"] in ("Tf", "Tm") and not messagebox.askyesno(
            "Remove state-setting operation",
            f"Removing {op['operator']} changes the state inherited by later operations. Remove only this operator's bytes?",
            parent=self,
        ):
            return
        updated = self.stream[:start] + self.stream[op["end"]:]
        self.reselect_signature = None
        self.apply_decoded_stream(updated)

    def apply_selected_fields(self):
        """Edit only the selected decoded content-stream operation."""
        index = self.selected_operation_index
        if index is None or index >= len(self.operations):
            return
        op = self.operations[index]
        if op["operator"] not in ("Tj", "TJ", "Tf", "Tm"):
            messagebox.showerror("Editable operation required", "Select a Tj, TJ, Tf, or Tm row first.", parent=self)
            return
        if op["operator"] == "Tf":
            font = self.edit_font_var.get().strip()
            if not font.startswith("/"):
                font = "/" + font
            try:
                size = float(self.edit_size_var.get())
            except ValueError as exc:
                messagebox.showerror("Invalid edit", f"Use a numeric font size.\n\n{exc}", parent=self)
                return
            if font not in self.resources.get("/Font", {}):
                messagebox.showerror("Unknown font", f"{font} is not a font resource on this page.", parent=self)
                return
            operands = op["operands"]
            if len(operands) < 2 or not math.isfinite(size):
                messagebox.showerror("Invalid font operation", "This Tf operation needs a font resource and a finite numeric size.", parent=self)
                return
            replacements = []
            if str(operands[-2]["value"]) != font:
                replacements.append((operands[-2]["start"], operands[-2]["end"], font.encode("ascii")))
            try:
                old_size = float(operands[-1]["value"])
            except (TypeError, ValueError):
                messagebox.showerror("Invalid font operation", "The selected Tf size is not numeric.", parent=self)
                return
            if old_size != size:
                replacements.append((operands[-1]["start"], operands[-1]["end"], f"{size:g}".encode("ascii")))
            if not replacements:
                return
            self.reselect_signature = {"operator": "Tf", "font": font, "size": size}
            updated = self.stream
            for start, end, replacement in sorted(replacements, reverse=True):
                updated = updated[:start] + replacement + updated[end:]
            self.apply_decoded_stream(updated)
            return
        if op["operator"] == "Tm":
            try:
                x = float(self.edit_x_var.get())
                y = float(self.edit_y_var.get())
            except ValueError as exc:
                messagebox.showerror("Invalid edit", f"Use numeric x and y values.\n\n{exc}", parent=self)
                return
            if not math.isfinite(x) or not math.isfinite(y):
                messagebox.showerror("Invalid edit", "X and Y must be finite numbers.", parent=self)
                return
            operands = op["operands"]
            if len(operands) < 6:
                messagebox.showerror("Matrix unavailable", "This Tm operation does not have six operands.", parent=self)
                return
            coordinate_operands = operands[-2:]
            replacements = []
            for operand, new_value in zip(coordinate_operands, (x, y)):
                try:
                    old_value = float(operand["value"])
                except (TypeError, ValueError):
                    messagebox.showerror("Invalid matrix", "The selected Tm has non-numeric x/y operands.", parent=self)
                    return
                if old_value != new_value:
                    replacements.append((operand["start"], operand["end"], f"{new_value:g}".encode("ascii")))
            if not replacements:
                return
            self.reselect_signature = {"operator": "Tm", "x": x, "y": y}
            updated = self.stream
            for start, end, replacement in sorted(replacements, reverse=True):
                updated = updated[:start] + replacement + updated[end:]
            self.apply_decoded_stream(updated)
            return
        try:
            hex_text = re.sub(r"\s+", "", self.edit_hex_var.get())
            text_bytes = bytes.fromhex(hex_text)
            size = float(self.edit_size_var.get())
            x = float(self.edit_x_var.get())
            y = float(self.edit_y_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid edit", f"Use valid hex bytes and numeric size/x/y values.\n\n{exc}", parent=self)
            return
        font = self.edit_font_var.get().strip()
        if not font.startswith("/"):
            font = "/" + font
        if font not in self.resources.get("/Font", {}):
            messagebox.showerror("Unknown font", f"{font} is not a font resource on this page.", parent=self)
            return
        replacements = []
        current_bytes = b"".join(item["value"] for item in op["operands"] if item["kind"] == "string")
        if text_bytes != current_bytes:
            string_operands = [item for item in op["operands"] if item["kind"] == "string"]
            if op["operator"] == "TJ" and len(string_operands) != 1:
                messagebox.showerror(
                    "Ambiguous TJ edit",
                    "This TJ operation has multiple string segments. To preserve its kerning adjustments, edit one segment at a time or use the decoded stream view.",
                    parent=self,
                )
                return
            cursor = 0
            for operand in string_operands:
                if len(text_bytes) != len(current_bytes):
                    replacement_bytes = text_bytes
                else:
                    replacement_bytes = text_bytes[cursor:cursor + len(operand["value"])]
                    cursor += len(operand["value"])
                original_token = self.stream[operand["start"]:operand["end"]]
                try:
                    replacement_token = replace_pdf_string_bytes(original_token, replacement_bytes)
                except ValueError as exc:
                    messagebox.showerror("Byte-preserving text edit", str(exc), parent=self)
                    return
                if replacement_token != original_token:
                    replacements.append((operand["start"], operand["end"], replacement_token))

        tf_index = None
        tm_index = None
        old_size = None
        old_font = None
        old_matrix = None
        for previous_index in range(index + 1):
            previous = self.operations[previous_index]
            values = [item["value"] for item in previous["operands"]]
            if previous["operator"] == "Tf" and len(values) >= 2:
                tf_index, old_font, old_size = previous_index, str(values[-2]), float(values[-1])
            elif previous["operator"] == "Tm" and len(values) >= 6:
                tm_index, old_matrix = previous_index, values[-6:]
        if tf_index is None or tm_index is None:
            messagebox.showerror("Position context unavailable", "This text operation has no preceding simple Tf and Tm to edit.", parent=self)
            return
        prefix = bytearray()
        if old_font != font or old_size != size:
            tf = self.operations[tf_index]
            if tf_index + 1 == index:
                font_operand, size_operand = tf["operands"][-2:]
                if old_font != font:
                    replacements.append((font_operand["start"], font_operand["end"], font.encode("ascii")))
                if old_size != size:
                    replacements.append((size_operand["start"], size_operand["end"], f"{size:g}".encode("ascii")))
            else:
                prefix.extend(f"{font} {size:g} Tf ".encode("ascii"))
        if float(old_matrix[4]) != x or float(old_matrix[5]) != y:
            tm = self.operations[tm_index]
            if tm_index + 1 == index:
                x_operand, y_operand = tm["operands"][-2:]
                if float(old_matrix[4]) != x:
                    replacements.append((x_operand["start"], x_operand["end"], f"{x:g}".encode("ascii")))
                if float(old_matrix[5]) != y:
                    replacements.append((y_operand["start"], y_operand["end"], f"{y:g}".encode("ascii")))
            else:
                prefix.extend((" ".join(str(value) for value in old_matrix[:4]) + f" {x:g} {y:g} Tm ").encode("ascii"))
        if prefix:
            replacements.append((op["start"], op["start"], bytes(prefix)))
        if not replacements:
            return
        self.reselect_signature = (text_bytes, x, y)
        updated = self.stream
        for start, end, replacement in sorted(replacements, reverse=True):
            updated = updated[:start] + replacement + updated[end:]
        self.apply_decoded_stream(updated)

    def _render_page_view(self):
        try:
            import pymupdf
            doc = pymupdf.open(self.preview_path or self.path)
            if doc.needs_pass and not doc.authenticate(self.password):
                return
            page = doc[self.page_index]
            self.page_transform = page.transformation_matrix
            self.page_pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            self.after_idle(self._draw_page_view)
        except Exception:
            self.page_pixmap = None

    def _show_pdf_structure(self, page):
        file_size = os.path.getsize(self.path)
        with open(self.path, "rb") as pdf_file:
            raw = pdf_file.read()
        header_end = raw.find(b"\n")
        header_end = len(raw) if header_end < 0 else header_end + 1
        startxref_pos = raw.rfind(b"startxref")
        xref_offset = "not found"
        if startxref_pos >= 0:
            tail = raw[startxref_pos + len(b"startxref"):].strip().splitlines()
            if tail:
                xref_offset = tail[0].decode("ascii", "replace")
        xref_position = int(xref_offset) if xref_offset.isdigit() else None

        def object_location(ref):
            if not hasattr(ref, "idnum"):
                return "direct object (no separate file offset)"
            offset = self.reader.xref.get(ref.generation, {}).get(ref.idnum)
            return f"object {ref.idnum} {ref.generation} at file byte {offset}" if offset is not None else f"object {ref.idnum} {ref.generation} (offset unavailable)"

        page_ref = page.indirect_reference
        contents = page.get("/Contents")
        content_refs = contents if isinstance(contents, list) else [contents]
        content_lines = [object_location(ref) for ref in content_refs if ref is not None]
        resources = page.get("/Resources")
        fonts = resources.get("/Font", {}) if resources else {}
        xobjects = resources.get("/XObject", {}) if resources else {}
        lines = [
            f"PDF byte layout · {file_size:,} bytes · PDF {raw[:header_end].decode('latin1', 'replace').strip()}",
            "",
            "BYTE ORDER",
            f"0–{header_end - 1}: file header and version marker",
            f"{header_end}–{xref_position - 1}: indirect objects (catalog, page tree, pages, resources, fonts, content streams, and other data)" if xref_position is not None else f"{header_end} onward: indirect objects and cross-reference data",
            f"{xref_position}–{startxref_pos - 1}: cross-reference table and trailer" if xref_position is not None else "Cross-reference table and trailer: location unavailable",
            f"{startxref_pos}–{file_size - 1}: startxref pointer and end marker",
            "The xref table maps each object number to its file offset. The trailer points to the catalog (/Root).",
            "",
            f"PAGE {self.page_index + 1} CONNECTIONS",
            f"Catalog: {object_location(self.reader.trailer.raw_get('/Root'))}",
            f"Page dictionary: {object_location(page_ref)}",
            f"Resources: {object_location(resources)} · {len(fonts)} font aliases · {len(xobjects)} XObjects",
            f"Fonts on this page: {', '.join(str(name) for name in fonts) or 'none'}",
            "Content stream(s):",
            *(f"  {item}" for item in content_lines),
            "",
            "READING THE BYTE VIEW",
            "The file is stored in byte order: header → indirect objects → xref → trailer/EOF.",
            "A content stream is one object among those objects. Its decoded offsets are counted after filters and encryption are decoded, so they are not file offsets.",
            f"startxref is at file byte {startxref_pos}; its value points to xref at byte {xref_offset}.",
        ]
        self._set_text(self.structure_text, "\n".join(lines))

    def apply_decoded_stream(self, edited):
        operations = parse_operations(edited)
        if not operations:
            if not messagebox.askyesno("No operators found", "The edited stream has no recognized operators. Apply it anyway?", parent=self):
                return
        if self.reader.is_encrypted and (self.reader._encryption.V != 1 or self.reader._encryption.R != 2):
            messagebox.showerror("Unsupported encryption", "Byte-preserving editing currently supports PDF Standard Security Handler revision 2 only (40-bit RC4). This PDF uses a different encryption revision.", parent=self)
            return
        candidate_streams = dict(self.edited_streams)
        source_stream = self._read_page_stream(self.reader.pages[self.page_index])
        if edited == source_stream:
            if self.page_index in self.removed_font_resources:
                candidate_streams[self.page_index] = bytes(edited)
            else:
                candidate_streams.pop(self.page_index, None)
        else:
            candidate_streams[self.page_index] = bytes(edited)
        self._clear_preview()
        if candidate_streams:
            self.preview_tempdir = tempfile.TemporaryDirectory(prefix="pdf-byte-explorer-")
            self.preview_path = os.path.join(self.preview_tempdir.name, "preview.pdf")
        try:
            if candidate_streams:
                self._write_rebuilt_pdf(candidate_streams, self.preview_path, self.removed_font_resources)
        except Exception as exc:
            self._clear_preview()
            messagebox.showerror("Could not apply edit", str(exc), parent=self)
            return
        previous_state = self._capture_edit_state()
        if candidate_streams != self.edited_streams:
            self.undo_stack.append(previous_state)
        self.edited_streams = candidate_streams
        self.unsaved_edits = bool(candidate_streams)
        self.stream = edited
        self.operations = operations
        self._populate_ops()
        self._render_page_view()
        if self.ops_tree.get_children():
            target = None
            if self.reselect_signature:
                signature = self.reselect_signature
                if isinstance(signature, dict):
                    for candidate_index, candidate in enumerate(self.operations):
                        if candidate["operator"] != signature.get("operator"):
                            continue
                        values = [item["value"] for item in candidate["operands"]]
                        if candidate["operator"] == "Tf" and len(values) >= 2 and str(values[-2]) == signature.get("font") and abs(float(values[-1]) - signature.get("size", 0)) < 0.001:
                            target = self._operation_id(self.page_index, candidate_index)
                            break
                        if candidate["operator"] == "Tm" and len(values) >= 6 and abs(float(values[-2]) - signature.get("x", 0)) < 0.001 and abs(float(values[-1]) - signature.get("y", 0)) < 0.001:
                            target = self._operation_id(self.page_index, candidate_index)
                            break
                else:
                    wanted_bytes, wanted_x, wanted_y = signature
                    for candidate_index, candidate in enumerate(self.operations):
                        if candidate["operator"] not in ("Tj", "TJ"):
                            continue
                        candidate_bytes = b"".join(item["value"] for item in candidate["operands"] if item["kind"] == "string")
                        origin = candidate.get("text_origin")
                        if candidate_bytes == wanted_bytes and origin and abs(origin[0] - wanted_x) < 0.001 and abs(origin[1] - wanted_y) < 0.001:
                            target = self._operation_id(self.page_index, candidate_index)
                            break
                self.reselect_signature = None
            fallback = next((item for item in self.ops_tree.get_children() if item.startswith(f"p{self.page_index}:o")), "")
            self.ops_tree.selection_set(target or fallback)
            if target or fallback:
                self.ops_tree.focus(target or fallback)
                self.ops_tree.see(target or fallback)
            self.select_operation()
        self.save_button.state(["!disabled"] if self.edited_streams else ["disabled"])
        self.unused_button.state(["!disabled"])
        self.undo_button.state(["!disabled"] if self.undo_stack else ["disabled"])
        self.status.configure(text=f"Applied page {self.page_index + 1} edit; {len(self.edited_streams)} page(s) pending. Save All Edits when ready.")

    def clean_confirmed_unused(self):
        """Remove only provably unused page fonts and path paint operators."""
        if not self.reader:
            messagebox.showinfo("Open a PDF first", "Open a PDF before cleaning unused items.", parent=self)
            return
        paint_ops = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*"}
        candidate_streams = dict(self.edited_streams)
        candidate_removed = {page: set(names) for page, names in self.removed_font_resources.items()}
        removable_fonts = []
        removable_paints = []
        changed_pages = set()
        for page_number, page in enumerate(self.reader.pages):
            stream = candidate_streams.get(page_number, self._read_page_stream(page))
            operations = parse_operations(stream)
            resources = page.get("/Resources", {})
            fonts = resources.get("/Font", {})
            used_fonts = set()
            path_active = False
            remove_ranges = []
            for op in operations:
                values = [item["value"] for item in op["operands"]]
                if op["operator"] == "Tf" and len(values) >= 2:
                    used_fonts.add(str(values[-2]))
                if op["operator"] in {"m", "l", "c", "v", "y", "re"}:
                    path_active = True
                elif op["operator"] in paint_ops:
                    if not path_active:
                        remove_ranges.append((op["start"], op["end"]))
                    path_active = False
            unused_fonts = set(str(name) for name in fonts) - used_fonts
            if unused_fonts:
                candidate_removed.setdefault(page_number, set()).update(unused_fonts)
                removable_fonts.extend(f"page {page_number + 1} {name}" for name in sorted(unused_fonts))
                candidate_streams[page_number] = stream
            if remove_ranges:
                updated = stream
                for start, end in reversed(remove_ranges):
                    updated = updated[:start] + updated[end:]
                candidate_streams[page_number] = updated
                changed_pages.add(page_number)
                removable_paints.extend(f"page {page_number + 1} bytes [{start}, {end})" for start, end in remove_ranges)
            if unused_fonts:
                changed_pages.add(page_number)
        if not changed_pages:
            messagebox.showinfo("Nothing to remove", "No unused font aliases or empty path paint operators were found.", parent=self)
            return
        details = [f"Unused font aliases: {len(removable_fonts)}", f"Path paint operators with no path: {len(removable_paints)}", "", "This removes only these page resource entries and decoded content bytes. It does not change metadata.", "Remove them now? You can undo before saving."]
        if not messagebox.askyesno("Remove unused fonts and strokes", "\n".join(details), parent=self):
            return
        if self.reader.is_encrypted and (self.reader._encryption.V != 1 or self.reader._encryption.R != 2):
            messagebox.showerror("Unsupported encryption", "Cleanup currently supports PDF Standard Security Handler revision 2 only.", parent=self)
            return
        self._clear_preview()
        try:
            self.preview_tempdir = tempfile.TemporaryDirectory(prefix="pdf-byte-explorer-")
            self.preview_path = os.path.join(self.preview_tempdir.name, "preview.pdf")
            self._write_rebuilt_pdf(candidate_streams, self.preview_path, candidate_removed)
        except Exception as exc:
            self._clear_preview()
            messagebox.showerror("Could not clean PDF", str(exc), parent=self)
            return
        self.undo_stack.append(self._capture_edit_state())
        self.edited_streams = {
            page: data for page, data in candidate_streams.items()
            if data != self._read_page_stream(self.reader.pages[page]) or page in candidate_removed
        }
        self.removed_font_resources = candidate_removed
        self.unsaved_edits = True
        self.load_page(self.page_index)
        self.save_button.state(["!disabled"])
        self.unused_button.state(["!disabled"])
        self.undo_button.state(["!disabled"])
        self.status.configure(text=f"Removed {len(removable_fonts)} unused font resource(s) and {len(removable_paints)} empty path paint(s); review before saving")

    def audit_pending_pdf(self):
        """Inspect page resources and drawing operators without changing the PDF."""
        if not self.reader or not self.path:
            messagebox.showinfo("Open a PDF first", "Open a PDF before running the audit.", parent=self)
            return
        audit_path = self.preview_path or self.path
        try:
            reader = PdfReader(audit_path)
            if reader.is_encrypted and not reader.decrypt(self.password):
                raise ValueError("Could not decrypt the current PDF for auditing.")
            lines = [
                f"Auditing: {audit_path}",
                f"Pages: {len(reader.pages)}",
                "Read-only: this audit does not remove or modify objects.",
                "Fonts are page resources; path strokes are operators in page content streams.",
                "PDF metadata does not store a count of fonts or path strokes.",
                "",
            ]
            paint_ops = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*"}
            visual_pages = []
            total_unused_fonts = 0
            total_empty_paints = 0
            for page_number, page in enumerate(reader.pages, 1):
                resources = page.get("/Resources", {})
                fonts = resources.get("/Font", {})
                xobjects = resources.get("/XObject", {})
                stream = self._read_page_stream(page)
                operations = parse_operations(stream)
                used_fonts = set()
                used_xobjects = set()
                text_codes = {}
                active_font = None
                for op in operations:
                    values = [item["value"] for item in op["operands"]]
                    if op["operator"] == "Tf" and len(values) >= 2:
                        active_font = str(values[-2])
                        used_fonts.add(active_font)
                    elif op["operator"] == "Do" and values:
                        used_xobjects.add(str(values[-1]))
                    elif op["operator"] in ("Tj", "TJ") and active_font:
                        text_codes.setdefault(active_font, set()).update(
                            byte
                            for item in op["operands"] if item["kind"] == "string"
                            for byte in item["value"]
                        )

                lines += [f"PAGE {page_number}", f"Decoded content stream: {len(stream):,} bytes"]
                lines.append("Fonts:")
                font_rows = []
                unused_font_names = []
                if not fonts:
                    lines.append("  No page font resources.")
                for name, ref in sorted(fonts.items(), key=lambda item: str(item[0])):
                    font = ref.get_object()
                    used = str(name) in used_fonts
                    cmap = {}
                    if font.get("/ToUnicode"):
                        try:
                            cmap = map_cmap(font["/ToUnicode"].get_object().get_data())
                        except Exception:
                            pass
                    used_codes = text_codes.get(str(name), set())
                    unused_mappings = [code.hex().upper() for code in cmap if len(code) == 1 and code[0] not in used_codes]
                    object_info = f"object {ref.idnum} {ref.generation} R" if hasattr(ref, "idnum") else "direct object"
                    if not used:
                        unused_font_names.append(str(name))
                        total_unused_fonts += 1
                        lines.append(f"  CLEANUP CANDIDATE: {name} is not selected by any Tf operation on this page.")
                    lines.append(
                        f"  {name}: {font.get('/Subtype', 'unknown subtype')}, {object_info}, "
                        f"{'referenced by Tf' if used else 'not referenced by Tf'}, "
                        f"{len(used_codes)} distinct encoded byte values, "
                        f"{len(cmap)} ToUnicode mappings ({len(unused_mappings)} unused on this page)"
                    )
                    font_rows.append((str(name), str(font.get("/Subtype", "?")), used, len(used_codes), len(cmap), len(unused_mappings)))
                    if unused_mappings:
                        lines.append("    Unused on this page: " + " ".join(unused_mappings))

                lines.append("XObjects:")
                if not xobjects:
                    lines.append("  No page XObject resources.")
                for name, ref in sorted(xobjects.items(), key=lambda item: str(item[0])):
                    obj = ref.get_object()
                    lines.append(f"  {name}: {obj.get('/Subtype', 'unknown subtype')}, {'used by Do' if str(name) in used_xobjects else 'not used by Do'}")

                lines.append("Path paint operations:")
                strokes = [(i, op) for i, op in enumerate(operations) if op["operator"] in paint_ops]
                stroke_rows = []
                path_points = []
                path_active = False
                if not strokes:
                    lines.append("  None.")
                for op in operations:
                    name = op["operator"]
                    values = [item["value"] for item in op["operands"]]
                    try:
                        numbers = [float(value) for value in values]
                    except (TypeError, ValueError):
                        numbers = []
                    if name in ("m", "l") and len(numbers) >= 2:
                        path_points.append((numbers[-2], numbers[-1]))
                    elif name == "re" and len(numbers) >= 4:
                        x, y, width, height = numbers[-4:]
                        path_points.extend(((x, y), (x + width, y + height)))
                    elif name == "c" and len(numbers) >= 6:
                        path_points.extend(((numbers[-6], numbers[-5]), (numbers[-4], numbers[-3]), (numbers[-2], numbers[-1])))
                    elif name in ("v", "y") and len(numbers) >= 4:
                        path_points.extend(((numbers[-4], numbers[-3]), (numbers[-2], numbers[-1])))
                    if name in {"m", "l", "c", "v", "y", "re"}:
                        path_active = True
                    if name in paint_ops:
                        bounds = None
                        if path_points:
                            xs, ys = zip(*path_points)
                            bounds = (min(xs), min(ys), max(xs), max(ys))
                        cleanup_candidate = not path_active
                        stroke_rows.append({"operator": name, "start": op["start"], "end": op["end"], "bounds": bounds, "cleanup_candidate": cleanup_candidate})
                        if cleanup_candidate:
                            total_empty_paints += 1
                            lines.append(f"  CLEANUP CANDIDATE: {name} has no preceding path; decoded-stream bytes [{op['start']}, {op['end']}).")
                        path_points = []
                        path_active = False
                for ordinal, (operation_index, op) in enumerate(strokes, 1):
                    lines.append(
                        f"  {ordinal}. {op['operator']} at decoded-stream bytes "
                        f"[{op['start']}, {op['end']}) (operation {operation_index})"
                    )
                lines.append(f"  Total path paint operations: {len(strokes)}")
                lines.append(f"  Cleanup candidates on page {page_number}: {len(unused_font_names)} unused font resource(s), {sum(1 for row in stroke_rows if row['cleanup_candidate'])} paint operator(s) with no path.")
                lines.append("")
                visual_pages.append({"number": page_number, "fonts": font_rows, "strokes": stroke_rows, "mediabox": tuple(float(v) for v in page.mediabox)})
            self.audit_visual_pages = visual_pages
            self.audit_page_combo.configure(values=[str(item["number"]) for item in visual_pages])
            if visual_pages:
                current_page = min(self.page_index + 1, len(visual_pages))
                self.audit_page_combo.current(current_page - 1)
            total_fonts = sum(len(item["fonts"]) for item in visual_pages)
            total_strokes = sum(len(item["strokes"]) for item in visual_pages)
            self.audit_summary.configure(text=f"{len(visual_pages)} pages · inventory: {total_fonts} fonts, {total_strokes} path paints · cleanup candidates: {total_unused_fonts} fonts, {total_empty_paints} empty paints")
            lines.insert(5, f"CLEANUP CANDIDATES: {total_unused_fonts} unused font resources and {total_empty_paints} paint operators with no constructed path.")
            lines.insert(6, "All other font mappings and path paints are inventory only; cleanup does not remove them.")
            self._set_text(self.audit_text, "\n".join(lines))
            self._render_audit_visuals()
            self.tabs.select(self.audit_tab)
            self.status.configure(text=f"Read-only audit complete for {len(reader.pages)} page(s); no PDF data was changed")
        except Exception as exc:
            messagebox.showerror("Audit failed", str(exc), parent=self)

    def _render_audit_visuals(self):
        if not self.audit_visual_pages:
            return
        page_index = self.audit_page_combo.current()
        if page_index < 0 or page_index >= len(self.audit_visual_pages):
            return
        page = self.audit_visual_pages[page_index]
        self.audit_font_tree.delete(*self.audit_font_tree.get_children())
        for name, subtype, used, byte_count, mapping_count, unused_count in page["fonts"]:
            self.audit_font_tree.insert(
                "", "end", values=(name, subtype.replace("/", ""), "Used" if used else "Remove", byte_count, f"{unused_count}/{mapping_count}")
            )
        self._draw_audit_strokes()

    def _draw_audit_strokes(self):
        if not hasattr(self, "audit_stroke_canvas") or not self.audit_visual_pages:
            return
        index = self.audit_page_combo.current()
        if index < 0 or index >= len(self.audit_visual_pages):
            return
        page = self.audit_visual_pages[index]
        canvas = self.audit_stroke_canvas
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1)
        left, top, right, bottom = page["mediabox"]
        page_width, page_height = max(right - left, 1), max(bottom - top, 1)
        pad = 22
        scale = min(max(width - pad * 2, 1) / page_width, max(height - pad * 2, 1) / page_height)
        draw_width, draw_height = page_width * scale, page_height * scale
        x0, y0 = (width - draw_width) / 2, (height - draw_height) / 2
        canvas.create_rectangle(x0, y0, x0 + draw_width, y0 + draw_height, fill="#ffffff", outline="#e2e7ef", width=1)
        canvas.create_text(x0 + 7, y0 + 7, anchor="nw", text=f"Page {page['number']} · {len(page['strokes'])} path paints", fill="#5f6368", font=("Segoe UI", 8))
        for ordinal, stroke in enumerate(page["strokes"], 1):
            bounds = stroke["bounds"]
            if not bounds:
                continue
            bx0, by0, bx1, by1 = bounds
            px0 = x0 + (bx0 - left) * scale
            px1 = x0 + (bx1 - left) * scale
            py0 = y0 + (bottom - by1) * scale
            py1 = y0 + (bottom - by0) * scale
            if abs(px1 - px0) < 2:
                px1 = px0 + 2
            if abs(py1 - py0) < 2:
                py1 = py0 + 2
            color = "#0866ff" if stroke["operator"] in ("S", "s") else "#18a789"
            canvas.create_rectangle(px0, py0, px1, py1, outline=color, width=2)
            if ordinal <= 70:
                canvas.create_oval(px0 - 2, py0 - 2, px0 + 2, py0 + 2, fill=color, outline="")
        canvas.create_text(x0 + 7, y0 + draw_height - 7, anchor="sw", text="Blue: stroke · Green: fill/combined paint · marks show approximate path bounds", fill="#5f6368", font=("Segoe UI", 8))

    def _write_rebuilt_pdf(self, edited, destination, removed_fonts=None):
        """Rebuild raw PDF bytes while preserving the source security handler."""
        page_streams = {self.page_index: bytes(edited)} if isinstance(edited, (bytes, bytearray)) else {int(page): bytes(stream) for page, stream in edited.items()}
        removed_fonts = removed_fonts or {}
        original = open(self.path, "rb").read()
        source = PdfReader(self.path, strict=False)
        if source.is_encrypted and not source.decrypt(self.password):
            raise ValueError("Could not decrypt the source PDF for rebuilding.")
        startxref_position = original.rfind(b"startxref")
        if startxref_position < 0:
            raise ValueError("This PDF has no startxref marker.")
        try:
            source_xref_offset = int(original[startxref_position + len(b"startxref"):].strip().splitlines()[0])
        except (ValueError, IndexError) as exc:
            raise ValueError("This PDF has an unreadable startxref value.") from exc
        if original[source_xref_offset:source_xref_offset + 4] != b"xref":
            raise ValueError("This PDF uses an xref stream; raw byte rebuild currently requires a classic xref table.")
        if source.xref_objStm:
            raise ValueError("This PDF uses compressed object streams; direct raw rebuild is not supported for it.")
        if any(generation not in (0, 65535) for generation in source.xref):
            raise ValueError("This PDF uses nonzero object generations; direct raw rebuild is not supported for it.")

        objects = {}
        for generation, entries in source.xref.items():
            if generation == 65535:
                continue
            for object_number, offset in entries.items():
                if not object_number or not offset:
                    continue
                end, _, _, _, _ = pdf_object_end(original, offset, source)
                objects[(object_number, generation)] = original[offset:end]
        object_order = sorted(objects, key=lambda ref: source.xref[ref[1]][ref[0]])

        stream_refs = {}
        for page_number, decoded_stream in page_streams.items():
            if page_number < 0 or page_number >= len(source.pages):
                raise ValueError(f"Page {page_number + 1} is outside this document.")
            contents = source.pages[page_number].raw_get("/Contents")
            if not hasattr(contents, "idnum") and hasattr(contents, "__len__") and len(contents) == 1:
                contents = contents[0]
            if not hasattr(contents, "idnum"):
                raise ValueError(f"Page {page_number + 1} does not have one indirect content stream.")
            stream_refs[(contents.idnum, contents.generation)] = (page_number, decoded_stream)

        for ref, (page_number, decoded_stream) in stream_refs.items():
            raw_object = objects.get(ref)
            if raw_object is None:
                raise ValueError(f"Page {page_number + 1}'s content object is not directly addressable.")
            end, dict_start, dict_end, stream_start, data_end = pdf_object_end(original, source.xref[ref[1]][ref[0]], source)
            if dict_start is None:
                raise ValueError(f"Page {page_number + 1}'s content object is not a stream.")
            page_contents = source.pages[page_number].raw_get("/Contents")
            if not hasattr(page_contents, "idnum") and hasattr(page_contents, "__len__") and len(page_contents) == 1:
                page_contents = page_contents[0]
            stream_object = page_contents.get_object()
            encoded = encode_stream_data(stream_object, decoded_stream)
            if source.is_encrypted:
                crypt_filter = source._encryption._make_crypt_filter(ref[0], ref[1])
                encoded = crypt_filter.stm_crypt.encrypt(encoded)
            absolute_offset = source.xref[ref[1]][ref[0]]
            local_dict_start = dict_start - absolute_offset
            local_dict_end = dict_end - absolute_offset
            dictionary = raw_object[local_dict_start:local_dict_end]
            indirect_length = re.search(rb"/Length\s+(\d+)\s+(\d+)\s+R", dictionary)
            if indirect_length:
                length_ref = (int(indirect_length.group(1)), int(indirect_length.group(2)))
                length_object = objects.get(length_ref)
                if length_object is None:
                    raise ValueError("The indirect stream /Length object is not directly addressable.")
                header = re.match(rb"\d+\s+\d+\s+obj\s*", length_object)
                if not header:
                    raise ValueError("The indirect stream /Length object has an unsupported syntax.")
                body_start = header.end()
                value_match = re.match(rb"\s*\d+", length_object[body_start:])
                if not value_match:
                    raise ValueError("The indirect stream /Length object is not a numeric value.")
                value_start = body_start + value_match.start()
                value_end = body_start + value_match.end()
                objects[length_ref] = length_object[:value_start] + str(len(encoded)).encode("ascii") + length_object[value_end:]
                updated = raw_object
            else:
                updated = rewrite_length_in_dictionary(raw_object, local_dict_start, local_dict_end, len(encoded))
            local_stream_start = stream_start - absolute_offset
            local_data_end = data_end - absolute_offset
            objects[ref] = updated[:local_stream_start] + encoded + updated[local_data_end:]

        if removed_fonts:
            for page_number, names in removed_fonts.items():
                page = source.pages[page_number]
                resources = page.raw_get("/Resources")
                if hasattr(resources, "idnum"):
                    ref = (resources.idnum, resources.generation)
                    raw_resource = objects.get(ref)
                    if raw_resource is None:
                        raise ValueError(f"Page {page_number + 1}'s resource object is not directly addressable.")
                    start = raw_resource.find(b"<<")
                    end = dictionary_end(raw_resource, start)
                    updated_resources = DictionaryObject(resources.get_object())
                    fonts = updated_resources.get("/Font", {})
                    updated_fonts = DictionaryObject({key: value for key, value in fonts.items() if str(key) not in names})
                    updated_resources[NameObject("/Font")] = updated_fonts
                    buffer = BytesIO()
                    updated_resources.write_to_stream(buffer, None)
                    objects[ref] = raw_resource[:start] + buffer.getvalue() + raw_resource[end:]
                else:
                    page_ref = page.indirect_reference
                    ref = (page_ref.idnum, page_ref.generation)
                    raw_page = objects[ref]
                    start = raw_page.find(b"<<")
                    end = dictionary_end(raw_page, start)
                    objects[ref] = replace_font_entries_in_dictionary(raw_page, start, end, names)

        first_object_offset = min(source.xref[generation][object_number] for object_number, generation in objects)
        header_end = first_object_offset
        output = bytearray(original[:header_end])
        offsets = {}
        for ref in object_order:
            offsets[ref] = len(output)
            output.extend(objects[ref])
            output.extend(b"\n")
        xref_offset = len(output)
        source_size = int(source.trailer.raw_get("/Size") or (max((object_number for object_number, _ in objects), default=0) + 1))
        max_object = source_size - 1
        output.extend(f"xref\n0 {source_size}\n0000000000 65535 f \n".encode("ascii"))
        for object_number in range(1, source_size):
            offset = offsets.get((object_number, 0))
            output.extend((f"{offset:010d} 00000 n \n" if offset is not None else "0000000000 65535 f \n").encode("ascii"))

        output.extend(b"trailer\n")
        trailer_start = original.rfind(b"trailer", 0, original.rfind(b"startxref"))
        trailer_dict_start = original.find(b"<<", trailer_start)
        trailer_dict_end = dictionary_end(original, trailer_dict_start)
        if trailer_start >= 0 and trailer_dict_start >= 0 and trailer_dict_end >= 0 and b"/Prev" not in original[trailer_dict_start:trailer_dict_end] and b"/XRefStm" not in original[trailer_dict_start:trailer_dict_end]:
            output.extend(original[trailer_dict_start:trailer_dict_end])
        else:
            trailer = DictionaryObject()
            for key, value in source.trailer.items():
                if str(key) not in ("/Size", "/Prev", "/XRefStm"):
                    trailer[key] = value
            from pypdf.generic import NumberObject
            trailer[NameObject("/Size")] = NumberObject(source_size)
            trailer_buffer = BytesIO()
            trailer.write_to_stream(trailer_buffer, None)
            output.extend(trailer_buffer.getvalue())
        output.extend(f"\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
        with open(destination, "wb") as target:
            target.write(output)

    def save_edited_copy(self):
        if not self.edited_streams or not self.preview_path:
            messagebox.showinfo("No edits to save", "Apply at least one page edit first.", parent=self)
            return False
        destination = filedialog.asksaveasfilename(title="Save Edited PDF Copy", defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not destination:
            return False
        try:
            import shutil
            shutil.copyfile(self.preview_path, destination)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return False
        self.unsaved_edits = False
        self.undo_stack = []
        self.undo_button.state(["disabled"])
        messagebox.showinfo("Saved", f"Edited PDF copy saved to:\n{destination}", parent=self)
        return True

    def _close_window(self):
        if not self.unsaved_edits:
            self.destroy()
            return
        choice = messagebox.askyesnocancel(
            "Save edits before quitting?",
            f"You have edits on {len(self.edited_streams)} page(s). Save them before closing?",
            parent=self,
        )
        if choice is True:
            if self.save_edited_copy():
                self.destroy()
        elif choice is False:
            self.destroy()

    def _draw_page_view(self, origin=None):
        if self.page_pixmap is None:
            return
        from PIL import Image, ImageTk
        if origin is not None:
            self.selected_origin = origin
        origin = self.selected_origin
        pix = self.page_pixmap
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        import pymupdf
        point = pymupdf.Point(*origin) * self.page_transform if origin else None
        for canvas, image_attr in ((getattr(self, "page_canvas", None), "page_image"), (getattr(self, "side_canvas", None), "side_page_image")):
            if canvas is None:
                continue
            cw, ch = max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1)
            if cw <= 1 or ch <= 1:
                continue
            scale = min(cw / pix.width, ch / pix.height)
            rendered = image.resize((max(1, int(pix.width * scale)), max(1, int(pix.height * scale))))
            photo = ImageTk.PhotoImage(rendered)
            setattr(self, image_attr, photo)
            canvas.delete("all")
            x0, y0 = (cw - rendered.width) / 2, (ch - rendered.height) / 2
            canvas.create_image(x0, y0, anchor="nw", image=photo)
            if point:
                px = x0 + point.x * 1.5 * scale
                py = y0 + point.y * 1.5 * scale
                canvas.create_oval(px-6, py-6, px+6, py+6, fill="#d13d35", outline="white", width=2)

    def _decode_bytes(self, data, font_name):
        if not font_name or font_name not in self.resources.get("/Font", {}):
            return data.decode("latin1", "replace"), ["No current font resource; showing byte values as Latin-1 fallback."]
        font = self.resources["/Font"][font_name].get_object()
        cmap = {}
        if font.get("/ToUnicode"):
            try:
                cmap = map_cmap(font["/ToUnicode"].get_object().get_data())
            except Exception:
                cmap = {}
        encoding = font.get("/Encoding")
        differences = {}
        if encoding:
            enc = encoding.get_object() if hasattr(encoding, "get_object") else encoding
            diff = enc.get("/Differences", []) if hasattr(enc, "get") else []
            code = None
            for item in diff:
                if isinstance(item, int):
                    code = item
                elif code is not None:
                    differences[code] = str(item).lstrip("/")
                    code += 1
        encoding_obj = encoding.get_object() if hasattr(encoding, "get_object") else encoding
        encoding_name = str(encoding_obj) if isinstance(encoding_obj, str) else ""
        pieces = []
        details = []
        for byte in data:
            code = bytes([byte])
            if code in cmap:
                char = cmap[code]
                pieces.append(char)
                details.append(f"byte {byte:02X} -> /ToUnicode U+{ord(char[0]):04X} {char!r}" if char else f"byte {byte:02X} -> empty Unicode mapping")
            else:
                glyph = differences.get(byte)
                custom = re.fullmatch(r"EX(\d{3})000", glyph or "")
                if custom:
                    char = chr(int(custom.group(1)))
                    pieces.append(char)
                    details.append(f"byte {byte:02X} -> glyph /{glyph} via /Encoding /Differences -> {char!r}; /ToUnicode has no entry")
                elif encoding_name == "/WinAnsiEncoding":
                    char = bytes([byte]).decode("cp1252", "replace")
                    pieces.append(char)
                    details.append(f"byte {byte:02X} -> /WinAnsiEncoding -> {char!r}; /ToUnicode has no entry")
                elif encoding_name == "/MacRomanEncoding":
                    char = bytes([byte]).decode("mac_roman", "replace")
                    pieces.append(char)
                    details.append(f"byte {byte:02X} -> /MacRomanEncoding -> {char!r}; /ToUnicode has no entry")
                elif encoding_name == "/SymbolEncoding":
                    char = _symbol_encoding[byte]
                    pieces.append(char)
                    details.append(f"byte {byte:02X} -> /SymbolEncoding -> {char!r}; /ToUnicode has no entry")
                elif glyph:
                    pieces.append(chr(0xFFFD))
                    details.append(f"byte {byte:02X} -> glyph /{glyph} via /Encoding /Differences; Unicode mapping not recognized")
                else:
                    pieces.append(chr(0xFFFD))
                    details.append(f"byte {byte:02X} -> no explicit /ToUnicode mapping; encoding fallback is needed")
        return "".join(pieces), details

    def select_font(self, _event=None):
        if self.font_combo.get():
            self.render_font(self.font_combo.get())

    def render_font(self, name):
        fonts = self.resources.get("/Font", {})
        if name not in fonts:
            return
        ref = fonts[name]
        font = ref.get_object()
        indirect = getattr(ref, "indirect_reference", None)
        object_id = f"object {indirect.idnum} {indirect.generation} R" if indirect else "direct font object"
        subtype = str(font.get("/Subtype", "unknown"))
        encoding = font.get("/Encoding")
        encoding = encoding.get_object() if hasattr(encoding, "get_object") else encoding
        encoding_name = str(encoding.get("/BaseEncoding", "custom encoding")) if hasattr(encoding, "get") else str(encoding or "not specified")
        differences = encoding.get("/Differences", []) if hasattr(encoding, "get") else []
        widths = font.get("/Widths")
        widths = widths.get_object() if hasattr(widths, "get_object") else widths
        to_unicode = font.get("/ToUnicode")
        charprocs = font.get("/CharProcs")
        sizes = []
        for op in self.operations:
            values = [item["value"] for item in op["operands"]]
            if op["operator"] == "Tf" and len(values) >= 2 and str(values[-2]) == name:
                try:
                    size = float(values[-1])
                    if size not in sizes:
                        sizes.append(size)
                except (TypeError, ValueError):
                    pass
        sizes_text = ", ".join(f"{size:g} pt" for size in sizes) if sizes else "not selected by a Tf operator on this page"
        font_matrix = font.get("/FontMatrix")
        first, last = font.get("/FirstChar"), font.get("/LastChar")
        lines = [
            f"/{name} → {object_id}",
            f"Type: {subtype} · used size(s) on this page: {sizes_text}",
            "The resource name is a page-local alias. A Tf operator selects this alias and its point size.",
            "",
            "FONT DATA SUMMARY",
            f"Encoding: {encoding_name} · {len(differences)} custom code/glyph entries",
            f"Character range: {first if first is not None else 'built-in'}–{last if last is not None else 'built-in'} · {len(widths) if widths is not None else 'built-in'} width entries",
            f"Font matrix: {' '.join(str(value) for value in font_matrix) if font_matrix is not None else 'default'}",
            f"Unicode map: {'present' if to_unicode is not None else 'not present'} · glyph procedures: {'present' if charprocs is not None else 'not present'}",
            "",
        ]
        lines.extend(self._digit_width_report(font, name))
        self._set_text(self.resource_text, "\n".join(lines))

    def _digit_width_report(self, font, name):
        widths = font.get("/Widths")
        widths = widths.get_object() if hasattr(widths, "get_object") else widths
        first = font.get("/FirstChar")
        if widths is None or first is None:
            return ["Digit advance widths (0-9): unavailable in this font dictionary; this font uses built-in metrics."]

        encoding = font.get("/Encoding")
        encoding = encoding.get_object() if hasattr(encoding, "get_object") else encoding
        differences = {}
        if hasattr(encoding, "get"):
            code = None
            for item in encoding.get("/Differences", []):
                if isinstance(item, int):
                    code = item
                elif code is not None:
                    differences[code] = str(item).lstrip("/")
                    code += 1

        current_size = None
        for op in self.operations:
            vals = [item["value"] for item in op["operands"]]
            if op["operator"] == "Tf" and len(vals) >= 2 and str(vals[-2]) == name:
                try:
                    current_size = float(vals[-1])
                except ValueError:
                    pass
        font_matrix = font.get("/FontMatrix", [1, 0, 0, 1, 0, 0])
        horizontal_scale = float(font_matrix[0]) if len(font_matrix) >= 4 else 1.0
        lines = ["Digit advance widths (0-9):", "Digit  Code  Glyph       Font units  Advance at current Tf"]
        glyph_digits = {f"EX{ord(d):03d}000": d for d in "0123456789"}
        found = 0
        for code, glyph in differences.items():
            digit = glyph_digits.get(glyph)
            index = code - int(first)
            if digit is None or not 0 <= index < len(widths):
                continue
            width = float(widths[index])
            scaled = f"{width * horizontal_scale * current_size:g} pt" if current_size is not None else "Tf size not found"
            lines.append(f"{digit:>5}  {code:02X}    /{glyph:<10} {width:>10g}  {scaled}")
            found += 1
        if not found:
            lines.append("No digit glyph mappings found in this font's /Encoding /Differences.")
        lines.append(f"Advance = width × Tf size × horizontal /FontMatrix scale ({horizontal_scale:g}); TJ adjustments can change it.")
        return lines

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")


if __name__ == "__main__":
    PdfExplorer().mainloop()
