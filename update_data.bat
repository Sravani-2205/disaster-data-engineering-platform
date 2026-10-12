@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
python run_pipelines.py
echo.
echo Done. Now click Refresh in Power BI.
pause