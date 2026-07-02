"""
collector.py — SniffHQ Platform monitoring collector
Runs every 5 minutes via Windows Task Scheduler.

Queries all active tenants from platform.db, collects metrics,
writes Snapshot rows, and fires email alerts on threshold breaches.

Task Scheduler setup (run once as admin):
    schtasks /create /tn "SniffHQ-Collector" /tr "python C:\SniffHQ\platform\collector.py" ^
             /sc minute /mo 5 /ru SYSTEM /f
"""

import os
import sys
import smtplib
import sqlite3
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from dotenv import load_dotenv

# ── Bootstrap: add platform dir to path so we can import metrics modules ──────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

load_dotenv(os.path.join(SCRIPT_DIR, '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [collector] %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(SCRIPT_DIR, 'logs', 'collector.log'), encoding='utf-8'),
    ]
)
log = logging.getLogger(__name__)

# ── Platform DB (read tenants + alert configs, write snapshots) ───────────────

PLATFORM_DB = os.path.join(SCRIPT_DIR, 'instance', 'platform.db')
TENANTS_DIR = os.environ.get('TENANTS_DIR', r'C:\SniffHQ\tenants')

# Rate-limit: don't alert same metric more than once per hour
_last_alert: dict = {}   # key=(app_id, metric) -> last alert datetime


def _get_db():
    conn = sqlite3.connect(PLATFORM_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_active_tenants(conn):
    return conn.execute(
        "SELECT * FROM tenant WHERE status='active' AND port IS NOT NULL"
    ).fetchall()


def get_alert_configs(conn):
    rows = conn.execute("SELECT * FROM alert_config WHERE enabled=1").fetchall()
    return {r['metric']: dict(r) for r in rows}


def insert_snapshot(conn, app_id, data):
    conn.execute(
        """INSERT INTO snapshot
           (app_id, ts, cpu_pct, mem_pct, disk_pct, svc_up, resp_ms,
            error_cnt, sms_sent, bookings, logins)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            app_id,
            datetime.utcnow(),
            data.get('cpu_pct'),
            data.get('mem_pct'),
            data.get('disk_pct'),
            data.get('svc_up'),
            data.get('resp_ms'),
            data.get('error_cnt'),
            data.get('sms_today'),
            data.get('active_boardings'),
            data.get('failed_logins'),
        )
    )
    conn.commit()


# ── Metric collection ─────────────────────────────────────────────────────────

def collect_tenant(tenant) -> dict:
    from metrics.infrastructure import get_system_metrics, get_service_status, ping_app
    from metrics.application    import get_all_metrics
    from metrics.logs           import get_error_count

    slug    = tenant['slug']
    svc_key = f'SniffHQ_{slug}'
    base_url = f"http://localhost:{tenant['port']}"
    db_path  = os.path.join(TENANTS_DIR, slug, 'instance', 'sniffhq.db')
    log_path = os.path.join(TENANTS_DIR, slug, 'logs', 'app.log')

    sys_m   = get_system_metrics()
    svc_up  = get_service_status(svc_key)
    resp_ms = ping_app(base_url) if svc_up else None
    metrics = get_all_metrics(db_path)
    errs    = get_error_count(log_path)

    return {
        'cpu_pct':         sys_m.get('cpu'),
        'mem_pct':         sys_m.get('memory'),
        'disk_pct':        sys_m.get('disk'),
        'svc_up':          svc_up,
        'resp_ms':         resp_ms,
        'error_cnt':       errs,
        'sms_today':       metrics.get('sms_today', 0),
        'sms_failures':    metrics.get('sms_failures', 0),
        'active_boardings':metrics.get('active_boardings', 0),
        'failed_logins':   metrics.get('failed_logins', 0),
        'customers':       metrics.get('customers', 0),
    }


# ── Alerting ──────────────────────────────────────────────────────────────────

ALERT_CHECKS = {
    'cpu':           lambda d: d.get('cpu_pct'),
    'memory':        lambda d: d.get('mem_pct'),
    'disk':          lambda d: d.get('disk_pct'),
    'error_spike':   lambda d: d.get('error_cnt'),
    'service_down':  lambda d: 1 if not d.get('svc_up') else 0,
    'sms_failures':  lambda d: d.get('sms_failures'),
    'failed_logins': lambda d: d.get('failed_logins'),
}


def _should_alert(app_id, metric) -> bool:
    key = (app_id, metric)
    last = _last_alert.get(key)
    if last and (datetime.now() - last) < timedelta(hours=1):
        return False
    _last_alert[key] = datetime.now()
    return True


def send_alert(app_name, metric_label, value, threshold, notify_email):
    try:
        mail_server   = os.environ.get('MAIL_SERVER',   'smtp.zoho.com')
        mail_port     = int(os.environ.get('MAIL_PORT', '587'))
        mail_username = os.environ.get('MAIL_USERNAME', '')
        mail_password = os.environ.get('MAIL_PASSWORD', '')
        admin_email   = os.environ.get('ADMIN_EMAIL',   'charles.brown@sniffhq.com')

        to_addr = notify_email or admin_email
        subject = f'[SniffHQ Alert] {app_name}: {metric_label} threshold breached'
        body = (
            f'SniffHQ Platform Alert\n'
            f'{"="*40}\n\n'
            f'Tenant:    {app_name}\n'
            f'Metric:    {metric_label}\n'
            f'Value:     {value}\n'
            f'Threshold: {threshold}\n'
            f'Time:      {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n'
            f'Log in to https://admin.sniffhq.app/monitoring to investigate.\n'
        )
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From']    = mail_username or admin_email
        msg['To']      = to_addr

        with smtplib.SMTP(mail_server, mail_port) as smtp:
            smtp.starttls()
            smtp.login(mail_username, mail_password)
            smtp.send_message(msg)
        log.info(f'Alert sent to {to_addr}: {subject}')
    except Exception as e:
        log.error(f'Failed to send alert email: {e}')


def check_alerts(app_id, app_name, data, alert_configs):
    for metric_key, extractor in ALERT_CHECKS.items():
        ac = alert_configs.get(metric_key)
        if not ac:
            continue
        value = extractor(data)
        if value is None:
            continue
        threshold = ac.get('threshold', 0)
        if value >= threshold and _should_alert(app_id, metric_key):
            label = metric_key.replace('_', ' ').title()
            log.warning(f'ALERT {app_name}: {label} = {value} >= {threshold}')
            send_alert(app_name, label, value, threshold, ac.get('notify_email'))


# ── Purge old snapshots (keep 7 days) ─────────────────────────────────────────

def purge_old_snapshots(conn):
    cutoff = datetime.utcnow() - timedelta(days=7)
    conn.execute("DELETE FROM snapshot WHERE ts < ?", (cutoff,))
    conn.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info('Collector run starting')
    os.makedirs(os.path.join(SCRIPT_DIR, 'logs'), exist_ok=True)

    conn = _get_db()
    try:
        tenants       = get_active_tenants(conn)
        alert_configs = get_alert_configs(conn)
        log.info(f'Found {len(tenants)} active tenant(s), {len(alert_configs)} alert rule(s) enabled')

        for t in tenants:
            slug = t['slug']
            name = t['business_name']
            log.info(f'Collecting: {name} ({slug})')
            try:
                data = collect_tenant(t)
                insert_snapshot(conn, slug, data)
                check_alerts(slug, name, data, alert_configs)
                log.info(
                    f'  {name}: svc={data["svc_up"]} resp={data["resp_ms"]}ms '
                    f'errs={data["error_cnt"]} sms_fail={data["sms_failures"]}'
                )
            except Exception as e:
                log.error(f'  Error collecting {name}: {e}')

        purge_old_snapshots(conn)
        log.info('Collector run complete')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
