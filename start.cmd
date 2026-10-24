@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create .venv and install the wheel or source package first. See README.md.
  exit /b 1
)
".venv\Scripts\python.exe" -m jira_analytics --config config.toml %*
exit /b %errorlevel%
