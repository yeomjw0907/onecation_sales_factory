@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=%cd%\src;%PYTHONPATH%
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python
"%PYTHON_EXE%" -c "import streamlit" 2>nul || (
    echo streamlit not found. Installing...
    "%PYTHON_EXE%" -m pip install streamlit
)
"%PYTHON_EXE%" -m streamlit run web_dashboard.py
pause
