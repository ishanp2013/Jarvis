@echo off
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
"%LOCALAPPDATA%\JarvisAssistant\venv\Scripts\python.exe" -W ignore -m unittest tests.test_core -v
pause
