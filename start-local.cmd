@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 tools\start_local_stack.py --open-browser
if errorlevel 1 pause
