<#
.SYNOPSIS
    Registers the Windows scheduled task for the daily stock scraper at 9 AM.
.DESCRIPTION
    Creates or replaces the task "NSE-Daily-Scrapers-9AM" to run daily at 09:00.
    Run this script as Administrator for best results.
#>
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$batchFile = Join-Path $scriptDir "run_daily_job.bat"
$taskName = "NSE-Daily-Scrapers-9AM"
$scheduleTime = "09:00"  # 9 AM (24-hour format)

if (-not (Test-Path -LiteralPath $batchFile)) {
    throw "Batch file not found: $batchFile"
}

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed existing task: $taskName"
}

$action = New-ScheduledTaskAction -Execute $batchFile -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $scheduleTime
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Daily stock scraper run at 9 AM"

Write-Host "Scheduled task registered: $taskName (daily at $scheduleTime)"
Write-Host "Verify with: schtasks /Query /TN `"$taskName`" /V /FO LIST"
