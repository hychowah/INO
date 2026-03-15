@echo off
if exist "%~dp0\..\venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call "%~dp0\..\venv\Scripts\activate.bat"
)
echo.
echo Starting Learning Agent API server...
echo.
echo Endpoints:
echo   POST /api/chat    - Send message to agent
echo   GET  /api/topics  - Topic tree
echo   GET  /api/due     - Due reviews
echo   GET  /api/stats   - Review stats
echo   GET  /api/health  - Health check
echo.
echo Press Ctrl+C to stop.
echo.
cd /d "%~dp0\.."
uvicorn api:app --host 0.0.0.0 --port 8080 --reload
