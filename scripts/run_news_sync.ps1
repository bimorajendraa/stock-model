# Daily news sync -- invoked by the "IDXPlatform_DailyNewsSync" Windows
# Scheduled Task (see docs/news.md's scheduling section for how it was
# created, how to inspect it, and how to remove it).
#
# Wraps `python -m src.cli news sync` with logging, since schtasks itself
# doesn't capture stdout/stderr -- every run appends a timestamped entry
# to logs/news_sync.log so failures are visible without opening Task
# Scheduler.
#
# Real constraint found live: this machine's account has no "Log on as a
# batch job" right and there's no admin session available to grant one
# (secedit /export itself fails with "you do not have sufficient
# permissions" for a non-admin user, and Windows 11 Home has no
# secpol.msc GUI either) -- so the task's LogonType=Password/S4U option
# ("run whether user is logged on or not") is unavailable, and the
# LogonType=Interactive + Daily-trigger combination was observed to
# intermittently fail with ERROR_PRIVILEGE_NOT_HELD (0x80070522) when
# the 06:00 trigger fired without a genuine interactive session behind
# it. The task is therefore ALSO triggered "At log on", which is always
# backed by a real interactive session -- so this script self-throttles
# to once/day via a marker file, since a user may log on more than once
# in a day and the 06:00 trigger may also fire on top of a same-day logon.
#
# Real second blocker found live: Docker Desktop's own "start at login"
# setting was off, so the `db` container (Postgres, port 5433) wasn't
# reachable when this ran unattended, even once the Task Scheduler side
# was fixed -- `psycopg.errors.ConnectionTimeout` on localhost:5433. Not
# fixed by editing Docker's internal settings-store.json directly (that
# was rejected as the wrong way to change a supported, user-facing
# Docker Desktop setting); instead this script launches Docker Desktop
# itself if the db port isn't already open, and waits for it before
# running the sync.

$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\Users\Bimo\code\scrape\stock-model"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "news_sync.log"
$MarkerFile = Join-Path $LogDir "news_sync.lastrun"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

$today = Get-Date -Format "yyyy-MM-dd"
if ((Test-Path $MarkerFile) -and ((Get-Content $MarkerFile -Raw).Trim() -eq $today)) {
    Add-Content -Path $LogFile -Value "===== ${today}: news sync skipped (already ran today) =====" -Encoding utf8
    exit 0
}

Set-Location $ProjectRoot
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "===== ${timestamp}: news sync starting =====" -Encoding utf8

$dbReady = (Test-NetConnection -ComputerName "localhost" -Port 5433 -WarningAction SilentlyContinue -InformationLevel Quiet)
if (-not $dbReady) {
    Add-Content -Path $LogFile -Value "----- db not reachable on 5433, launching Docker Desktop -----" -Encoding utf8
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $waited = 0
    while (-not $dbReady -and $waited -lt 120) {
        Start-Sleep -Seconds 5
        $waited += 5
        $dbReady = (Test-NetConnection -ComputerName "localhost" -Port 5433 -WarningAction SilentlyContinue -InformationLevel Quiet)
    }
    if (-not $dbReady) {
        Add-Content -Path $LogFile -Value "===== ${timestamp}: news sync FAILED: db still unreachable after ${waited}s wait =====" -Encoding utf8
        exit 1
    }
    Add-Content -Path $LogFile -Value "----- db reachable after ${waited}s -----" -Encoding utf8
}

try {
    # Real bug hit here: piping python.exe's output straight into
    # Tee-Object -FilePath produced a UTF-16-vs-UTF-8 mismatch (every
    # character space-separated when read back) -- capturing to a
    # variable first and writing it explicitly with -Encoding utf8
    # avoids Tee-Object's own encoding behavior entirely.
    $output = & "$ProjectRoot\.venv\Scripts\python.exe" -m src.cli news sync 2>&1
    $output | Out-String | Write-Host
    Add-Content -Path $LogFile -Value $output -Encoding utf8
    $doneTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "===== ${doneTimestamp}: news sync finished OK =====" -Encoding utf8
    Set-Content -Path $MarkerFile -Value $today -Encoding utf8
} catch {
    $failTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "===== ${failTimestamp}: news sync FAILED: $_ =====" -Encoding utf8
    exit 1
}
