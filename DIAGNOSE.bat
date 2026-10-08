@echo off
chcp 65001 >nul 2>&1
title PDF2MD Diagnose
echo.
echo === PDF2MD - Diagnose ===
echo.
echo Current folder: %CD%
echo.

echo --- Files ---
if exist "PDF2MD.bat" (echo   OK  PDF2MD.bat) else (echo   --  PDF2MD.bat MISSING)
if exist "app.py" (echo   OK  app.py) else (echo   --  app.py MISSING)
if exist "requirements.txt" (echo   OK  requirements.txt) else (echo   --  requirements.txt MISSING)
echo.

echo --- Python search ---
echo.

echo [1] py launcher:
py -3 --version 2>nul
if errorlevel 1 (echo     NOT FOUND) else (echo     WORKS)
echo.

echo [2] python in PATH:
python --version 2>nul
if errorlevel 1 (echo     NOT FOUND) else (echo     WORKS)
echo.

echo [3] Typical install paths:
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" echo     FOUND: %LOCALAPPDATA%\Programs\Python\Python313\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" echo     FOUND: %LOCALAPPDATA%\Programs\Python\Python312\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" echo     FOUND: %LOCALAPPDATA%\Programs\Python\Python311\python.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" echo     FOUND: %LOCALAPPDATA%\Programs\Python\Python310\python.exe
if exist "C:\Python313\python.exe" echo     FOUND: C:\Python313\python.exe
if exist "C:\Python312\python.exe" echo     FOUND: C:\Python312\python.exe
if exist "C:\Python311\python.exe" echo     FOUND: C:\Python311\python.exe
if exist "C:\Python310\python.exe" echo     FOUND: C:\Python310\python.exe
echo.
echo === End ===
echo.
pause
