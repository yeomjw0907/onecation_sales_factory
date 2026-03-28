@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%cd%\src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python
"%PYTHON_EXE%" -c "from sales_factory.main import run; run()"
pause
