@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Yellow's Pixel Buddies - Uninstaller / Cleanup
echo ===================================================
echo.
echo This script removes Yellow's Pixel Buddies autostart registry entries,
echo saved pet memories/settings, and installed application files.
echo.
set /p CONFIRM="Are you sure you want to proceed with uninstallation? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Operation cancelled by user.
    pause
    exit /b 0
)

echo.
echo [1/4] Closing any running instances...
taskkill /f /im Yellows-Pixel-Buddies.exe >nul 2>&1

echo [2/4] Removing Windows startup entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "YellowsPixelBuddies" /f >nul 2>&1

echo [3/4] Checking for Inno Setup uninstaller...
set "APP_DIR=%LOCALAPPDATA%\Programs\Yellows Pixel Buddies"
if exist "%APP_DIR%\unins000.exe" (
    echo Launching Windows uninstaller...
    "%APP_DIR%\unins000.exe" /SILENT
    echo Uninstalled from %APP_DIR%
) else if exist "%APP_DIR%" (
    echo Removing installed directory %APP_DIR%...
    rmdir /s /q "%APP_DIR%" >nul 2>&1
)

echo [4/4] Cleaning user pet memories and configs...
set "USER_DATA=%APPDATA%\YellowsPixelBuddies"
if exist "%USER_DATA%" (
    set /p DEL_DATA="Delete saved pet memories and facts from %USER_DATA%? (Y/N): "
    if /i "!DEL_DATA!"=="Y" (
        rmdir /s /q "%USER_DATA%" >nul 2>&1
        echo [OK] Deleted pet memories and configs.
    ) else (
        echo [INFO] Kept pet memories in %USER_DATA%.
    )
)

:: Clean up updater temp folder if present
if exist "%TEMP%\yellows_update" (
    rmdir /s /q "%TEMP%\yellows_update" >nul 2>&1
)

echo.
echo ===================================================
echo   Uninstallation and cleanup completed!
echo ===================================================
pause
