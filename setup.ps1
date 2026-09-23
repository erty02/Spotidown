# Local Python package: https://www.python.org/ftp/python/3.13.15/windows-3.13.15.json
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath $PSScriptRoot

$runtimeDir = Join-Path $PSScriptRoot '.runtime'
$pythonDir = Join-Path $runtimeDir 'python'
$pythonExe = Join-Path $pythonDir 'python.exe'
$requirementsFile = Join-Path $PSScriptRoot 'requirements.txt'
$requirementsStamp = Join-Path $runtimeDir 'requirements.sha256'
$ffmpegDir = Join-Path $PSScriptRoot 'ffmpeg'
$ffmpegExe = Join-Path $ffmpegDir 'bin\ffmpeg.exe'

# Do not inherit settings from an unrelated Python installation.
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'

function Test-PythonCode([string]$Code) {
    if (-not (Test-Path -LiteralPath $pythonExe)) { return $false }
    # Windows PowerShell 5 turns native stderr into errors under Stop.
    $ErrorActionPreference = 'Continue'
    try {
        & $pythonExe -c $Code *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Test-LocalPython {
    return (Test-PythonCode "import sys, tkinter; assert sys.version_info[:2] == (3, 13); root = tkinter.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()")
}

function Invoke-LocalPython([string[]]$PythonArgs) {
    $ErrorActionPreference = 'Continue'
    & $pythonExe @PythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python setup step failed (exit code $LASTEXITCODE). Check the messages above."
    }
}

try {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host '1. Checking local Python...'
    if (-not (Test-LocalPython)) {
        if (-not [Environment]::Is64BitOperatingSystem) {
            throw 'This automatic setup requires 64-bit Windows.'
        }
        $archive = Join-Path $runtimeDir 'python-3.13.15-amd64.zip'
        $expectedHash = '6479223746cdfb79d25865110d6f524ac98de081324e119af1dc3ae36bddc7a5'
        $archiveValid = (Test-Path -LiteralPath $archive) -and
            ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -eq $expectedHash)
        if (-not $archiveValid) {
            Write-Host '   Downloading Python from python.org (first launch only)...'
            Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.zip' -OutFile $archive
        }
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
            throw 'Python archive checksum did not match. Run start.bat again to retry.'
        }
        Write-Host '   Unpacking Python...'
        Expand-Archive -LiteralPath $archive -DestinationPath $pythonDir -Force
        if (-not (Test-LocalPython)) { throw 'Local Python or its window library could not start.' }
    }

    Write-Host '2. Checking application libraries...'
    $requirementsHash = (Get-FileHash -LiteralPath $requirementsFile -Algorithm SHA256).Hash
    $savedHash = if (Test-Path -LiteralPath $requirementsStamp) {
        (Get-Content -LiteralPath $requirementsStamp -Raw).Trim()
    } else { '' }
    $librariesReady = Test-PythonCode "import spotipy, yt_dlp, mutagen, requests, lyricsgenius, thefuzz, bs4; from PIL import Image; import main"
    if (-not $librariesReady -or $savedHash -ne $requirementsHash) {
        Write-Host '   Installing required libraries...'
        Invoke-LocalPython @('-m', 'ensurepip', '--upgrade')
        Invoke-LocalPython @('-m', 'pip', 'install', '--no-cache-dir', '--no-warn-script-location', '-r', $requirementsFile)
        Invoke-LocalPython @('-c', 'import main; from PIL import Image; import thefuzz')
        Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ASCII
    }

    Write-Host '3. Checking FFmpeg...'
    if (-not (Test-Path -LiteralPath $ffmpegExe)) {
        $ffmpegArchive = Join-Path $runtimeDir 'ffmpeg.zip'
        $unpackDir = Join-Path $runtimeDir ('ffmpeg-' + [guid]::NewGuid().ToString('N'))
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ffmpegArchive
        Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath $unpackDir
        $extractedExe = Get-ChildItem -LiteralPath $unpackDir -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1
        if (-not $extractedExe) { throw 'FFmpeg archive did not contain ffmpeg.exe.' }
        $extractedRoot = $extractedExe.Directory.Parent.FullName
        New-Item -ItemType Directory -Path $ffmpegDir -Force | Out-Null
        Get-ChildItem -LiteralPath $extractedRoot | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $ffmpegDir -Recurse -Force
        }
    }
    & $ffmpegExe -version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg could not start.' }

    Write-Host 'Ready. Launching SpotiDown.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host ("Setup failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
