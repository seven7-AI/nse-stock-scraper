param(
    [switch]$NoNotepad,
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

function Get-JsonlRows {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $rows = @()
    if (-not (Test-Path -LiteralPath $Path)) {
        return $rows
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line.Trim().Length -eq 0) {
            continue
        }
        try {
            $rows += ($line | ConvertFrom-Json)
        }
        catch {
            # Skip malformed rows but continue report generation.
        }
    }
    return $rows
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FromPath,
        [Parameter(Mandatory = $true)]
        [string]$ToPath
    )
    $fromFull = [System.IO.Path]::GetFullPath($FromPath)
    $toFull = [System.IO.Path]::GetFullPath($ToPath)
    
    if ($toFull.StartsWith($fromFull)) {
        $relative = $toFull.Substring($fromFull.Length).TrimStart('\', '/')
        if ([string]::IsNullOrEmpty($relative)) {
            return "."
        }
        return $relative.Replace('\', '/')
    }
    
    $fromParts = $fromFull.Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.StringSplitOptions]::RemoveEmptyEntries)
    $toParts = $toFull.Split([System.IO.Path]::DirectorySeparatorChar, [System.IO.StringSplitOptions]::RemoveEmptyEntries)
    
    $commonLength = 0
    $minLength = [Math]::Min($fromParts.Length, $toParts.Length)
    for ($i = 0; $i -lt $minLength; $i++) {
        if ($fromParts[$i] -eq $toParts[$i]) {
            $commonLength++
        }
        else {
            break
        }
    }
    
    $upLevels = $fromParts.Length - $commonLength
    $downParts = $toParts[$commonLength..($toParts.Length - 1)]
    $downPath = $downParts -join '/'
    
    if ($upLevels -eq 0) {
        if ([string]::IsNullOrEmpty($downPath)) {
            return "."
        }
        return $downPath
    }
    
    $upPath = (@("..") * $upLevels) -join '/'
    if ([string]::IsNullOrEmpty($downPath)) {
        return $upPath
    }
    return "$upPath/$downPath"
}

function Invoke-SpiderRun {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,
        [Parameter(Mandatory = $true)]
        [string]$SpiderName,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath,
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $spiderStart = Get-Date
    $cmdArgs = @(
        "-m", "scrapy", "crawl", $SpiderName,
        "-o", $OutputPath,
        "-s", "LOG_LEVEL=INFO",
        "-s", "HTTPCACHE_ENABLED=False"
    )

    Add-Content -LiteralPath $LogPath -Value ("[{0}] Starting spider: {1}" -f $spiderStart.ToString("s"), $SpiderName)
    $result = Invoke-NativeCaptured -FilePath $PythonPath -Arguments $cmdArgs
    foreach ($line in $result.Output) {
        Add-Content -LiteralPath $LogPath -Value ("[{0}] {1}" -f $SpiderName, $line)
    }
    $spiderEnd = Get-Date

    return [PSCustomObject]@{
        SpiderName = $SpiderName
        ExitCode   = $result.ExitCode
        StartedAt  = $spiderStart
        EndedAt    = $spiderEnd
        Duration   = [Math]::Round(($spiderEnd - $spiderStart).TotalSeconds, 2)
        OutputPath = $OutputPath
    }
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

    $stdOut = $stdOutBuilder.ToString()
    $stdErr = $stdErrBuilder.ToString()

    $outputLines = @()
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

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$reportsDir = Join-Path $repoRoot "reports"
New-DirectoryIfMissing -Path $reportsDir

$dateStamp = Get-Date -Format "yyyy-MM-dd"
$runStamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$reportPath = Join-Path $reportsDir ("report-{0}.txt" -f $dateStamp)
$latestReportPath = Join-Path $reportsDir "latest-report.txt"
$runLogPath = Join-Path $reportsDir ("run-{0}.log" -f $runStamp)
$afxOutputPath = Join-Path $reportsDir ("afx_output-{0}.jsonl" -f $dateStamp)
$stockOutputPath = Join-Path $reportsDir ("stockanalysis_output-{0}.jsonl" -f $dateStamp)

$runStartedAt = Get-Date
Push-Location $repoRoot
try {
    $pythonPath = Resolve-PythonExecutable -RepoRoot $repoRoot
    if (-not $pythonPath) {
        throw "No virtual environment Python found. Expected one of: .venv\Scripts\python.exe, env\Scripts\python.exe, venv\Scripts\python.exe"
    }

    if (-not (Test-ScrapyInstalled -PythonPath $pythonPath)) {
        if ($BootstrapDeps) {
            $requirementsPath = Join-Path $repoRoot "requirements.txt"
            $pipInstall = Invoke-NativeCaptured -FilePath $pythonPath -Arguments @("-m", "pip", "install", "-r", $requirementsPath)
            foreach ($line in $pipInstall.Output) {
                Write-Host $line
            }
            if ($pipInstall.ExitCode -ne 0 -or -not (Test-ScrapyInstalled -PythonPath $pythonPath)) {
                throw "Dependency bootstrap failed. Could not install Scrapy in environment: $pythonPath"
            }
        }
        else {
            throw "Scrapy is not installed in environment '$pythonPath'. Run once with -BootstrapDeps or install manually: `"$pythonPath`" -m pip install -r requirements.txt"
        }
    }

    $afxRun = Invoke-SpiderRun -PythonPath $pythonPath -SpiderName "afx_scraper" -OutputPath $afxOutputPath -LogPath $runLogPath
    $stockRun = Invoke-SpiderRun -PythonPath $pythonPath -SpiderName "stockanalysis_scraper" -OutputPath $stockOutputPath -LogPath $runLogPath

    $afxRows = Get-JsonlRows -Path $afxOutputPath
    $stockRows = Get-JsonlRows -Path $stockOutputPath
    $afxCount = @($afxRows).Count
    $stockCount = @($stockRows).Count

    $viewCounts = @{}
    $nullMetricCount = 0
    $nonNullMetricCount = 0
    foreach ($row in $stockRows) {
        $view = [string]$row.view
        if (-not $viewCounts.ContainsKey($view)) {
            $viewCounts[$view] = 0
        }
        $viewCounts[$view]++

        if ($null -ne $row.metrics) {
            foreach ($metric in $row.metrics.PSObject.Properties) {
                if ($null -eq $metric.Value) {
                    $nullMetricCount++
                }
                else {
                    $nonNullMetricCount++
                }
            }
        }
    }

    $topAfx = $afxRows | Select-Object -First 5
    $topStockOverview = $stockRows | Where-Object { $_.view -eq "overview" } | Select-Object -First 5
    $runEndedAt = Get-Date
    $overallSuccess = ($afxRun.ExitCode -eq 0 -and $stockRun.ExitCode -eq 0)

    $report = @()
    $report += "Daily Scraper Report"
    $report += "Date: $dateStamp"
    $report += ""
    $report += "Run Summary"
    $report += "Start: $($runStartedAt.ToString('yyyy-MM-dd HH:mm:ss'))"
    $report += "End:   $($runEndedAt.ToString('yyyy-MM-dd HH:mm:ss'))"
    $report += ("DurationSeconds: {0}" -f [Math]::Round(($runEndedAt - $runStartedAt).TotalSeconds, 2))
    $report += ("OverallStatus: {0}" -f ($(if ($overallSuccess) { "SUCCESS" } else { "FAILED" })))
    $report += ""
    $report += "Scrape Metrics"
    $report += ("afx_scraper: rows={0}, exitCode={1}, durationSec={2}" -f $afxCount, $afxRun.ExitCode, $afxRun.Duration)
    $report += ("stockanalysis_scraper: rows={0}, exitCode={1}, durationSec={2}" -f $stockCount, $stockRun.ExitCode, $stockRun.Duration)
    $report += "stockanalysis view counts:"
    foreach ($key in ($viewCounts.Keys | Sort-Object)) {
        $report += ("- {0}: {1}" -f $key, $viewCounts[$key])
    }
    $report += ("stockanalysis metrics non-null={0}, null={1}" -f $nonNullMetricCount, $nullMetricCount)
    $report += ""
    $report += "Top Samples (AFX)"
    if (@($topAfx).Count -eq 0) {
        $report += "- No rows captured"
    }
    else {
        foreach ($row in $topAfx) {
            $symbol = [string]$row.ticker_symbol
            $name = [string]$row.stock_name
            $price = [string]$row.stock_price
            $change = [string]$row.stock_change
            $report += ("- {0} | {1} | price={2} | change={3}" -f $symbol, $name, $price, $change)
        }
    }
    $report += ""
    $report += "Top Samples (StockAnalysis Overview)"
    if (@($topStockOverview).Count -eq 0) {
        $report += "- No overview rows captured"
    }
    else {
        foreach ($row in $topStockOverview) {
            $symbol = [string]$row.ticker_symbol
            $name = [string]$row.company_name
            $price = [string]$row.stock_price
            $change = [string]$row.stock_change
            $report += ("- {0} | {1} | price={2} | change={3}" -f $symbol, $name, $price, $change)
        }
    }
    $report += ""
    $report += "Artifacts"
    $report += ("- AFX output: {0}" -f $afxOutputPath)
    $report += ("- StockAnalysis output: {0}" -f $stockOutputPath)
    $report += ("- Run log: {0}" -f $runLogPath)

    $report | Set-Content -LiteralPath $reportPath -Encoding UTF8
    $report | Set-Content -LiteralPath $latestReportPath -Encoding UTF8

    $commitMessage = "chore(report): daily afx+stockanalysis run $dateStamp"
    $tracked = @($reportPath, $latestReportPath, $afxOutputPath, $stockOutputPath, $runLogPath)
    $tracked = $tracked | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object {
        Get-RelativePath -FromPath $repoRoot -ToPath $_
    }

    & git add -- $tracked
    & git diff --cached --quiet
    $hasChanges = ($LASTEXITCODE -ne 0)
    if ($hasChanges) {
        & git commit -m $commitMessage | Out-Null
        if (-not $NoGitPush) {
            $branch = (& git branch --show-current).Trim()
            if (-not $branch) {
                $branch = "main"
            }
            & git push origin $branch | Out-Null
        }
    }

    if (-not $NoNotepad -and [Environment]::UserInteractive) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath) -ErrorAction SilentlyContinue | Out-Null
    }

    if (-not $overallSuccess) {
        throw "One or more spiders failed. Check run log: $runLogPath"
    }
}
finally {
    Pop-Location
}
