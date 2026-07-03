"""
provisioner.py — SniffHQ tenant provisioning logic

Called by app.py when Charles clicks Provision after verifying Wave payment.

Automated steps:
  1. Write .env
  2. Initialise DB schema + seed BusinessSettings
  3. Create admin user + magic link token
  4. Send welcome email
  5. Register Windows service via NSSM
  6. Create IIS reverse-proxy site
  7. Create DNS A record via NameCheap API
  8. SSL cert — called separately via platform UI (provision_ssl)
"""

import os
import re
import secrets
import sqlite3
import socket
import subprocess
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
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

NSSM_EXE            = Path(os.environ.get('NSSM_EXE',  r'C:\nssm\win64\nssm.exe'))
WACS_EXE            = Path(os.environ.get('WACS_EXE',  r'C:\win-acme\wacs.exe'))
VPS_PUBLIC_IP       = os.environ.get('VPS_PUBLIC_IP', '')
NAMECHEAP_API_USER  = os.environ.get('NAMECHEAP_API_USER', '')
NAMECHEAP_API_KEY   = os.environ.get('NAMECHEAP_API_KEY', '')
NAMECHEAP_API_URL   = 'https://api.namecheap.com/xml.response'
NAMECHEAP_NS        = '{http://api.namecheap.com/xml.response}'

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

    # Step 3 — Create admin user + magic link
    magic_token = _seed_admin(db_path, email, business_name)

    # Step 4 — Send welcome email
    send_welcome_email(email, business_name, slug, magic_token)

    # Step 5 — Register Windows service via NSSM
    _register_service(tenant_dir, slug, port)

    # Step 6 — Create IIS reverse-proxy site
    _create_iis_site(tenant_dir, slug, port)

    # Step 7 — Create DNS A record via NameCheap API
    _create_dns_record(slug)

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

SCHEMA_SQL = Path(__file__).parent / 'schema.sql'


def _init_db(db_path: Path, secret_key: str, business_name: str, tier: str):
    """
    Apply the static schema.sql to a fresh tenant SQLite DB, then seed
    a BusinessSettings row.
    """
    if not SCHEMA_SQL.exists():
        raise ProvisionError(
            f"schema.sql not found at {SCHEMA_SQL}. "
            "Ensure it has been committed to the repo and pulled to the VPS."
        )

    schema = SCHEMA_SQL.read_text(encoding='utf-8')
    stmts  = [s.strip() for s in schema.split(';') if s.strip() and not s.strip().startswith('--')]

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        for stmt in stmts:
            try:
                cur.execute(stmt)
            except sqlite3.OperationalError as e:
                if 'already exists' not in str(e).lower():
                    raise ProvisionError(f"Schema error: {e} | {stmt[:120]}")
        conn.commit()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='business_settings'")
        if not cur.fetchone():
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            found = [r[0] for r in cur.fetchall()]
            raise ProvisionError(
                f"business_settings table missing after applying schema.sql. "
                f"Tables created: {found}"
            )

        db_tier = TIER_DB_MAP.get(tier.lower(), 'starter')
        cur.execute("SELECT COUNT(*) FROM business_settings")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO business_settings (tier) VALUES (?)", (db_tier,))
            conn.commit()
    finally:
        conn.close()


# ── Step 3: Seed admin user ───────────────────────────────────────────────────

def _seed_admin(db_path: Path, email: str, business_name: str) -> str:
    """Create admin User + MagicLinkToken. Returns the raw token string."""
    token      = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=72)).isoformat()

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    cur.execute("SELECT id FROM user WHERE email = ?", (email.lower(),))
    row = cur.fetchone()
    if row:
        user_id = row[0]
        cur.execute("UPDATE user SET is_admin = 1 WHERE id = ?", (user_id,))
    else:
        first_name     = _first_name(business_name)
        placeholder_pw = 'set-via-magic-link-' + secrets.token_hex(8)
        cur.execute(
            """INSERT INTO user
               (email, password_hash, first_name, last_name, is_admin, is_active, created_at)
               VALUES (?, ?, ?, '', 1, 1, ?)""",
            (email.lower(), placeholder_pw, first_name, datetime.utcnow().isoformat())
        )
        user_id = cur.lastrowid

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
    If token is None (resend flow), a fresh token is minted from the tenant DB.
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

    login_url = f"https://{slug}.sniffhq.app/auth/magic/{token}"
    first     = _first_name(business_name)

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

    msg            = MIMEMultipart()
    msg['From']    = FROM_EMAIL
    msg['To']      = email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(FROM_EMAIL, [email], msg.as_string())
    except Exception as e:
        raise ProvisionError(f"Welcome email failed: {e}")


# ── Step 5: Register Windows service via NSSM ────────────────────────────────

def _register_service(tenant_dir: Path, slug: str, port: int):
    """
    Install and start a Windows service for the tenant using NSSM.
    Uses python.exe directly with PYTHONPATH so imports resolve correctly.
    Idempotent — removes any stale service with the same name first.
    """
    svc    = f'SniffHQ_{slug}'
    python = SNIFFHQ_APP_DIR / 'venv' / 'Scripts' / 'python.exe'

    def _nssm(*args):
        return subprocess.run(
            [str(NSSM_EXE)] + list(args),
            capture_output=True, text=True
        )

    # Remove any stale service with this name (idempotent re-provision)
    status = _nssm('status', svc)
    if any(s in status.stdout for s in ('SERVICE_RUNNING', 'SERVICE_STOPPED', 'SERVICE_PAUSED')):
        _nssm('stop', svc)
        _nssm('remove', svc, 'confirm')

    steps = [
        ['install', svc, str(python)],
        ['set', svc, 'AppParameters',
         f'-m waitress --port={port} --threads=4 --call "app:create_app"'],
        ['set', svc, 'AppDirectory',        str(tenant_dir)],
        ['set', svc, 'AppEnvironmentExtra', f'PYTHONPATH={SNIFFHQ_APP_DIR}'],
        ['set', svc, 'DisplayName',         f'SniffHQ — {slug}'],
        ['set', svc, 'Description',         f'SniffHQ tenant app for {slug}.sniffhq.app'],
        ['set', svc, 'Start',               'SERVICE_AUTO_START'],
        ['start', svc],
    ]

    for step in steps:
        r = _nssm(*step)
        # 'start' failure is non-fatal — service may take a moment
        if r.returncode != 0 and step[0] != 'start':
            raise ProvisionError(
                f"NSSM {' '.join(step[:3])} failed: {(r.stderr or r.stdout).strip()}"
            )


# ── Step 6: Create IIS reverse-proxy site ────────────────────────────────────

def _create_iis_site(tenant_dir: Path, slug: str, port: int):
    """
    Create iis_root directory, write web.config reverse proxy rule,
    and register the IIS website bound to slug.sniffhq.app:80.
    """
    iis_root = tenant_dir / 'iis_root'
    iis_root.mkdir(exist_ok=True)

    # Build web.config — {R:1} must be escaped as {{R:1}} in an f-string
    web_config = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<configuration>\n'
        '    <system.webServer>\n'
        '        <rewrite>\n'
        '            <rules>\n'
        f'                <rule name="ReverseProxy_{slug}" stopProcessing="true">\n'
        '                    <match url="(.*)" />\n'
        f'                    <action type="Rewrite" url="http://127.0.0.1:{port}/{{R:1}}" />\n'
        '                </rule>\n'
        '            </rules>\n'
        '        </rewrite>\n'
        '    </system.webServer>\n'
        '</configuration>'
    )
    (iis_root / 'web.config').write_text(web_config, encoding='utf-8')

    ps = (
        'Import-Module WebAdministration; '
        f'New-Website -Name "{slug}" '
        f'-PhysicalPath "{iis_root}" '
        '-Port 80 '
        f'-HostHeader "{slug}.sniffhq.app" '
        '-Force'
    )
    r = subprocess.run(['powershell', '-Command', ps], capture_output=True, text=True)
    if r.returncode != 0:
        raise ProvisionError(f"IIS site creation failed: {(r.stderr or r.stdout).strip()}")


# ── Step 7: DNS A record via NameCheap API ────────────────────────────────────

def _create_dns_record(slug: str):
    """
    Add an A record slug.sniffhq.app → VPS_PUBLIC_IP via the NameCheap API.
    Fetches existing records first (setHosts replaces all), then appends new one.
    Skips silently if the record already exists.
    """
    if not all([NAMECHEAP_API_USER, NAMECHEAP_API_KEY, VPS_PUBLIC_IP]):
        raise ProvisionError(
            "NAMECHEAP_API_USER, NAMECHEAP_API_KEY, or VPS_PUBLIC_IP not set in .env."
        )

    base = {
        'ApiUser':  NAMECHEAP_API_USER,
        'ApiKey':   NAMECHEAP_API_KEY,
        'UserName': NAMECHEAP_API_USER,
        'ClientIp': VPS_PUBLIC_IP,
        'SLD': 'sniffhq',
        'TLD': 'app',
    }

    # Fetch existing records
    get_url = NAMECHEAP_API_URL + '?' + urllib.parse.urlencode(
        {**base, 'Command': 'namecheap.domains.dns.getHosts'}
    )
    with urllib.request.urlopen(get_url, timeout=15) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    if root.get('Status') != 'OK':
        errs = root.findall(f'.//{NAMECHEAP_NS}Error')
        raise ProvisionError('NameCheap getHosts: ' + '; '.join(e.text for e in errs))

    existing = root.findall(f'.//{NAMECHEAP_NS}host')

    # Skip if already exists
    for h in existing:
        if h.get('Name', '').lower() == slug.lower() and h.get('Type') == 'A':
            return

    # Build setHosts payload — preserve all existing records + add new one
    set_params = {**base, 'Command': 'namecheap.domains.dns.setHosts'}
    for i, h in enumerate(existing, start=1):
        set_params[f'HostName{i}']   = h.get('Name')
        set_params[f'RecordType{i}'] = h.get('Type')
        set_params[f'Address{i}']    = h.get('Address')
        set_params[f'TTL{i}']        = h.get('TTL', '1800')
        if h.get('Type') == 'MX':
            set_params[f'MXPref{i}'] = h.get('MXPref', '10')

    n = len(existing) + 1
    set_params[f'HostName{n}']   = slug
    set_params[f'RecordType{n}'] = 'A'
    set_params[f'Address{n}']    = VPS_PUBLIC_IP
    set_params[f'TTL{n}']        = '300'

    data = urllib.parse.urlencode(set_params).encode('utf-8')
    req  = urllib.request.Request(NAMECHEAP_API_URL, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=15) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    if root.get('Status') != 'OK':
        errs = root.findall(f'.//{NAMECHEAP_NS}Error')
        raise ProvisionError('NameCheap setHosts: ' + '; '.join(e.text for e in errs))


# ── SSL provisioning — called via platform UI after DNS propagates ────────────

def provision_ssl(slug: str) -> str:
    """
    Run win-acme to obtain an SSL cert for slug.sniffhq.app and bind it
    to the IIS site on port 443. Call this ~60s after provisioning to allow
    DNS propagation. Returns wacs stdout on success.
    """
    hostname = f'{slug}.sniffhq.app'

    # Look up IIS site ID
    ps = f'Import-Module WebAdministration; (Get-Website -Name "{slug}").id'
    r  = subprocess.run(['powershell', '-Command', ps], capture_output=True, text=True)
    site_id = r.stdout.strip()
    if not site_id:
        raise ProvisionError(
            f"IIS site '{slug}' not found. "
            "Ensure provisioning completed before activating SSL."
        )

    r = subprocess.run([
        str(WACS_EXE),
        '--target',             'manual',
        '--host',               hostname,
        '--validation',         'selfhosting',
        '--store',              'certificatestore',
        '--installation',       'iis',
        '--installationsiteid', site_id,
        '--accepttos',
        '--notaskscheduler',
    ], capture_output=True, text=True)

    if r.returncode != 0:
        raise ProvisionError(f"wacs failed:\n{r.stdout}\n{r.stderr}")

    return r.stdout
