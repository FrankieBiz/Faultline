# Native foreground demo supervisor (Windows PowerShell 5.1 and PowerShell 7).
param([string]$StopFile = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$children = New-Object 'System.Collections.Generic.List[System.Diagnostics.Process]'
$services = New-Object 'System.Collections.Generic.List[System.Diagnostics.Process]'
$exitCode = 1

function Assert-Running {
    if ($StopFile -and (Test-Path -LiteralPath $StopFile)) {
        throw [System.OperationCanceledException]::new('Demo stopped.')
    }
    foreach ($service in $services) {
        if ($service.HasExited) { throw "A demo service exited (code $($service.ExitCode))." }
    }
}

function Start-Owned {
    param([string]$Directory, [string]$Program, [string[]]$Arguments)
    Assert-Running
    # These fixed arguments contain no spaces; directories and executable paths
    # are separate parameters so a clone under e.g. C:\My Projects works.
    $process = Start-Process -FilePath $Program -ArgumentList $Arguments -WorkingDirectory $Directory -NoNewWindow -PassThru
    $children.Add($process)
    return $process
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    Assert-Running
    Push-Location $root
    try {
        & $Program @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Build/setup command failed (exit $LASTEXITCODE). Run .\setup.bat first." }
    }
    finally { Pop-Location }
    Assert-Running
}

try {
    $names = @('BUGGYSHOP_API_PORT', 'FAULTLINE_PORT', 'BUGGYSHOP_PORT', 'INSPECTOR_PORT')
    $ports = @(8000, 9000, 3000, 4000)
    for ($index = 0; $index -lt 4; $index++) {
        $value = [Environment]::GetEnvironmentVariable($names[$index])
        if ($value) {
            $port = 0
            if (-not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
                throw "Invalid $($names[$index]): choose an integer between 1 and 65535."
            }
            $ports[$index] = $port
        }
    }
    if (@($ports | Select-Object -Unique).Count -ne 4) { throw 'Demo ports must be distinct.' }
    # Probe all ports before syncing, rebuilding, or starting any child.
    foreach ($port in $ports) {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
        $listener.Server.ExclusiveAddressUse = $true
        try { $listener.Start() }
        catch { throw "Demo port $port is occupied or unavailable. Stop its owner or choose free demo ports; no process was stopped." }
        finally { $listener.Stop() }
    }
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $uv) {
        foreach ($directory in @("$HOME\.local\bin", "$HOME\.cargo\bin")) {
            $candidate = Join-Path $directory 'uv.exe'
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $uv = Get-Item -LiteralPath $candidate
                break
            }
        }
    }
    if (-not $uv) { throw 'uv is required. Run .\setup.bat first.' }
    $uvPath = if ($uv.Source) { $uv.Source } else { $uv.FullName }
    $node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $npm = Get-Command npm.cmd, npm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $node -or -not $npm) { throw 'Node.js and npm are required. Run .\setup.bat first.' }
    $versionText = & $node.Source --version
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the Node.js version.' }
    $version = [version]($versionText.Trim().TrimStart('v'))
    if (-not (($version.Major -eq 20 -and $version.Minor -ge 19) -or
              ($version.Major -eq 22 -and $version.Minor -ge 13) -or $version.Major -ge 24)) {
        throw 'Node.js 20.19+, 22.13+, or 24+ is required; Node.js 24+ is recommended.'
    }
    foreach ($project in @('apps/buggyshop-frontend', 'tools/browser-runner', 'web/inspector-ui')) {
        if (-not (Test-Path -LiteralPath (Join-Path $root "$project/node_modules") -PathType Container)) {
            throw "Missing dependencies in $project. Run .\setup.bat first."
        }
    }
    # Call npm's JS entry point directly: .cmd files cannot be safely supervised
    # as executables by Start-Process with shell execution disabled.
    $npmCli = Join-Path (Split-Path -Parent $npm.Source) 'node_modules/npm/bin/npm-cli.js'
    if (-not (Test-Path -LiteralPath $npmCli)) { throw 'Cannot locate npm-cli.js beside npm. Reinstall Node.js with npm.' }
    Invoke-Checked $uvPath @('sync', '--project', 'services/repair-orchestrator', '--python', '3.13', '--locked')
    foreach ($project in @('tools/browser-runner', 'apps/buggyshop-frontend', 'web/inspector-ui')) {
        Invoke-Checked $node.Source @($npmCli, '--prefix', $project, 'run', 'build')
    }
    if (-not $env:FAULTLINE_CONTROL_TOKEN) {
        $bytes = New-Object byte[] 32
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($bytes) }
        finally { $random.Dispose() }
        $env:FAULTLINE_CONTROL_TOKEN = [Convert]::ToBase64String($bytes)
    }
    # Never log the session credential. Each child inherits the same token.
    $env:PYTHONPATH = $root
    $env:BUGGYSHOP_PORT = [string]$ports[2]
    $env:FAULTLINE_RUNTIME = 'isolated'
    $env:FAULTLINE_PROJECT_PORT = [string]$ports[0]
    $env:FAULTLINE_LIVE_STORE_URL = "http://127.0.0.1:$($ports[0])"
    $env:BUGGYSHOP_BACKEND_URL = $env:FAULTLINE_LIVE_STORE_URL
    $env:FAULTLINE_ORCHESTRATOR_URL = "http://127.0.0.1:$($ports[1])"
    $directories = @('apps/buggyshop-backend', 'services/repair-orchestrator', 'apps/buggyshop-frontend', 'web/inspector-ui')
    for ($index = 0; $index -lt 4; $index++) {
        $directory = Join-Path $root $directories[$index]
        if ($index -lt 2) {
            $service = Start-Owned $directory $uvPath @('run', '--python', '3.13', '--locked', '--no-env-file', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', [string]$ports[$index], '--log-level', 'warning')
        }
        else {
            $service = Start-Owned $directory $node.Source @('node_modules/next/dist/bin/next', 'start', '-p', [string]$ports[$index], '-H', '127.0.0.1')
        }
        $services.Add($service)
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    $pending = @(0, 1, 2, 3)
    while ($pending.Count -gt 0) {
        Assert-Running
        foreach ($index in @($pending)) {
            $path = if ($index -lt 2) { '/healthz' } else { '/' }
            $url = "http://127.0.0.1:$($ports[$index])$path"
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1
                if ($response.StatusCode -ne 200) { continue }
                if ($index -lt 2) {
                    $body = $response.Content | ConvertFrom-Json
                    $expected = @('buggyshop-api', 'faultline-orchestrator')[$index]
                    if ($body.app -ne $expected -or $body.status -ne 'ok') { continue }
                }
                $pending = @($pending | Where-Object { $_ -ne $index })
            }
            catch { } # Startup connection failures are expected until readiness.
        }
        if ($pending.Count -gt 0) {
            if ([DateTime]::UtcNow -ge $deadline) { throw "Demo startup timed out; unhealthy ports: $($ports[$pending] -join ', ')." }
            Start-Sleep -Milliseconds 250
        }
    }
    Write-Host "`nFaultLine Inspector: http://127.0.0.1:$($ports[3])"
    Write-Host "Storefront: http://127.0.0.1:$($ports[2])"
    Write-Host 'Explore the demo; sandbox repair requires Linux. Ctrl+C stops this session; evidence is retained.'
    while ($true) { Assert-Running; Start-Sleep -Milliseconds 250 }
}
catch [System.OperationCanceledException] { $exitCode = 130 }
catch { Write-Error $_ -ErrorAction Continue }
finally {
    # PowerShell runs finally on Ctrl+C too. Never kill by port or image name.
    foreach ($child in $children) {
        if (-not $child.HasExited) {
            if ($env:OS -eq 'Windows_NT') {
                & "$env:SystemRoot\System32\taskkill.exe" /PID $child.Id /T /F 2>$null | Out-Null
            }
            else { $child.Kill($true) } # Enables real PowerShell regression tests on Unix.
            $child.WaitForExit()
        }
        $child.Dispose()
    }
}
exit $exitCode
