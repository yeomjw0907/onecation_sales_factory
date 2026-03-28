@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [%date% %time%] Sales Factory 자동 실행 시작 >> "%~dp0logs\scheduler.log" 2>&1
".venv\Scripts\python.exe" -c "from sales_factory.main import run; run()" >> "%~dp0logs\scheduler.log" 2>&1
echo [%date% %time%] 완료 >> "%~dp0logs\scheduler.log" 2>&1
