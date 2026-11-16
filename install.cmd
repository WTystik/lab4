@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer from python.org with the Python launcher.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
if exist "pyproject.toml" (
  ".venv\Scripts\python.exe" -m pip install .
) else (
  ".venv\Scripts\python.exe" -m pip install --upgrade jira_lab4_analytics-1.2.0-py3-none-any.whl
)
if errorlevel 1 goto failed
echo Installation complete. Run: start.cmd --project KAFKA --open
exit /b 0
:failed
echo Installation failed. Check the message above.
pause
exit /b 1
