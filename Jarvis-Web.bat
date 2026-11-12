@echo off
rem Starts Jarvis with its dashboard in your browser at http://127.0.0.1:8765 instead of its own window.
rem Close this console window (or press Ctrl+C) to stop Jarvis. Only one Jarvis can run at a time.
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
"%LOCALAPPDATA%\JarvisAssistant\venv\Scripts\python.exe" -W ignore -m jarvis --web %*
