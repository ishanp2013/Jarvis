@echo off
rem Opens Jarvis in its own window (no browser). Starts Jarvis's background core first if it isn't running.
rem Add --debug for dev tools.
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\JarvisAssistant\venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%LOCALAPPDATA%\Packages\AnthropicPBC.Claude_fnn82j28hfe8t\LocalCache\Local\JarvisAssistant\venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo Jarvis isn't installed yet. Run setup.bat first.
  pause
  exit /b 1
)
start "" "%PYW%" -W ignore -m jarvis %*
