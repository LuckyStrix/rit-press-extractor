@echo off
rem One command: sets everything up if needed, then opens the window.
rem No administrator rights are needed.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0run.py" %*
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 was not found. Install it for your user only, no administrator needed:
    echo   winget install --id Python.Python.3.11 -e --scope user
    echo or download it from https://www.python.org/downloads/ and choose "Install for me only".
  ) else (
    python "%~dp0run.py" %*
  )
)
pause
