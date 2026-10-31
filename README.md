# openPdfEditor

[![CI](https://github.com/simondong1/openPdfEditor/actions/workflows/ci.yml/badge.svg)](https://github.com/simondong1/openPdfEditor/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/simondong1/openPdfEditor?display_name=tag)](https://github.com/simondong1/openPdfEditor/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Offline PDF editor for Windows: edit text, fonts, and positions

openPdfEditor is a free, open-source PDF editor for Windows. Find text across pages, change its content, font, size, or position, and preview each edit before saving. Unlike general PDF editors, it also shows the underlying page data beside the rendered page. Everything runs locally: your PDF is not uploaded and your original file stays untouched.

### How it compares with other PDF editing options

| What you need to do | Typical choice | How openPdfEditor differs |
| --- | --- | --- |
| Your goal | Common choice | openPdfEditor difference |
| --- | --- | --- |
| Design pages, forms, and signatures | Acrobat, PDF-XChange, Foxit, or another desktop PDF editor | Focuses on finding and precisely changing existing PDF text, fonts, and positions |
| Make a quick edit in a browser | An online PDF editor | Edits locally on your computer; no upload, account, or cloud copy |
| Automate changes across many PDFs | A PDF programming library | Offers a visual workflow with document search, live preview, and undo |
| Inspect raw file bytes | A general hex editor | Connects PDF data and font information to readable page content and a live preview |
| Edit an exact value and check its placement | **openPdfEditor** | Search all pages, edit the selected item, preview the page, and save a separate PDF |

**Choose a desktop editor for page design, an online editor for quick browser edits, and openPdfEditor to edit PDF text, font, and position locally while seeing how the saved file is built.**

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
| Does this make a stealth or undetectable edit? | **No.** It does not hide changes | No tool can guarantee that | No tool can guarantee that |
| Does saving replace your original? | **No.** It creates a new file | Depends on the save option | Usually creates a new file |
| Is the original password protection retained? | **Yes**, for supported PDFs | Depends on the product | Depends on the product |

For supported PDFs, openPdfEditor writes one rebuilt PDF rather than appending a new revision to the end of the original. This removes the old appended revision from the saved copy; it does not conceal the edit. The changed content and metadata can still be inspected or compared with an original. A small text edit may also change the final file size because the document is reconstructed when saved.

## What you can do

| Workflow | What you get |
| --- | --- |
| Find PDF text | Search every page and jump to the matching text and its location |
| Edit PDF text | Change the selected text, including supported encoded characters |
| Change text position | Adjust placement and see the result in the page preview |
| Change or inspect fonts | Review the selected font, size, character widths, and displayed characters |
| Inspect PDF page content | See the page, its text, fonts, and drawing details together |
| Stay in control | Keep edits across pages, undo with `Ctrl+Z`, and review before saving |
| Clean unused resources | Confirm removal of unused fonts and empty path-drawing commands; undo before saving |

## See it in action

Open a PDF to reveal the editor. The welcome screen stays simple until a document is open.

![Offline Windows PDF editor welcome screen before a PDF is opened](docs/images/welcome.png)

Search across pages and select a result to jump to its page and preview location.

![PDF editor with cross-page search, selected text position, and live page preview](docs/images/operation-map.png)

Inspect and edit the selected text, font, size, and position beside the page preview.

![PDF text editor showing selected text, font, size, position, and editable page data](docs/images/decoded-bytes.png)

Review the fonts used on the page, including character widths and displayed characters.

![PDF font inspector showing page fonts, character widths, and character mappings](docs/images/font-resources.png)

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

## PDF editor questions

**Is there an offline PDF editor for Windows?** Yes. openPdfEditor runs locally on Windows and includes a page preview, cross-page search, text editing, font controls, and position editing. It does not upload PDFs.

**How can I edit text or move text in a PDF?** Open the file, search for the text, select it, change its text, font, size, or position, review the page preview, and save a new PDF.

**How is openPdfEditor different from Acrobat, PDF-XChange, or Foxit?** Those products focus on broad document editing and production. openPdfEditor focuses on precise text and position edits while showing the page's underlying content and live preview together.

**Does openPdfEditor make stealth or undetectable PDF edits?** No. It does not conceal changes. It rebuilds supported PDFs instead of appending an old revision, but the current content can still be inspected or compared with an original file.

**Does openPdfEditor upload or store my PDF online?** No. The app reads the PDF locally; it does not send it to an online editor or cloud service.

**Can I change PDF font size and text position?** Yes, for supported PDFs. Select the text and adjust its font, size, or position while checking the live page preview.

**How do I download the Windows PDF editor?** Download the single-file [`openPdfEditor.exe`](https://github.com/simondong1/openPdfEditor/releases/latest/download/openPdfEditor.exe) and double-click it. Python and a separate installer are not required.

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
