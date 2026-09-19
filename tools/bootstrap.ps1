param([string]$Name, [string]$Email)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git first.' }
    python --version
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3 first.' }
    if ($Name) { git config --local user.name $Name }
    if ($Email) { git config --local user.email $Email }
    if (-not (git config user.name) -or -not (git config user.email)) { throw 'Supply -Name and -Email for your own Git identity.' }
    git config --local core.hooksPath .githooks
    git config --local core.autocrlf false
    git config --local core.quotepath false
    git config --local pull.ff only
    git config --local fetch.prune true
    git config --local push.default simple
    Write-Host 'Local collaboration setup complete. Use task branches and pull requests.'
} finally { Pop-Location }
