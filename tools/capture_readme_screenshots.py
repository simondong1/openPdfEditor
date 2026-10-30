"""Capture safe README screenshots using a generated, non-sensitive PDF."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from PIL import ImageGrab
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "docs" / "images"
sys.path.insert(0, str(ROOT))

import pdf_explorer


def make_sample_pdf(destination: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    font_ref = writer._add_object(font)
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
    })
    page[NameObject("/Resources")] = resources

    lines = [
        "A PDF is objects, resources, and content streams.",
        "The text matrix sets the baseline start position.",
        "Tf selects a font resource and size.",
        "Tj shows the encoded string bytes.",
        "The preview dot marks the text baseline origin.",
        "Undo restores the previous in-memory edit.",
        "Each line is positioned by its own text matrix.",
        "Font widths determine how each glyph advances.",
        "Page resources connect aliases to font objects.",
        "The xref table points to objects in the file.",
        "Decoded byte offsets are not file offsets.",
        "Changes are rebuilt and saved to a new PDF.",
    ]
    stream_data = bytearray(b"BT\n/F1 14 Tf\n")
    for index, text in enumerate(lines):
        y = 720 - index * 36
        stream_data.extend(f"1 0 0 1 70 {y} Tm\n({text}) Tj\n".encode("ascii"))
    stream_data.extend(b"ET\n")
    content = DecodedStreamObject()
    content.set_data(bytes(stream_data))
    page[NameObject("/Contents")] = writer._add_object(content)
    with destination.open("wb") as output:
        writer.write(output)


def capture(app: pdf_explorer.PdfExplorer, name: str) -> None:
    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)
    app.update_idletasks()
    app.update()
    time.sleep(0.25)
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    width = app.winfo_width()
    height = app.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(IMAGE_DIR / name, optimize=True)
    app.attributes("-topmost", False)


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="openpdfeditor-demo-") as folder:
        sample = Path(folder) / "synthetic-example.pdf"
        make_sample_pdf(sample)
        app = pdf_explorer.PdfExplorer()
        app.geometry("1360x840")
        capture(app, "welcome.png")

        app.reader = PdfReader(str(sample))
        app.path = str(sample)
        app.password = ""
        app.edited_streams = {}
        app.removed_font_resources = {}
        app.page_combo.configure(values=["1"])
        app.page_combo.current(0)
        app.welcome_frame.pack_forget()
        app.workspace_body.pack(fill="both", expand=True, padx=14, pady=(10, 8))
        app.file_label.configure(text="Synthetic example.pdf  ·  1 page")
        app.load_page(0)
        app.undo_button.state(["disabled"])
        app.unused_button.state(["!disabled"])
        app.save_button.state(["disabled"])

        text_operation = next(index for index, op in enumerate(app.operations) if op["operator"] == "Tj")
        matrix_operation = next(index for index, op in enumerate(app.operations) if op["operator"] == "Tm")
        app.ops_tree.selection_set(app._operation_id(0, matrix_operation))
        app.ops_tree.focus(app._operation_id(0, matrix_operation))
        app.select_operation()
        app.tabs.select(app.content_tab)
        capture(app, "operation-map.png")
        app.ops_tree.selection_set(app._operation_id(0, text_operation))
        app.ops_tree.focus(app._operation_id(0, text_operation))
        app.select_operation()
        app.toggle_preview()
        capture(app, "decoded-bytes.png")
        app.toggle_preview()
        app.tabs.select(app.resources_tab)
        app.font_combo.set("/F1")
        app.render_font("/F1")
        capture(app, "font-resources.png")
        app.destroy()


if __name__ == "__main__":
    main()
