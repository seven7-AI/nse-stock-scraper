param(
    [switch]$NoGitPush,
    [switch]$BootstrapDeps
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-DirectoryIfMissing {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Resolve-PythonExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )
    $candidates = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "env\Scripts\python.exe"),
        (Join-Path $RepoRoot "venv\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FromPath,
        [Parameter(Mandatory = $true)]
        [string]$ToPath
    )

    $fromFull = [System.IO.Path]::GetFullPath($FromPath).TrimEnd('\')
    $toFull = [System.IO.Path]::GetFullPath($ToPath)
    if ($toFull.StartsWith($fromFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $toFull.Substring($fromFull.Length).TrimStart('\').Replace('\', '/')
    }

    return $toFull.Replace('\', '/')
}

function Invoke-NativeCaptured {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $argStrings = @()
    foreach ($arg in $Arguments) {
        if ($arg -match '\s|"') {
            $argStrings += "`"$($arg -replace '"', '`"')`""
        }
        else {
            $argStrings += $arg
        }
    }
    $argString = $argStrings -join " "

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $argString
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    $stdOutBuilder = New-Object System.Text.StringBuilder
    $stdErrBuilder = New-Object System.Text.StringBuilder

    $outHandler = {
        if ($EventArgs.Data) {
            [void]$Event.MessageData.AppendLine($EventArgs.Data)
        }
    }
    $errHandler = {
        if ($EventArgs.Data) {
            [void]$Event.MessageData.AppendLine($EventArgs.Data)
        }
    }

    $outEvent = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action $outHandler -MessageData $stdOutBuilder
    $errEvent = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action $errHandler -MessageData $stdErrBuilder

    [void]$proc.Start()
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()
    $proc.WaitForExit()

    Start-Sleep -Milliseconds 200

    Unregister-Event -SourceIdentifier $outEvent.Name -ErrorAction SilentlyContinue
    Unregister-Event -SourceIdentifier $errEvent.Name -ErrorAction SilentlyContinue

    $outputLines = @()
    $stdOut = $stdOutBuilder.ToString()
    $stdErr = $stdErrBuilder.ToString()
    if ($stdOut) {
        $outputLines += ($stdOut -split "(`r`n|`n|`r)")
    }
    if ($stdErr) {
        $outputLines += ($stdErr -split "(`r`n|`n|`r)")
    }
    $outputLines = $outputLines | Where-Object { $_ -ne "" }

    return [PSCustomObject]@{
        ExitCode = $proc.ExitCode
        Output   = @($outputLines)
    }
}

function Test-ScrapyInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )
    $probe = Invoke-NativeCaptured -FilePath $PythonPath -Arguments @("-c", "import scrapy")
    return ($probe.ExitCode -eq 0)
}

function Invoke-SpiderRun {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,
        [Parameter(Mandatory = $true)]
        [string]$SpiderName,
        [Parameter(Mandatory = $true)]
        [string]$RunLogPath,
        [switch]$DisableHttpCache
    )

    $spiderStart = Get-Date
    $cmdArgs = @(
        "-m", "scrapy", "crawl", $SpiderName,
        "-s", "LOG_LEVEL=INFO"
    )
    if ($DisableHttpCache) {
        $cmdArgs += @("-s", "HTTPCACHE_ENABLED=False")
    }

    Add-Content -LiteralPath $RunLogPath -Value ("[{0}] START {1}" -f $spiderStart.ToString("s"), $SpiderName)
    $result = Invoke-NativeCaptured -FilePath $PythonPath -Arguments $cmdArgs
    foreach ($line in $result.Output) {
        Add-Content -LiteralPath $RunLogPath -Value ("[{0}] {1}" -f $SpiderName, $line)
    }

    $spiderEnd = Get-Date
    $duration = [Math]::Round(($spiderEnd - $spiderStart).TotalSeconds, 2)
    Add-Content -LiteralPath $RunLogPath -Value ("[{0}] END {1} exit={2} durationSec={3}" -f $spiderEnd.ToString("s"), $SpiderName, $result.ExitCode, $duration)

    return [PSCustomObject]@{
        SpiderName = $SpiderName
        ExitCode   = $result.ExitCode
        Duration   = $duration
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$reportsDir = Join-Path $repoRoot "reports"
New-DirectoryIfMissing -Path $reportsDir

$dateStamp = Get-Date -Format "yyyy-MM-dd"
$runStamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$runLogPath = Join-Path $reportsDir ("run-{0}.log" -f $runStamp)
$taskRunnerLogPath = Join-Path $reportsDir "task-runner.log"
$runStartedAt = Get-Date

Push-Location $repoRoot
try {
    Add-Content -LiteralPath $runLogPath -Value ("[{0}] RUN_START" -f $runStartedAt.ToString("s"))

    $pythonPath = Resolve-PythonExecutable -RepoRoot $repoRoot
    if (-not $pythonPath) {
        throw "No virtual environment Python found. Expected one of: .venv\Scripts\python.exe, env\Scripts\python.exe, venv\Scripts\python.exe"
    }
    Add-Content -LiteralPath $runLogPath -Value ("[{0}] python={1}" -f (Get-Date).ToString("s"), $pythonPath)

    if (-not (Test-ScrapyInstalled -PythonPath $pythonPath)) {
        if ($BootstrapDeps) {
            $requirementsPath = Join-Path $repoRoot "requirements.txt"
            Add-Content -LiteralPath $runLogPath -Value ("[{0}] installing requirements from {1}" -f (Get-Date).ToString("s"), $requirementsPath)
            $pipInstall = Invoke-NativeCaptured -FilePath $pythonPath -Arguments @("-m", "pip", "install", "-r", $requirementsPath)
            foreach ($line in $pipInstall.Output) {
                Add-Content -LiteralPath $runLogPath -Value ("[pip] {0}" -f $line)
            }
            if ($pipInstall.ExitCode -ne 0 -or -not (Test-ScrapyInstalled -PythonPath $pythonPath)) {
                throw "Dependency bootstrap failed. Could not install Scrapy in environment: $pythonPath"
            }
        }
        else {
            throw "Scrapy is not installed in environment '$pythonPath'. Run once with -BootstrapDeps or install manually: `"$pythonPath`" -m pip install -r requirements.txt"
        }
    }

    $afxRun = Invoke-SpiderRun -PythonPath $pythonPath -SpiderName "afx_scraper" -RunLogPath $runLogPath
    $stockRun = Invoke-SpiderRun -PythonPath $pythonPath -SpiderName "stockanalysis_scraper" -RunLogPath $runLogPath -DisableHttpCache

    $runEndedAt = Get-Date
    $duration = [Math]::Round(($runEndedAt - $runStartedAt).TotalSeconds, 2)
    $overallSuccess = ($afxRun.ExitCode -eq 0 -and $stockRun.ExitCode -eq 0)

    Add-Content -LiteralPath $runLogPath -Value ("[{0}] SUMMARY afx_exit={1} stockanalysis_exit={2} durationSec={3}" -f $runEndedAt.ToString("s"), $afxRun.ExitCode, $stockRun.ExitCode, $duration)
    if ($overallSuccess) {
        Add-Content -LiteralPath $runLogPath -Value ("[{0}] RUN_STATUS SUCCESS" -f $runEndedAt.ToString("s"))
    }
    else {
        Add-Content -LiteralPath $runLogPath -Value ("[{0}] RUN_STATUS FAILED reason=one_or_more_spiders_failed" -f $runEndedAt.ToString("s"))
        throw "One or more spiders failed. Check run log: $runLogPath"
    }

    $tracked = @($runLogPath, $taskRunnerLogPath) | Where-Object { Test-Path -LiteralPath $_ }
    $tracked = $tracked | ForEach-Object { Get-RelativePath -FromPath $repoRoot -ToPath $_ } | Where-Object { $_ -and $_ -ne "." }
    if (@($tracked).Count -gt 0) {
        & git add -- $tracked
        & git diff --cached --quiet
        $hasChanges = ($LASTEXITCODE -ne 0)
        if ($hasChanges) {
            $commitMessage = "chore(log): daily scraper run $dateStamp"
            & git commit -m $commitMessage | Out-Null
            if (-not $NoGitPush) {
                $branch = (& git branch --show-current).Trim()
                if (-not $branch) {
                    $branch = "main"
                }
                & git push origin $branch | Out-Null
            }
        }
    }
}
catch {
    $failedAt = Get-Date
    Add-Content -LiteralPath $runLogPath -Value ("[{0}] RUN_STATUS FAILED reason={1}" -f $failedAt.ToString("s"), $_.Exception.Message)
    throw
}
finally {
    Pop-Location
}
