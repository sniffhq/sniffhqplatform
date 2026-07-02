"""Read metrics from monitored app SQLite databases (read-only)."""
import sqlite3
from datetime import datetime, timedelta, date


def _conn(db_path):
    """Open a read-only connection to a SQLite DB."""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True,
                               timeout=3, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _query(db_path, sql, params=()):
    conn = _conn(db_path)
    if not conn:
        return None
    try:
        cur = conn.execute(sql, params)
        return cur.fetchall()
    except Exception:
        return None
    finally:
        conn.close()


def _scalar(db_path, sql, params=(), default=0):
    rows = _query(db_path, sql, params)
    if rows and rows[0][0] is not None:
        return rows[0][0]
    return default


# ── Generic metrics (work for both SniffHQ and RuffLife) ──────────────────────

def get_customer_count(db_path):
    return _scalar(db_path, "SELECT COUNT(*) FROM user WHERE role='customer' AND is_active=1")


def get_new_customers_this_month(db_path):
    start = date.today().replace(day=1).isoformat()
    return _scalar(db_path,
        "SELECT COUNT(*) FROM user WHERE role='customer' AND created_at >= ?", (start,))


def get_active_boardings(db_path):
    return _scalar(db_path,
        "SELECT COUNT(*) FROM boarding WHERE status='active'")


def get_bookings_this_month(db_path):
    start = date.today().replace(day=1).isoformat()
    return _scalar(db_path,
        "SELECT COUNT(*) FROM boarding WHERE created_at >= ? OR check_in_date >= ?",
        (start, start))


def get_daycare_enrolled(db_path):
    return _scalar(db_path,
        "SELECT COUNT(*) FROM daycare_enrollment WHERE active=1")


def get_sms_today(db_path):
    today = date.today().isoformat()
    return _scalar(db_path,
        "SELECT COUNT(*) FROM sms_message WHERE direction='outbound' AND created_at >= ?",
        (today,))


def get_sms_this_month(db_path):
    start = date.today().replace(day=1).isoformat()
    return _scalar(db_path,
        "SELECT COUNT(*) FROM sms_message WHERE direction='outbound' AND created_at >= ?",
        (start,))


def get_sms_failures(db_path):
    """Count outbound SMS with no twilio_sid (failed before sending)."""
    return _scalar(db_path,
        "SELECT COUNT(*) FROM sms_message WHERE direction='outbound' AND twilio_sid IS NULL")


def get_open_support_tickets(db_path):
    try:
        return _scalar(db_path,
            "SELECT COUNT(*) FROM support_ticket WHERE status IN ('open','in_progress')")
    except Exception:
        return 0


def get_failed_logins_today(db_path):
    """Read from audit_log if available."""
    today = date.today().isoformat()
    try:
        return _scalar(db_path,
            "SELECT COUNT(*) FROM audit_log WHERE action='auth.login_failed' AND timestamp >= ?",
            (today,))
    except Exception:
        return 0


def get_waitlist_depth(db_path):
    try:
        return _scalar(db_path,
            "SELECT COUNT(*) FROM boarding_waitlist WHERE status='waiting'")
    except Exception:
        return 0


def get_recent_errors(db_path, hours=24):
    """Pull recent audit log entries for anomaly detection."""
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    try:
        rows = _query(db_path,
            "SELECT action, COUNT(*) as cnt FROM audit_log "
            "WHERE timestamp >= ? AND action LIKE '%.deleted' "
            "GROUP BY action ORDER BY cnt DESC LIMIT 10", (since,))
        return [{"action": r[0], "count": r[1]} for r in rows] if rows else []
    except Exception:
        return []


def get_revenue_this_month(db_path):
    start = date.today().replace(day=1).isoformat()
    try:
        val = _scalar(db_path,
            "SELECT SUM(amount) FROM payment WHERE status='paid' AND payment_date >= ?",
            (start,), default=0)
        return float(val) if val else 0.0
    except Exception:
        return 0.0


def get_all_metrics(db_path):
    """Collect all app-level metrics in one call."""
    return {
        "customers":          get_customer_count(db_path),
        "new_customers":      get_new_customers_this_month(db_path),
        "active_boardings":   get_active_boardings(db_path),
        "bookings_month":     get_bookings_this_month(db_path),
        "daycare_enrolled":   get_daycare_enrolled(db_path),
        "sms_today":          get_sms_today(db_path),
        "sms_month":          get_sms_this_month(db_path),
        "sms_failures":       get_sms_failures(db_path),
        "open_tickets":       get_open_support_tickets(db_path),
        "failed_logins":      get_failed_logins_today(db_path),
        "waitlist_depth":     get_waitlist_depth(db_path),
        "revenue_month":      get_revenue_this_month(db_path),
        "recent_errors":      get_recent_errors(db_path),
    }
