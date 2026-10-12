@echo off
cd /d "C:\Disaster Data Engineering & Intelligence Platform"
call .venv\Scripts\activate
python run_pipelines.py
echo.
echo Done. Now click Refresh in Power BI.
pause