@echo off
setlocal
set LOGFILE=D:\2026 Projects\nse-stock-scraper\reports\task-runner.log
echo [%date% %time%] Task started >> "%LOGFILE%"

cd /d "D:\2026 Projects\nse-stock-scraper"
if errorlevel 1 (
    echo [%date% %time%] ERROR: Failed to change directory >> "%LOGFILE%"
    exit /b 1
)

"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -ExecutionPolicy Bypass -File "D:\2026 Projects\nse-stock-scraper\scripts\daily_stock_job.ps1" >> "%LOGFILE%" 2>&1
set EXITCODE=%ERRORLEVEL%

echo [%date% %time%] Task completed with exit code %EXITCODE% >> "%LOGFILE%"
exit /b %EXITCODE%
