@echo off
echo ============================================
echo   FarmaciaPOS - Instalacion de dependencias
echo ============================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python no esta instalado.
    echo Descarga Python 3.11+ desde: https://python.org
    pause
    exit /b 1
)

echo Instalando dependencias...
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo ERROR al instalar dependencias.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Instalacion exitosa!
echo   Ejecuta: python main.py
echo ============================================
pause
