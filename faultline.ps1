# Keep the caller's working directory and pass every argument to the CLI.
$ErrorActionPreference = 'Stop'
try {
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $uvPath = if ($uv) { $uv.Source } else { $null }
    if (-not $uvPath) {
        foreach ($directory in @("$HOME\.local\bin", "$HOME\.cargo\bin")) {
            $candidate = Join-Path $directory 'uv.exe'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $uvPath = $candidate
                break
            }
        }
    }
    if (-not $uvPath) { throw "uv is required. Run $PSScriptRoot\setup.ps1 (or setup.bat) first." }
    $env:PATH = "$(Split-Path -Parent $uvPath);$env:PATH"
    $env:PYTHONUTF8 = '1'
    & $uvPath run --project (Join-Path $PSScriptRoot 'services/repair-orchestrator') --python 3.13 --locked --no-env-file python -m app.cli @args
    exit $LASTEXITCODE
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
