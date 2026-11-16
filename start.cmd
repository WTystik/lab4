@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run install.cmd to install the application.
  exit /b 1
)
if "%~1"=="" goto default
".venv\Scripts\python.exe" -m jira_analytics --config config.toml %*
exit /b %errorlevel%
:default
".venv\Scripts\python.exe" -m jira_analytics --config config.toml --open
exit /b %errorlevel%
