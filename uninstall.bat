@echo off
setlocal

REM ---------------------------------------------------------------------
REM  S.TFU uninstaller
REM
REM  Deliberately a plain batch file rather than a compiled uninstaller:
REM  you can read every line of it before running it, which is the least
REM  an app that took over your screen owes you.
REM ---------------------------------------------------------------------

set "DATA=%LOCALAPPDATA%\STFU"

echo.
echo   S.TFU uninstaller
echo   =================
echo.
echo   This will remove:
echo     - the start-with-Windows entry
echo         HKCU\Software\Microsoft\Windows\CurrentVersion\Run\STFU
echo     - your settings and PIN, sound clips and pictures, and the log
echo         %DATA%
echo.
echo   Your log of past triggers is copied to the Desktop first.
echo.
echo   It does NOT delete stfu.exe. Delete that yourself afterwards.
echo.

choice /C YN /N /M "  Go ahead? [Y/N] "
if errorlevel 2 goto :cancelled

echo.
echo   Stopping S.TFU if it is running...
taskkill /IM stfu.exe /F >nul 2>&1
if errorlevel 1 (echo     not running) else (echo     stopped)

REM Keep the record. It is the only thing here that cannot be recreated,
REM and a stray file on the Desktop is easier to undo than a deleted log.
if exist "%DATA%\events.jsonl" (
    copy /Y "%DATA%\events.jsonl" "%USERPROFILE%\Desktop\stfu-events-backup.jsonl" >nul 2>&1
    if errorlevel 1 (
        echo     could not back up the event log
    ) else (
        echo     event log copied to Desktop\stfu-events-backup.jsonl
    )
)

echo   Removing the start-with-Windows entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v STFU /f >nul 2>&1
if errorlevel 1 (echo     was not registered) else (echo     removed)

echo   Removing %DATA% ...
if exist "%DATA%" (
    rmdir /S /Q "%DATA%" >nul 2>&1
    if exist "%DATA%" (
        echo     FAILED - something still has a file open there.
        echo     Close S.TFU and any open folder windows, then run this again.
    ) else (
        echo     removed
    )
) else (
    echo     nothing to remove
)

echo.
echo   Done. S.TFU is no longer installed.
echo   You can now delete stfu.exe.
echo.
pause
exit /b 0

:cancelled
echo.
echo   Cancelled. Nothing was changed.
echo.
pause
exit /b 1
