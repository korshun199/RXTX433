@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ESP Programmer - Windows Build

cd /d "%~dp0"

echo.
echo ==========================================
echo   ESP Programmer - Windows build script
echo ==========================================
echo.

set "PY=%CD%\venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] Virtual environment not found:
    echo         %PY%
    echo.
    echo Create it first with Python 3.13:
    echo   py -3.13 -m venv venv
    echo   venv\Scripts\python.exe -m pip install PySide6 pyserial esptool pyinstaller
    echo.
    pause
    exit /b 1
)

if not exist "%CD%\esp_programmer.py" (
    echo [ERROR] esp_programmer.py not found in:
    echo         %CD%
    echo.
    pause
    exit /b 1
)

echo [1/6] Checking dependencies...
"%PY%" -c "import PySide6, serial, esptool, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Installing...
    "%PY%" -m pip install --upgrade pip setuptools wheel
    if errorlevel 1 goto :fail

    "%PY%" -m pip install PySide6 pyserial esptool pyinstaller
    if errorlevel 1 goto :fail
)

echo [2/6] Creating esptool launcher...
> "%CD%\esptool_launcher.py" (
    echo import runpy
    echo.
    echo if __name__ == "__main__":
    echo     runpy.run_module^("esptool", run_name="__main__"^)
)

echo [3/6] Cleaning old build...
if exist "%CD%\build" rmdir /s /q "%CD%\build"
if exist "%CD%\dist" rmdir /s /q "%CD%\dist"
if exist "%CD%\ESP_Programmer.spec" del /q "%CD%\ESP_Programmer.spec"
if exist "%CD%\esptool.spec" del /q "%CD%\esptool.spec"

echo [4/6] Building ESP_Programmer.exe...
"%PY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --windowed ^
  --name ESP_Programmer ^
  --collect-all PySide6 ^
  --hidden-import serial.tools.list_ports ^
  "%CD%\esp_programmer.py"

if errorlevel 1 goto :fail

echo [5/6] Building esptool.exe...
"%PY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name esptool ^
  --collect-all esptool ^
  --distpath "%CD%\dist\ESP_Programmer" ^
  "%CD%\esptool_launcher.py"

if errorlevel 1 goto :fail

echo [6/6] Verifying output...
if not exist "%CD%\dist\ESP_Programmer\ESP_Programmer.exe" (
    echo [ERROR] ESP_Programmer.exe was not created.
    goto :fail
)

if not exist "%CD%\dist\ESP_Programmer\esptool.exe" (
    echo [ERROR] esptool.exe was not created.
    goto :fail
)

echo.
echo ==========================================
echo BUILD COMPLETED SUCCESSFULLY
echo ==========================================
echo.
echo Output:
echo   %CD%\dist\ESP_Programmer\ESP_Programmer.exe
echo.
echo Copy the whole folder:
echo   %CD%\dist\ESP_Programmer
echo.

start "" "%CD%\dist\ESP_Programmer\ESP_Programmer.exe"

pause
exit /b 0

:fail
echo.
echo ==========================================
echo BUILD FAILED
echo ==========================================
echo Check the messages above. Windows has once again found a way
echo to turn a simple build into an administrative ceremony.
echo.
pause
exit /b 1
