@echo off
REM Build the Windows .exe + folder (run on Windows 10/11 with Python 3.10+).
REM Output: dist\ReelsAIEditor\  →  zip it as ReelsAIEditor-Windows-x64.zip

setlocal
pushd %~dp0\..

echo Staging bundled ffmpeg + ffprobe...
call scripts\fetch_ffmpeg_windows.bat
if errorlevel 1 (
  echo Failed to fetch ffmpeg
  popd
  exit /b 1
)

echo Installing build dependencies...
python -m pip install --upgrade pyinstaller
python -m pip install -r requirements.txt

echo Building...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller reels.spec --clean --noconfirm

if not exist dist\ReelsAIEditor (
  echo Build failed — folder not produced
  popd
  exit /b 1
)

echo Packaging zip...
powershell -Command "Compress-Archive -Path dist\ReelsAIEditor\* -DestinationPath dist\ReelsAIEditor-Windows-x64.zip -Force"

echo Done. See dist\ReelsAIEditor-Windows-x64.zip
popd
endlocal
