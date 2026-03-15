@echo off
chcp 65001 >nul
echo ============================================
echo Learning Agent Bot - Auto-Restart
echo ============================================
echo.
echo Press Ctrl+C to stop completely
echo.

if exist "%~dp0\..\venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call "%~dp0\..\venv\Scripts\activate.bat"
)
echo.
echo.

:loop
echo [%date% %time%] Starting bot...
cd /d "%~dp0\.."
python bot.py
set EXITCODE=%ERRORLEVEL%

echo.
echo [%date% %time%] Bot exited with code %EXITCODE%

if %EXITCODE% == 42 (
    echo Restart requested...
    echo.
    timeout /t 2 /nobreak >nul
    goto loop
)

if %EXITCODE% == 0 (
    echo Normal shutdown.
) else (
    echo Crashed or stopped unexpectedly.
)

echo.
pause
