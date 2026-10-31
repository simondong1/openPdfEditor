# openPdfEditor

[![CI](https://github.com/simondong1/openPdfEditor/actions/workflows/ci.yml/badge.svg)](https://github.com/simondong1/openPdfEditor/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/simondong1/openPdfEditor?display_name=tag)](https://github.com/simondong1/openPdfEditor/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Offline PDF editor comparison: choose the right tool

openPdfEditor is an offline Windows PDF editor for precise text, font, and positioning changes. It shows the page preview beside the controls used to make each change, so you can edit a specific part of a PDF without uploading it or using a full document-layout suite.

| What you need to do | Typical choice | How openPdfEditor differs |
| --- | --- | --- |
| Design pages, forms, and signatures | Acrobat, PDF-XChange, Foxit, or another desktop PDF editor | Focuses on precise text, font, and position changes with the page preview beside them |
| Edit a PDF in a browser | An online PDF editor | Opens the file locally; no upload, account, or cloud copy |
| Automate many PDFs | A PDF programming library | Provides a visual editor with search, preview, and undo instead of requiring a script |
| View raw file bytes | A general hex editor | Shows PDF text and font information in the context of the rendered page |
| Change an exact value and inspect the result | **openPdfEditor** | Edit the page's actual text and positioning data, then save a rebuilt PDF |

**Choose a desktop editor for page design, an online editor for quick browser edits, and openPdfEditor when you need precise text or position changes with local processing and control over the saved file.**

## Download openPdfEditor for Windows

1. Download [`openPdfEditor.exe`](https://github.com/simondong1/openPdfEditor/releases/latest/download/openPdfEditor.exe).
2. Double-click it. It is a self-contained Windows application and does not open a terminal window.
3. Click **Open PDF** and choose a document.

[![GitHub downloads](https://img.shields.io/github/downloads/simondong1/openPdfEditor/total?label=downloads)](https://github.com/simondong1/openPdfEditor/releases) This live counter shows actual GitHub release downloads.

The [release page](https://github.com/simondong1/openPdfEditor/releases/latest) includes version notes and the same executable as a downloadable asset. Python and dependencies are not required.

Windows may show SmartScreen for a new unsigned open-source executable. Run it only if you downloaded it from this repository's Releases page.

## What changes in the saved PDF?

| What happens when you save? | openPdfEditor | Add changes to the existing PDF | Export a rebuilt PDF |
| --- | --- | --- | --- |
| Is an earlier saved version kept in the file? | **No** | It may be, depending on the save option | Usually no |
| How can file size change? | It may grow or shrink when the file is rebuilt | It often grows as changes are added | It may grow or shrink during export |
| Can someone tell it was edited? | **Possibly.** Changes can be found by comparing with an original | Changes may be found the same way | Changes may be found the same way |
| Does saving replace your original? | **No.** It creates a new file | Depends on the save option | Usually creates a new file |
| Is the original password protection retained? | **Yes**, for supported PDFs | Depends on the product | Depends on the product |

The important difference is that openPdfEditor saves one rebuilt PDF instead of adding a new version to the end of the old file. A small text edit may still change the final file size because the document is reconstructed when saved.

## What you can do

| Workflow | What you get |
| --- | --- |
| Find a value | Search every page and jump to the matching text and its location |
| Change text | Edit the text shown on the page, including supported encoded characters |
| Move text | Adjust the text position and see the result in the page preview |
| Check fonts | Inspect the selected font, size, character widths, and displayed characters |
| Understand a page | See the page, its text, fonts, and drawing details together |
| Stay in control | Keep edits across pages, undo with `Ctrl+Z`, and review before saving |
| Clean unused resources | Confirm removal of unused fonts and empty drawing instructions; undo before saving |

## See it in action

Open a PDF to reveal the editor. The welcome screen stays simple until a document is open.

![Welcome screen](docs/images/welcome.png)

Search across pages and select a result to jump to its page and preview location.

![Operation map and preview](docs/images/operation-map.png)

Inspect and edit the selected text, font, size, and position beside the page preview.

![Decoded bytes and operation editor](docs/images/decoded-bytes.png)

Review the fonts used on the page, including character widths and displayed characters.

![Font resource summary](docs/images/font-resources.png)

Screenshots show a synthetic PDF and contain no user documents.

## Quick workflow

| Step | Do this | What you see |
| --- | --- | --- |
| 1. Find | Search all pages and select a text item | The matching page and text are highlighted together |
| 2. Understand | Review the text, font, size, and position | The page preview stays linked to your selection |
| 3. Change | Edit text, font, size, or position; use **Undo** or `Ctrl+Z` | Preview updates; edits stay pending across pages |
| 4. Save | Choose **Save All Edits** | A rebuilt PDF is written to a new file |

The preview marker shows where text begins along its baseline. It is not the corner of a text box. PDF pages measure position from the lower-left corner.

## PDF compatibility

openPdfEditor works best with standard PDFs containing selectable text, common fonts, and ordinary page layouts. Some modern password protection, complex fonts, unusual page structures, and text stored only as an image are not supported. Unsupported files are rejected before saving; your original remains untouched.

## Common questions

**What is openPdfEditor?** It is an offline Windows PDF editor for changing text, fonts, positions, and page data while keeping a live preview beside the edit.

**How is it different from Acrobat or an online PDF editor?** Those tools focus on page layout and convenience. openPdfEditor is for the cases where the exact value, position, font, privacy, or saved-file structure matters.

**Does it upload my PDF?** No. The application runs locally and opens the file from your computer.

**Does it hide that a PDF was edited?** No tool can promise that. openPdfEditor saves one rebuilt output instead of appending an earlier revision, but changed content can still be compared with an original.

**How do I install it?** Download the one-file [`openPdfEditor.exe`](https://github.com/simondong1/openPdfEditor/releases/latest/download/openPdfEditor.exe), double-click it, and open a PDF. Python is not required.

## Build and run from source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python pdf_explorer.py
```

Or double-click `Run PDF Byte Explorer.bat` after installing dependencies.

### Build the Windows executable

```powershell
python -m pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean --onefile --windowed --name openPdfEditor pdf_explorer.py
```

The executable is written to `dist\openPdfEditor.exe`. The tagged-release workflow performs this build automatically and attaches that single executable to the GitHub release. The release asset is the same one-file, no-terminal build linked above.

## Contributing

Issues and pull requests are welcome. Please include:

- Windows version and Python version if running from source.
- The smallest non-sensitive PDF that reproduces the behavior, or a synthetic reproduction.
- Whether the issue concerns parsing, rendering, editing, rebuilding, or the user interface.
- A short before/after description and the relevant page or PDF object, if known.

Please do not upload private financial, medical, legal, or otherwise sensitive PDFs. Redact or create a synthetic file first.

Start with an issue for a design change, then open a focused pull request. Run `python -m py_compile pdf_explorer.py` before submitting.

## Credits

Created and maintained by **Simon Dong** (`simondong1`). Built with [pypdf](https://github.com/py-pdf/pypdf), [PyMuPDF](https://github.com/pymupdf/PyMuPDF), Tkinter, Pillow, and PyInstaller.

If openPdfEditor helps you understand a PDF, please [star the repository](https://github.com/simondong1/openPdfEditor) and share improvements through issues or pull requests.

## License and responsibility

| Item | Details |
| --- | --- |
| License | [MIT](LICENSE) |
| Warranty | Provided as-is, without warranty |
| Responsibility | You are responsible for your files, edits, rights, and distribution |
| Liability | The authors and contributors are not liable for document changes, data loss, corrupted output, security consequences, or misuse |
| File handling | The tool is independent of the PDFs you process and does not upload them |
