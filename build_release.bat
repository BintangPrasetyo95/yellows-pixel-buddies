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

:: Publish SHA-256 checksums. Pink only auto-installs an update whose hash matches this file, so
:: SHA256SUMS.txt MUST be uploaded with every GitHub release next to the .exe files.
echo.
echo Writing dist\SHA256SUMS.txt ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath 'dist' -Filter '*.exe' | ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name } | Set-Content -LiteralPath 'dist\SHA256SUMS.txt' -Encoding ascii"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Could not write dist\SHA256SUMS.txt - do NOT publish this release without it.
    exit /b 1
)
type dist\SHA256SUMS.txt
echo [SUCCESS] Upload dist\SHA256SUMS.txt with the release, or auto-update will refuse it.

echo.
echo All done!
