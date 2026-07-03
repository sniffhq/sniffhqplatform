"""
provisioner.py — SniffHQ tenant provisioning logic

Called by app.py when Charles clicks Provision after verifying Wave payment.
"""

import os
import re
import sys
import secrets
import sqlite3
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

from dotenv import load_dotenv
load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

SNIFFHQ_APP_DIR = Path(os.environ.get('SNIFFHQ_APP_DIR', r'C:\SniffHQDemo'))
TENANTS_DIR     = Path(os.environ.get('TENANTS_DIR',     r'C:\SniffHQ\tenants'))
BASE_PORT       = int(os.environ.get('BASE_PORT', 8001))

MAIL_SERVER   = os.environ.get('MAIL_SERVER',   'smtp.zoho.com')
MAIL_PORT     = int(os.environ.get('MAIL_PORT', 587))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
FROM_EMAIL    = os.environ.get('MAIL_USERNAME', 'info@sniffhq.com')

TIER_DB_MAP = {
    'starter':      'starter',
    'professional': 'pro',
    'enterprise':   'enterprise',
}


class ProvisionError(Exception):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """'Jane\'s Pet Paradise' → 'janespetparadise'"""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]", "", slug)
    return slug[:50] or 'tenant'


def _next_available_port() -> int:
    """Find the next free TCP port starting from BASE_PORT."""
    port = BASE_PORT
    while port < BASE_PORT + 500:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                port += 1
    raise ProvisionError("No available ports in range. Check running services.")


def _first_name(business_name: str) -> str:
    """'Jane\'s Pet Paradise' → 'Jane'  (best-effort)"""
    return business_name.split()[0].rstrip("'s").rstrip("'") if business_name else 'there'


# ── Core provisioner ─────────────────────────────────────────────────────────

def provision_tenant(email: str, business_name: str, tier: str, slug: str) -> int:
    """
    Full tenant provisioning pipeline.
    Returns the assigned Waitress port.
    """
    tenant_dir   = TENANTS_DIR / slug
    instance_dir = tenant_dir / 'instance'

    try:
        instance_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise ProvisionError(f"Could not create tenant directory: {e}")

    db_path    = instance_dir / 'sniffhq.db'
    secret_key = secrets.token_hex(32)
    port       = _next_available_port()

    # Step 1 — Write .env
    _write_env(tenant_dir, db_path, secret_key, business_name, slug)

    # Step 2 — Initialise DB schema + seed BusinessSettings
    _init_db(db_path, secret_key, business_name, tier)

    # Step 3 — Create admin user + magic link, returns token
    magic_token = _seed_admin(db_path, email, business_name)

    # Step 4 — Send welcome email
    send_welcome_email(email, business_name, slug, magic_token)

    # Step 5 — Generate Windows service + IIS scripts
    _generate_setup_scripts(tenant_dir, slug, port)

    return port


# ── Step 1: .env ──────────────────────────────────────────────────────────────

def _write_env(tenant_dir: Path, db_path: Path, secret_key: str,
               business_name: str, slug: str):
    content = f"""# SniffHQ Tenant: {business_name}
SECRET_KEY={secret_key}
DATABASE_URL=sqlite:///{db_path.as_posix()}
UPLOAD_FOLDER=app/static/uploads

MAIL_SERVER={MAIL_SERVER}
MAIL_PORT={MAIL_PORT}
MAIL_USE_TLS=true
MAIL_USERNAME={MAIL_USERNAME}
MAIL_PASSWORD={MAIL_PASSWORD}

BUSINESS_NAME={business_name}
BUSINESS_DOMAIN={slug}.sniffhq.app
FLASK_DEBUG=0
"""
    (tenant_dir / '.env').write_text(content, encoding='utf-8')


# ── Step 2: Init DB ───────────────────────────────────────────────────────────

# schema.sql lives next to this file
SCHEMA_SQL = Path(__file__).parent / 'schema.sql'


def _init_db(db_path: Path, secret_key: str, business_name: str, tier: str):
    """
    Apply the static schema.sql to a fresh tenant SQLite DB, then seed
    a BusinessSettings row. No demo DB or external venv required.
    """
    if not SCHEMA_SQL.exists():
        raise ProvisionError(
            f"schema.sql not found at {SCHEMA_SQL}. "
            "Ensure it has been committed to the repo and pulled to the VPS."
        )

    schema = SCHEMA_SQL.read_text(encoding='utf-8')

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema)
        conn.commit()

        # Verify the critical table exists
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='business_settings'")
        if not cur.fetchone():
            raise ProvisionError("business_settings table missing after applying schema.sql.")

        # Seed BusinessSettings row
        db_tier = TIER_DB_MAP.get(tier.lower(), 'starter')
        cur.execute("SELECT COUNT(*) FROM business_settings")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO business_settings (tier) VALUES (?)",
                (db_tier,)
            )
            conn.commit()
    finally:
        conn.close()


# ── Step 3: Seed admin user ───────────────────────────────────────────────────

def _seed_admin(db_path: Path, email: str, business_name: str) -> str:
    """
    Create admin User + MagicLinkToken in the tenant DB.
    Returns the raw token string.
    """
    token      = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=72)).isoformat()

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    # Upsert user
    cur.execute("SELECT id FROM user WHERE email = ?", (email.lower(),))
    row = cur.fetchone()
    if row:
        user_id = row[0]
        # Ensure admin flag
        cur.execute("UPDATE user SET is_admin = 1 WHERE id = ?", (user_id,))
    else:
        first_name = _first_name(business_name)
        placeholder_pw = 'set-via-magic-link-' + secrets.token_hex(8)
        cur.execute(
            """INSERT INTO user
               (email, password_hash, first_name, last_name, is_admin, is_active, created_at)
               VALUES (?, ?, ?, '', 1, 1, ?)""",
            (email.lower(), placeholder_pw, first_name, datetime.utcnow().isoformat())
        )
        user_id = cur.lastrowid

    # Magic link token
    cur.execute(
        "INSERT INTO magic_link_token (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
        (token, user_id, expires_at)
    )
    conn.commit()
    conn.close()
    return token


# ── Step 4: Welcome email ─────────────────────────────────────────────────────

def send_welcome_email(email: str, business_name: str, slug: str,
                       token: str = None):
    """
    Send the welcome / magic-link email to the new tenant owner.
    If token is None (resend flow), a fresh token is created in the tenant DB.
    """
    if token is None:
        db_path = TENANTS_DIR / slug / 'instance' / 'sniffhq.db'
        if not db_path.exists():
            raise ProvisionError(f"Tenant DB not found at {db_path}")
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()
        cur.execute("SELECT id FROM user WHERE email = ?", (email.lower(),))
        row = cur.fetchone()
        if not row:
            raise ProvisionError(f"No user found for {email} in {slug}")
        token      = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(hours=72)).isoformat()
        cur.execute(
            "INSERT INTO magic_link_token (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
            (token, row[0], expires_at)
        )
        conn.commit()
        conn.close()

    login_url  = f"https://{slug}.sniffhq.app/auth/magic/{token}"
    first      = _first_name(business_name)

    subject = "Your SniffHQ account is ready 🐾"
    body    = f"""Hi {first},

Welcome to SniffHQ! Your account for {business_name} has been set up and is live.

Your dashboard:
https://{slug}.sniffhq.app

Click the link below to log in — no password needed. This link expires in 72 hours:
{login_url}

Once you're in, we recommend:
  1. Complete your Business Settings (name, address, phone)
  2. Add your first staff member
  3. Import or add your first customer

Questions? Email us anytime at info@sniffhq.com — we personally respond to every message.

Welcome aboard!
— Charles & the SniffHQ Team
"""

    msg              = MIMEMultipart()
    msg['From']      = FROM_EMAIL
    msg['To']        = email
    msg['Subject']   = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(FROM_EMAIL, [email], msg.as_string())
    except Exception as e:
        raise ProvisionError(f"Welcome email failed: {e}")


# ── Step 5: Setup scripts ─────────────────────────────────────────────────────

def _generate_setup_scripts(tenant_dir: Path, slug: str, port: int):
    """
    Write a .bat startup script and a PowerShell IIS registration script
    into the tenant directory. Charles runs these once on the VPS.
    """
    app_dir = SNIFFHQ_APP_DIR

    # Startup .bat — loads tenant .env, starts Waitress on assigned port
    bat = f"""@echo off
REM SniffHQ Tenant: {slug}
REM Run this once to start the tenant app, or register as a Windows service.
cd /d "{tenant_dir}"
set "DOTENV_OVERRIDE=1"
"{app_dir}\\venv\\Scripts\\waitress-serve.exe" ^
    --port={port} ^
    --threads=4 ^
    --call "app:create_app"
"""
    (tenant_dir / f'start_{slug}.bat').write_text(bat, encoding='utf-8')

    # PowerShell — registers Windows service via NSSM (if installed) + IIS ARR rule
    ps1 = f"""# Run as Administrator in PowerShell
# Registers {slug}.sniffhq.app as a Windows service and IIS reverse proxy

$slug    = "{slug}"
$port    = {port}
$svcName = "SniffHQ_$slug"
$batPath = "{tenant_dir}\\start_$slug.bat"

# --- Windows Service via NSSM ---
# Download NSSM from https://nssm.cc if not installed
if (Get-Command nssm -ErrorAction SilentlyContinue) {{
    nssm install $svcName $batPath
    nssm set $svcName DisplayName "SniffHQ — $slug"
    nssm set $svcName Description "SniffHQ tenant app for {slug}.sniffhq.app"
    nssm set $svcName Start SERVICE_AUTO_START
    nssm start $svcName
    Write-Host "Service $svcName installed and started on port $port" -ForegroundColor Green
}} else {{
    Write-Host "NSSM not found. Run start_$slug.bat manually or install NSSM." -ForegroundColor Yellow
}}

# --- IIS Reverse Proxy (requires ARR + URL Rewrite modules) ---
# In IIS Manager: add a server farm named $slug pointing to localhost:$port
# Then add a URL Rewrite inbound rule:
#   Pattern: .*
#   Conditions: {{HTTP_HOST}} matches ^{slug}\\.sniffhq\\.app$
#   Action: Route to server farm $slug
Write-Host ""
Write-Host "IIS manual step:" -ForegroundColor Cyan
Write-Host "  Add reverse proxy for {slug}.sniffhq.app → localhost:$port"
Write-Host "  Use IIS Manager > URL Rewrite > Add Rule > Reverse Proxy"
"""
    (tenant_dir / f'setup_{slug}.ps1').write_text(ps1, encoding='utf-8')
