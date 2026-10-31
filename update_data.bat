@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
python run_pipelines.py
if errorlevel 1 (
    echo.
    echo One or more sources FAILED. Read the messages above before refreshing Power BI.
    pause
    exit /b 1
)
echo.
echo Done. Now click Refresh in Power BI.
pause
