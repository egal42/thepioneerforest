@echo off
setlocal
echo TPF Operations Center Partner Payment Match update
echo Close the Operations Center command window first.
echo This updates code in your existing folder and makes a local backup.
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0install.py" %*
) else (
  python "%~dp0install.py" %*
)
echo.
pause
