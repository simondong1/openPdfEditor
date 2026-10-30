# Contributing to openPdfEditor

Thank you for improving openPdfEditor. Start with an issue for a new behavior or design change, then open a focused pull request.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python pdf_explorer.py
```

Before opening a pull request:

```powershell
python -m py_compile pdf_explorer.py
```

Please use synthetic or fully redacted PDFs. Do not upload private financial, medical, legal, or otherwise sensitive documents.

For parser or writer changes, include a small regression case and explain whether the source bytes, decoded stream, encryption state, metadata, and rendered output were checked.
