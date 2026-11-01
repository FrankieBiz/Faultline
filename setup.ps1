# Native Windows setup; no system Python or Unix shell is required.
$ErrorActionPreference = 'Stop'

function Find-Uv {
    $command = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    foreach ($directory in @("$HOME\.local\bin", "$HOME\.cargo\bin")) {
        $candidate = Join-Path $directory 'uv.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        $code = $LASTEXITCODE
        Write-Error "$Program failed (exit $code). Setup stopped." -ErrorAction Continue
        exit $code
    }
}

try {
    $uv = Find-Uv
    if (-not $uv) {
        Write-Host 'Installing uv from https://astral.sh/uv/install.ps1 ...'
        try {
            Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue
            $global:LASTEXITCODE = 0
            Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression
            if ($LASTEXITCODE -ne 0) { throw "uv installer failed (exit $LASTEXITCODE)." }
            if (-not (Find-Uv)) { throw 'uv installer did not provide uv.' }
        }
        catch {
            Write-Warning "uv installer failed: $_. Trying the official Windows zip instead."
            $temporary = Join-Path ([IO.Path]::GetTempPath()) "faultline-uv-$([guid]::NewGuid())"
            try {
                New-Item -ItemType Directory -Path $temporary | Out-Null
                $archive = Join-Path $temporary 'uv.zip'
                Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $archive
                $extracted = Join-Path $temporary 'extracted'
                Expand-Archive -LiteralPath $archive -DestinationPath $extracted
                $destination = Join-Path $HOME '.local\bin'
                New-Item -ItemType Directory -Force -Path $destination | Out-Null
                foreach ($binary in @('uv.exe', 'uvx.exe')) {
                    Copy-Item -LiteralPath (Join-Path $extracted $binary) -Destination $destination -Force
                }
            }
            finally {
                if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
            }
        }
        $uv = Find-Uv
        if (-not $uv) { throw 'uv installation did not provide uv. Add uv to PATH and rerun .\setup.ps1.' }
    }
    $env:PATH = "$(Split-Path -Parent $uv);$env:PATH"
    $node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $npm = Get-Command npm.cmd, npm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $npx = Get-Command npx.cmd, npx -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $node -or -not $npm -or -not $npx) {
        throw 'Node.js and npm are required. Install Node.js 24+ (including npm), reopen your terminal, and rerun .\setup.ps1.'
    }
    $nodeVersion = & $node.Source --version
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the Node.js version. Reinstall Node.js 24+.' }
    $version = [version]($nodeVersion.Trim().TrimStart('v'))
    if (-not (($version.Major -eq 20 -and $version.Minor -ge 19) -or
              ($version.Major -eq 22 -and $version.Minor -ge 13) -or $version.Major -ge 24)) {
        throw 'Node.js 20.19+, 22.13+, or 24+ is required by the locked dependencies; Node.js 24+ is recommended.'
    }
    Push-Location -LiteralPath $PSScriptRoot
    try {
        Invoke-Checked $uv @('python', 'install', '3.13')
        foreach ($project in @('apps/buggyshop-backend', 'services/repair-orchestrator')) {
            Invoke-Checked $uv @('sync', '--project', $project, '--python', '3.13', '--locked')
        }
        foreach ($project in @('apps/buggyshop-frontend', 'tools/browser-runner', 'web/inspector-ui')) {
            Invoke-Checked $npm.Source @('--prefix', $project, 'ci')
        }
        Invoke-Checked $npm.Source @('--prefix', 'tools/browser-runner', 'run', 'build')
        Push-Location -LiteralPath 'tools/browser-runner'
        try { Invoke-Checked $npx.Source @('playwright', 'install', 'chromium') }
        finally { Pop-Location }
    }
    finally { Pop-Location }
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
