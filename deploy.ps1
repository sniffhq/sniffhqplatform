# ============================================================
#  SniffHQ Platform — One-Time Deployment Script
#  Run as Administrator on the VPS
#  Sets up the platform admin app at admin.sniffhq.app (port 9000)
# ============================================================

param(
    [string]$PlatformDir = "C:\SniffHQPlatform",
    [string]$PythonExe   = "python",
    [string]$NssmExe     = "C:\nssm\win64\nssm.exe",
    [int]   $Port        = 9000
)

$ServiceName = "SniffHQPlatform"
$SiteName    = "SniffHQPlatform"

# ── Helper ──────────────────────────────────────────────────
function Write-Step([string]$msg) { Write-Host "`n▶  $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "   ✓  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "   ⚠  $msg" -ForegroundColor Yellow }
function Fail([string]$msg)       { Write-Host "`n✗  ERROR: $msg" -ForegroundColor Red; exit 1 }

# ── Pre-flight ───────────────────────────────────────────────
Write-Step "Checking prerequisites"

if (-not (Test-Path $PlatformDir)) { Fail "$PlatformDir not found. Clone or copy SniffHQPlatform there first." }
if (-not (Test-Path "$PlatformDir\.env")) {
    if (Test-Path "$PlatformDir\.env.example") {
        Write-Warn ".env not found — copying .env.example to .env. Fill in all values before starting the service."
        Copy-Item "$PlatformDir\.env.example" "$PlatformDir\.env"
    } else {
        Fail ".env not found at $PlatformDir\.env — create it from .env.example first."
    }
}
if (-not (Test-Path $NssmExe)) {
    Fail "NSSM not found at $NssmExe. Download from https://nssm.cc/download and extract to C:\nssm\"
}

# Verify Python
try { & $PythonExe --version | Out-Null } catch { Fail "Python not found at '$PythonExe'. Install Python 3.10+ and ensure it's in PATH." }
Write-OK "Prerequisites OK"

# ── Install Python dependencies ───────────────────────────────
Write-Step "Installing Python dependencies"
Push-Location $PlatformDir
& $PythonExe -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Fail "pip install failed — check requirements.txt and your Python environment." }
Write-OK "Dependencies installed"
Pop-Location

# ── Create tenants directory ─────────────────────────────────
Write-Step "Creating tenants directory"
$envContent = Get-Content "$PlatformDir\.env" | Where-Object { $_ -match "^TENANTS_DIR=" }
$tenantsDir = if ($envContent) { ($envContent -split "=", 2)[1].Trim() } else { "C:\SniffHQ\tenants" }
if (-not (Test-Path $tenantsDir)) {
    New-Item -ItemType Directory -Path $tenantsDir -Force | Out-Null
    Write-OK "Created $tenantsDir"
} else {
    Write-OK "$tenantsDir already exists"
}

# ── Register Windows service via NSSM ────────────────────────
Write-Step "Registering Windows service: $ServiceName"

$existing = & $NssmExe status $ServiceName 2>&1
if ($existing -notmatch "Can't open service") {
    Write-Warn "Service '$ServiceName' already exists — stopping and reconfiguring."
    & $NssmExe stop $ServiceName confirm 2>&1 | Out-Null
    & $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
}

# Find Python executable in venv or system
$pythonPath = (Get-Command $PythonExe).Source

& $NssmExe install $ServiceName $pythonPath
& $NssmExe set     $ServiceName AppParameters "-m waitress --host=127.0.0.1 --port=$Port app:app"
& $NssmExe set     $ServiceName AppDirectory  $PlatformDir
& $NssmExe set     $ServiceName AppEnvironmentExtra "FLASK_ENV=production"
& $NssmExe set     $ServiceName DisplayName   "SniffHQ Platform Admin"
& $NssmExe set     $ServiceName Description   "SniffHQ multi-tenant control plane — admin.sniffhq.app"
& $NssmExe set     $ServiceName Start         SERVICE_AUTO_START
& $NssmExe set     $ServiceName AppStdout     "$PlatformDir\logs\platform_stdout.log"
& $NssmExe set     $ServiceName AppStderr     "$PlatformDir\logs\platform_stderr.log"
& $NssmExe set     $ServiceName AppRotateFiles 1
& $NssmExe set     $ServiceName AppRotateSeconds 86400

# Create logs dir
New-Item -ItemType Directory -Path "$PlatformDir\logs" -Force | Out-Null

# Start service
& $NssmExe start $ServiceName
if ($LASTEXITCODE -ne 0) { Fail "Service failed to start. Check $PlatformDir\logs\platform_stderr.log" }
Write-OK "Service '$ServiceName' started on port $Port"

# ── IIS ARR setup ────────────────────────────────────────────
Write-Step "Configuring IIS Application Request Routing"

# Import WebAdministration module
Import-Module WebAdministration -ErrorAction SilentlyContinue
if (-not (Get-Module WebAdministration)) {
    Write-Warn "WebAdministration module not available — do IIS steps manually (see below)."
} else {
    # Create IIS site for admin.sniffhq.app
    if (Get-WebSite -Name $SiteName -ErrorAction SilentlyContinue) {
        Write-Warn "IIS site '$SiteName' already exists — skipping creation."
    } else {
        # Create a minimal physical directory for the IIS site
        $siteRoot = "$PlatformDir\iis_root"
        New-Item -ItemType Directory -Path $siteRoot -Force | Out-Null
        New-WebSite -Name $SiteName -PhysicalPath $siteRoot -Port 80 -HostHeader "admin.sniffhq.app" | Out-Null
        Write-OK "IIS site '$SiteName' created (HTTP, admin.sniffhq.app)"
    }

    # Enable ARR proxy at server level (required once per server)
    Set-WebConfigurationProperty -Filter "system.webServer/proxy" -Name "enabled" -Value $true -PSPath "IIS:\" -ErrorAction SilentlyContinue

    # Add URL Rewrite reverse proxy rule to the site
    $ruleName = "ReverseProxy_Platform"
    $sitePath = "IIS:\Sites\$SiteName"
    $filter   = "system.webServer/rewrite/rules/rule[@name='$ruleName']"

    if (Get-WebConfigurationProperty -Filter $filter -Name "name" -PSPath $sitePath -ErrorAction SilentlyContinue) {
        Write-Warn "Rewrite rule '$ruleName' already exists — skipping."
    } else {
        Add-WebConfigurationProperty -Filter "system.webServer/rewrite/rules" -Name "." -Value @{
            name       = $ruleName
            patternSyntax = "ECMAScript"
            stopProcessing = "True"
        } -PSPath $sitePath

        Set-WebConfigurationProperty -Filter "$filter/match"      -Name "url"   -Value "(.*)"          -PSPath $sitePath
        Set-WebConfigurationProperty -Filter "$filter/action"     -Name "type"  -Value "Rewrite"        -PSPath $sitePath
        Set-WebConfigurationProperty -Filter "$filter/action"     -Name "url"   -Value "http://127.0.0.1:$Port/{R:1}" -PSPath $sitePath

        Write-OK "Rewrite rule added: admin.sniffhq.app → http://127.0.0.1:$Port"
    }
}

# ── Summary ──────────────────────────────────────────────────
Write-Host @"

═══════════════════════════════════════════════════════════════
  SniffHQ Platform deployment complete
═══════════════════════════════════════════════════════════════

  Service:  $ServiceName  (port $Port)
  Logs:     $PlatformDir\logs\
  URL:      https://admin.sniffhq.app  (after SSL cert)

  MANUAL STEPS REMAINING:
  ────────────────────────────────────────────────────────────
  1. Edit $PlatformDir\.env  — fill in all required values
     (PLATFORM_SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, MAIL_*)
     Then restart the service:  nssm restart $ServiceName

  2. SSL Certificate for admin.sniffhq.app
     - Install via IIS Manager → Server Certificates → Let's Encrypt
       (use win-acme: https://www.win-acme.com/)
     - Add HTTPS binding (port 443) to the '$SiteName' site
     - Enable HSTS redirect in the web.config (optional)

  3. IIS ARR (if WebAdministration module was unavailable):
     a. Open IIS Manager → Application Request Routing → Server Proxy Settings
        → Enable proxy  [Apply]
     b. Select site '$SiteName' → URL Rewrite → Add Rule(s)
        → Reverse Proxy  →  Server name: 127.0.0.1:$Port  [OK]

  4. For each new tenant provisioned, run the generated
     setup_{slug}.ps1 script in C:\SniffHQ\tenants\{slug}\

═══════════════════════════════════════════════════════════════
"@ -ForegroundColor White
