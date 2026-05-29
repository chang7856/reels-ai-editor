@echo off
REM Fetch static ffmpeg + ffprobe for Windows x64 and stage them under .\bin\
REM so PyInstaller can bundle them into ReelsAIEditor.exe.
REM
REM Source: https://www.gyan.dev/ffmpeg/builds/ — community-maintained
REM static builds. We grab the "essentials" release zip (smallest with
REM ffmpeg.exe + ffprobe.exe, ~80 MB).

setlocal
pushd %~dp0\..

if not exist bin mkdir bin

if exist bin\ffmpeg.exe (
  if exist bin\ffprobe.exe (
    echo Binaries already present in bin\, skipping download.
    popd
    endlocal
    exit /b 0
  )
)

echo Downloading ffmpeg essentials build...
set URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
set ZIP=%TEMP%\ffmpeg-windows.zip
set OUT=%TEMP%\ffmpeg-extract

if exist "%ZIP%" del "%ZIP%"
if exist "%OUT%" rmdir /s /q "%OUT%"

powershell -Command "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing"
if errorlevel 1 (
  echo Download failed
  popd
  exit /b 1
)

echo Extracting...
powershell -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%OUT%' -Force"

echo Staging into bin\...
for /r "%OUT%" %%F in (ffmpeg.exe) do copy "%%F" bin\ffmpeg.exe >nul
for /r "%OUT%" %%F in (ffprobe.exe) do copy "%%F" bin\ffprobe.exe >nul

if not exist bin\ffmpeg.exe (
  echo ERROR: ffmpeg.exe not found after extract
  popd
  exit /b 1
)
if not exist bin\ffprobe.exe (
  echo ERROR: ffprobe.exe not found after extract
  popd
  exit /b 1
)

del "%ZIP%"
rmdir /s /q "%OUT%"

echo OK:
dir bin
popd
endlocal
