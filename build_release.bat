@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Building Yellow's Pixel Buddies Executable
echo ===================================================
echo.

python -m PyInstaller --clean Yellows-Pixel-Buddies.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [SUCCESS] Executable built successfully in dist\Yellows-Pixel-Buddies.exe!
echo.

:: Check for Inno Setup compiler to build the installer if available
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\iscc.exe" (
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\iscc.exe"
) else if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\iscc.exe"
) else if exist "C:\Program Files\Inno Setup 6\iscc.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\iscc.exe"
) else (
    where iscc >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "ISCC=iscc"
    )
)

if defined ISCC (
    echo Compiling Windows Installer with Inno Setup...
    "%ISCC%" installer.iss
    if !ERRORLEVEL! EQU 0 (
        echo [SUCCESS] Installer generated at dist\Yellows-Pixel-Buddies-Setup.exe!
    ) else (
        echo [WARNING] Inno Setup compilation encountered an issue.
    )
) else (
    echo [INFO] Inno Setup compiler iscc.exe was not found.
    echo To create the setup installer, install Inno Setup 6 from https://jrsoftware.org/isdl.php
    echo and compile installer.iss.
)

echo.
echo All done!
