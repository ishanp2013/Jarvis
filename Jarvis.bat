@echo off
rem Starts Jarvis without a console window. Add --debug after pythonw.exe's arguments for dev tools.
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\JarvisAssistant\venv\Scripts\pythonw.exe" -W ignore -m jarvis %*
