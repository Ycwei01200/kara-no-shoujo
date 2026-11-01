@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem find a windowless Python: PATH, then the py launcher, then the default install folder
set "PYW="
for %%P in (pythonw.exe) do if not "%%~$PATH:P"=="" set "PYW=%%~$PATH:P"
if not defined PYW for %%P in (pyw.exe) do if not "%%~$PATH:P"=="" set "PYW=%%~$PATH:P"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not defined PYW if exist "%WINDIR%\pyw.exe" set "PYW=%WINDIR%\pyw.exe"
if not defined PYW (
  echo 找不到 Python（pythonw.exe）。請先安裝 Python 3.12。
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0guide\pet.py"
