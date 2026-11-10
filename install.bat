@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo Installing PyQt-Fluent-Widgets (PyQt6 build)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $tmp=Join-Path $env:TEMP 'finch-fluent'; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Path $tmp | Out-Null; $zip=Join-Path $tmp 'fluent.zip'; Invoke-WebRequest -Uri 'https://codeload.github.com/zhiyiYo/PyQt-Fluent-Widgets/zip/refs/heads/PyQt6' -OutFile $zip -UseBasicParsing; Expand-Archive -Path $zip -DestinationPath $tmp -Force; $dir=Get-ChildItem -Path $tmp -Directory | Select-Object -First 1; & '.venv\Scripts\python.exe' -m pip install --no-deps $dir.FullName"
echo.
echo Install complete. Run "启动 Finch.bat" or ".venv\Scripts\python.exe run.py".
pause
