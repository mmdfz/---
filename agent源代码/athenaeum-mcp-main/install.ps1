<#
.SYNOPSIS
    Athenaeum MCP — one-step installer / uninstaller for Windows.

.DESCRIPTION
    Sets up a self-contained Python environment for the Athenaeum MCP server and
    auto-configures it in your AI coding clients (VS Code, Claude, Cursor,
    Windsurf, Codex, OpenCode, Gemini CLI). Re-running is safe and idempotent.

    The same script uninstalls: pass -Uninstall to remove Athenaeum from every
    client config (backups are created) and, with -Purge, delete the virtual
    environment too.

.PARAMETER Scope
    'project' (default) writes config into the target project folder; 'user'
    writes global config for each client.

.PARAMETER Project
    Project root for project-scope config. Defaults to the folder that CONTAINS
    this athenaeum-mcp directory (i.e. your workspace).

.PARAMETER Clients
    Specific clients to target (e.g. vscode cursor). Default: auto-detected.
    Use 'all' to target every known client.

.PARAMETER Uninstall
    Remove Athenaeum from client configurations instead of installing.

.PARAMETER Purge
    With -Uninstall, also delete the .venv and cache folders.

.PARAMETER DryRun
    Show what would change without writing anything.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -Clients vscode cursor
.EXAMPLE
    .\install.ps1 -Uninstall
.EXAMPLE
    .\install.ps1 -Uninstall -Purge
#>
[CmdletBinding()]
param(
    [ValidateSet('project', 'user')]
    [string]$Scope = 'project',
    [string]$Project,
    [string[]]$Clients,
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvPython = Join-Path $Here '.venv\Scripts\python.exe'

# Default the project root to the parent of athenaeum-mcp (your workspace).
if (-not $Project) { $Project = (Get-Item $Here).Parent.FullName }

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    $msg" -ForegroundColor Yellow }

function Find-BasePython {
    foreach ($cand in @('py -3', 'python', 'python3')) {
        $parts = $cand.Split(' ')
        $exe = $parts[0]
        try {
            $ver = & $exe @($parts[1..($parts.Length-1)] + '--version') 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -match '3\.(1[0-9]|[2-9][0-9])') { return $cand }
        } catch { }
    }
    return $null
}

function Invoke-Configurator([string[]]$cfgArgs) {
    if (-not (Test-Path $VenvPython)) {
        throw "Virtual environment not found. Run the installer without -Uninstall first."
    }
    & $VenvPython '-m' 'athenaeum_mcp.configurator' @cfgArgs
}

# --------------------------------------------------------------------------- #
# Uninstall path
# --------------------------------------------------------------------------- #
if ($Uninstall) {
    Write-Step "Uninstalling Athenaeum from client configurations"
    $args = @('uninstall', '--project', $Project)
    if ($Clients) { $args += @('--clients') + $Clients }
    if ($DryRun)  { $args += '--dry-run' }
    if (Test-Path $VenvPython) {
        Invoke-Configurator $args
    } else {
        Write-Warn2 "No virtual environment found; nothing to run the configurator with."
    }

    if ($Purge -and -not $DryRun) {
        Write-Step "Purging virtual environment and caches"
        foreach ($d in @('.venv', '.athenaeum_cache')) {
            $p = Join-Path $Here $d
            if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Ok "removed $d" }
        }
        $cache = Join-Path $Project '.athenaeum_cache'
        if (Test-Path $cache) { Remove-Item -Recurse -Force $cache; Write-Ok "removed project cache" }
    }
    Write-Host "`nUninstall complete." -ForegroundColor Green
    return
}

# --------------------------------------------------------------------------- #
# Install path
# --------------------------------------------------------------------------- #
Write-Step "Athenaeum MCP installer"
Write-Host "    project root : $Project"
Write-Host "    scope        : $Scope"

if (-not (Test-Path $VenvPython)) {
    $base = Find-BasePython
    if (-not $base) {
        Write-Error "Python 3.10+ was not found. Install it from https://python.org and re-run."
        return
    }
    Write-Step "Creating virtual environment (.venv)"
    $parts = $base.Split(' ')
    & $parts[0] @($parts[1..($parts.Length-1)] + @('-m', 'venv', (Join-Path $Here '.venv')))
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create virtual environment."; return }
    Write-Ok "created"
} else {
    Write-Ok "virtual environment already present"
}

Write-Step "Installing Athenaeum and dependencies (this may take a minute)"
& $VenvPython '-m' 'pip' 'install' '--upgrade' 'pip' '--quiet'
& $VenvPython '-m' 'pip' 'install' '-e' $Here '--quiet'
if ($LASTEXITCODE -ne 0) { Write-Error "Dependency installation failed."; return }
Write-Ok "installed"

# Seed a .env from the example if absent (all-optional settings).
$envFile = Join-Path $Here '.env'
$envExample = Join-Path $Here '.env.example'
if ((-not (Test-Path $envFile)) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-Ok "created .env (optional settings; safe to leave blank)"
}

Write-Step "Configuring MCP clients"
$cfgArgs = @('install', '--scope', $Scope, '--project', $Project)
if ($Clients) { $cfgArgs += @('--clients') + $Clients }
if ($DryRun)  { $cfgArgs += '--dry-run' }
Invoke-Configurator $cfgArgs

Write-Host "`nAll done. Restart your AI client (or reload its MCP servers) to use Athenaeum." -ForegroundColor Green
Write-Host "Try asking:  'Find the most-cited papers on technostress since 2018.'" -ForegroundColor Green
Write-Host "`nTo remove later:  .\install.ps1 -Uninstall   (add -Purge to also delete the venv)" -ForegroundColor DarkGray
