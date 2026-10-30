@echo off
cd /d "%~dp0"
python pdf_explorer.py
if errorlevel 1 pause
