@echo off
chcp 65001 >nul 2>&1
title PDF2MD
cd /d "%~dp0"

if not exist "app.py" (
    echo ERROR: app.py not found in this folder.
    echo Make sure all files are in the same folder as PDF2MD.bat
    pause
    exit /b 1
)

set "PY="

py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"

if "%PY%"=="" (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if "%PY%"=="" if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if "%PY%"=="" if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if "%PY%"=="" if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if "%PY%"=="" if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"

if "%PY%"=="" (
    echo.
    echo Python NOT FOUND.
    echo.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo IMPORTANT: check "Add Python to PATH" during installation.
    echo.
    echo Or run DIAGNOSE.bat to see where Python is.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PY%
echo.

rem Install dependencies when they do not actually import. A marker file
rem (.installed_v3) was used before, so a copied folder skipped installation
rem on a clean PC.
%PY% -c "import requests, pypdf, numpy, pymupdf4llm, PIL, socks" >nul 2>&1
if not errorlevel 1 goto run

echo Installing dependencies, please wait...
echo (any VPN/SOCKS proxy is temporarily bypassed so pip can reach PyPI)
echo.

setlocal
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="

%PY% -m pip install --upgrade pip --disable-pip-version-check
%PY% -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto corefail

echo.
echo Installing optional office-format support (Word/Excel/PPTX)...
%PY% -m pip install -r requirements-optional.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo NOTE: office-format support was NOT installed.
    echo   Usually this means Python 3.14 has no onnxruntime build yet.
    echo   The app still works for PDF, images and scans.
    echo   For Word/Excel support, install Python 3.12 or 3.13 and run again.
    echo.
)
endlocal

echo.
echo Installation done.
echo.
goto run

:corefail
endlocal
echo.
echo Failed to install core dependencies.
echo If you use a VPN/proxy that is required for the internet, disable it for
echo the first run, then start again.
pause
exit /b 1

:run
echo Starting PDF2MD...
echo.
%PY% app.py
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo Program exited with error code %RC%
    pause
)
