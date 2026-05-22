@echo off
cd /d "%~dp0"
python main.py
if %errorlevel% neq 0 (
    echo.
    echo Error al iniciar. Verifica que las dependencias esten instaladas.
    echo Ejecuta: instalar.bat
    pause
)
