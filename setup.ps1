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
        $global:LASTEXITCODE = 0
        Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
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
