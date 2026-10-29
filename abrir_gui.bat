@echo off
cd /d "%~dp0"
py -3 gui.py
if errorlevel 1 (
    echo.
    echo Nao foi possivel iniciar a GUI. Consulte docs\GUI.md.
    pause
)
