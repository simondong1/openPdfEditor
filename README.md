# openPdfEditor

[![CI](https://github.com/simondong1/openPdfEditor/actions/workflows/ci.yml/badge.svg)](https://github.com/simondong1/openPdfEditor/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/simondong1/openPdfEditor?display_name=tag)](https://github.com/simondong1/openPdfEditor/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**openPdfEditor is the PDF editor for people who need control after the page is already “finished.”** Edit the actual decoded content stream: the text bytes, `Tm` coordinates, `Tf` font selections, `Tj` strings, resource aliases, and path operators. Preview the result beside the bytes, undo changes, and save a clean rebuilt PDF without an incremental-update trail or editor watermark.

Use it for precise PDF repair, document automation, reverse engineering, template maintenance, and workflows where changing one visible value should not mean handing the document to an online service or rebuilding it through a layout editor. Everything runs locally on Windows: no upload, account, or cloud copy. The original file remains untouched.

### Why openPdfEditor

Most PDF tools treat a page as a picture or a collection of invisible text boxes. openPdfEditor exposes the layer that actually makes the page: operators, bytes, fonts, widths, filters, encryption, object references, and xref offsets. When a number is wrong, change the number. When text is shifted, change its matrix. When a resource is unused, remove that resource deliberately. The preview confirms the rendered result before you save.

For low-level PDF edits, this is the shortest path from **“I can see the wrong value”** to **“I changed the exact stream data that draws it.”**

## Comparison

| Capability | openPdfEditor | Acrobat / PDF-XChange | Online PDF editors | pypdf / scripting libraries |
| --- | --- | --- | --- | --- |
| Primary purpose | Direct, controlled PDF editing at the content-stream level | Page layout, forms, markup, signing, OCR | Convenient browser-based page edits | Programmatic PDF creation and transformation |
| Where editing happens | Local decoded bytes and operators | High-level page/text abstractions | Uploaded copy on a vendor server | Python objects and generated serialization |
| Edit `Tm` x/y, `Tf`, `Tj`, `TJ` directly | **Yes** | Usually hidden | No | Only with custom parser code |
| See exact hex and decoded offsets | **Yes** | No | No | Not as an interactive workflow |
| See resource aliases, font widths, `/ToUnicode`, Type 3 data | **Yes** | Limited | No | Requires manual inspection |
| Upload required | **No** | No | **Usually yes** | No |
| Incremental revision history in output | **No incremental update is created** | Save-mode dependent | Vendor-dependent | Library-dependent |
| Original metadata/security objects | Preserved by the supported raw rebuild path | Tool-controlled | Vendor-controlled | Often reserialized |
| Live page preview tied to the selected operator | **Yes** | Page preview, without byte mapping | Page preview, without byte mapping | No |
| Best for | Exact repair, reverse engineering, private workflows | Polished document production | Fast one-off convenience edits | Batch pipelines and application integration |

The writer rebuilds supported PDFs instead of appending an incremental revision, so the previous revision is not retained in the output. This does not make edits undetectable: the changed content remains part of the PDF and may be compared with an original copy.

## Download first

1. Open the [latest release](https://github.com/simondong1/openPdfEditor/releases/latest).
2. Download `openPdfEditor.exe`.
3. Double-click the executable.
4. Click **Open PDF** and choose a document. The repository does not contain sample bank statements or user documents.

The release is a self-contained Windows build. Python and dependencies are not required. Windows may show SmartScreen for a new unsigned open-source executable; choose **More info → Run anyway** only if you downloaded the archive from this repository's Releases page.

## What it does

- Shows every page's decoded content-stream operation in one continuous, searchable document map.
- Explains `Tm`, `Tf`, `Tj`, `TJ`, path operators, current font, size, and baseline origin.
- Shows decoded offsets, exact hex bytes, ASCII, and byte-to-Unicode mappings.
- Follows page resource aliases such as `/F9` to their font objects and summarizes encoding, widths, font matrix, and digit advances.
- Displays a live page preview beside the byte editor. The marker is the start of the text baseline in PDF user space.
- Edits decoded text bytes, font aliases, font sizes, and text-matrix x/y values, then rebuilds a complete PDF for preview and saving.
- Supports undo across edits on different pages and `Ctrl+Z`.
- Offers an explicit, confirmation-gated **Delete Unused Fonts/Strokes** action. It removes only page font aliases never selected by `Tf` and empty path-paint operators identified by the tool.
- Preserves the original supported security handler, document ID, owner/user values, permissions, metadata objects, and encryption key while rebuilding edited PDFs.

### Visual tour

The viewer starts with a focused welcome screen. Open a PDF to reveal the editor, document map, byte breakdown, resource inspector, and preview.

![Welcome screen](docs/images/welcome.png)

The left map is continuous across pages. Search matches all pages; selecting a result switches to that page and keeps the selected operation visible.

![Operation map and preview](docs/images/operation-map.png)

The byte panel separates the decoded stream from the PDF file itself. A selected text operation shows its operator, font, size, baseline position, bytes, and Unicode interpretation.

![Decoded bytes and operation editor](docs/images/decoded-bytes.png)

The resource view keeps font information readable: page-local alias, object reference, selected sizes, encoding summary, font matrix, Unicode-map presence, and per-digit advances.

![Font resource summary](docs/images/font-resources.png)

These screenshots use a synthetic, non-sensitive example PDF. They are generated during the release build and are not required to run the application.

## Tutorial

### 1. Open and orient yourself

Open a PDF. The document map is ordered by page, then top-to-bottom position, then left-to-right position. `Tm` rows show text-matrix placement; `Tf` rows show font selection; `Tj` and `TJ` rows show strings; path rows are optional.

The preview marker is a baseline origin. It is not the top-left or center of a text box. PDF coordinates start at the lower-left of the page.

### 2. Read a text operation

Select a `Tj` row. Read the fields in this order:

```text
/F9 0.24 Tf       select page-local font alias /F9 at 0.24 points
1 0 0 1 326.1 714 Tm   set the text matrix; x=326.1, y=714
(...) Tj           show the string bytes using the active font and matrix
```

The resource view explains how `/F9` resolves through the page's `/Resources /Font` dictionary. For encoded fonts, the same byte is interpreted through the font's encoding and optional `/ToUnicode` map.

### 3. Edit and preview

Select a text operation and edit its decoded string bytes, font, size, x, or y. Click **Apply edit**. The app keeps edits in memory, rebuilds a preview, and updates the page preview. Change pages and continue editing; **Save All Edits** writes every pending page change together.

Use **Undo** or `Ctrl+Z` to restore the previous in-memory state. Closing with pending edits asks whether to save, discard, or cancel.

### 4. Inspect PDF structure

The structure view explains the file's byte order:

```text
PDF header → indirect objects → xref table → trailer → startxref → %%EOF
```

The page dictionary connects the page to resources and content-stream objects. Decoded stream offsets are offsets after encryption and stream filters are decoded; they are not offsets into the original file.

### 5. Save carefully

The writer currently supports the PDF layouts listed below. It rejects unsupported layouts before writing rather than silently changing them. The source PDF is never modified; save creates a new file.

## How this compares with normal PDF editors

| Capability | openPdfEditor | General PDF editor |
| --- | --- | --- |
| Goal | Learn and edit PDF internals | Produce polished documents quickly |
| Primary view | Operators, decoded bytes, resources, object offsets | Pages, text boxes, annotations |
| Text positioning | Direct `Tm`/`Td`/`Tf`/`Tj` stream edits | Layout and mouse-based positioning |
| Font understanding | Encoding, `/ToUnicode`, widths, Type 3 resources | Usually hidden behind a text tool |
| Encryption model | Preserves supported original security data while rebuilding | Usually creates a new PDF serialization/security setup |
| Best use | PDF reverse engineering, teaching, controlled byte edits | Forms, markup, signing, OCR, page composition |
| Not provided | Full validator, arbitrary font substitution, OCR, signing | Low-level byte-by-byte teaching view |

## Supported and unsupported PDFs

Supported byte-preserving rebuilds include unencrypted PDFs and PDF Standard Security Handler revision 2 (40-bit RC4) files with ordinary indirect objects, traditional xref tables, supported content filters, and a single page content stream.

The writer currently rejects xref streams, compressed object streams, nonzero object generations, multiple page content streams, unsupported filters or predictors, and newer encryption revisions. The parser is intentionally small: composite fonts, complex CMaps, nested Form XObjects, and text embedded in images need additional interpretation.

## Run from source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python pdf_explorer.py
```

Or double-click `Run PDF Byte Explorer.bat` after installing dependencies.

## Build the Windows executable

```powershell
python -m pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean --onefile --windowed --name openPdfEditor pdf_explorer.py
```

The executable is written to `dist\openPdfEditor.exe`. The tagged-release workflow performs this build automatically and attaches that single executable to the GitHub release.

## Contributing

Issues and pull requests are welcome. Please include:

- Windows version and Python version if running from source.
- The smallest non-sensitive PDF that reproduces the behavior, or a synthetic reproduction.
- Whether the issue concerns parsing, rendering, editing, rebuilding, or the user interface.
- A short before/after description and the relevant operator or object number.

Please do not upload private financial, medical, legal, or otherwise sensitive PDFs. Redact or create a synthetic file first.

Start with an issue for a design change, then open a focused pull request. Run `python -m py_compile pdf_explorer.py` before submitting.

## Credits

Created and maintained by **Simon Dong** (`simondong1`). Built with [pypdf](https://github.com/py-pdf/pypdf), [PyMuPDF](https://github.com/pymupdf/PyMuPDF), Tkinter, Pillow, and PyInstaller.

If openPdfEditor helps you understand a PDF, please [star the repository](https://github.com/simondong1/openPdfEditor) and share improvements through issues or pull requests.

## License and responsibility

openPdfEditor is released under the [MIT License](LICENSE). The software is provided without warranty. You are responsible for the PDFs you open, the edits you make, your legal right to edit them, and the files you distribute. The author and contributors are not responsible for document changes, data loss, corrupted output, security consequences, or any use of the tool. The tool is independent of the PDF files users choose to process and does not upload documents.
