@echo off
setlocal
rem One-time setup. The Python environment lives in a short path because Windows can't load
rem some DLLs from very long folder paths.
set "HOME=%LOCALAPPDATA%\JarvisAssistant"
set "VENV=%HOME%\venv"
if not exist "%HOME%" mkdir "%HOME%"

py -3.11 --version >nul 2>&1 || (echo Python 3.11 is required: install it from python.org or the Microsoft Store. & pause & exit /b 1)
if not exist "%VENV%\Scripts\python.exe" py -3.11 -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt" || (pause & exit /b 1)
rem scikit-learn comes in with openWakeWord but is only used for training, and Smart App Control blocks it.
"%VENV%\Scripts\python.exe" -m pip uninstall -y scikit-learn >nul 2>&1

echo Downloading wake-word and speech models (about 160 MB, one time)...
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
pushd "%~dp0"
"%VENV%\Scripts\python.exe" -W ignore -c "from jarvis import speech; speech.WakeWord(); speech.STT().warm(); print('Models ready.')"
popd

set /p SC="Create a desktop shortcut? (y/n) "
if /i "%SC%"=="y" powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Jarvis.lnk'); $s.TargetPath='%~dp0Jarvis.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo Setup complete. Start Jarvis with Jarvis.bat
pause
