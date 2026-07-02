"""Parse Flask log files for errors and slow responses."""
import re
from pathlib import Path
from datetime import datetime, timedelta


ERROR_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*(ERROR|500|Exception)")
SLOW_RE  = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*GET|POST.*(\d+)ms")


def get_error_count(log_path, hours=24):
    """Count ERROR lines in the log file within the last N hours."""
    p = Path(log_path)
    if not p.exists():
        return 0
    cutoff = datetime.now() - timedelta(hours=hours)
    count  = 0
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = ERROR_RE.search(line)
                if m:
                    try:
                        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                        if ts >= cutoff:
                            count += 1
                    except Exception:
                        count += 1
    except Exception:
        pass
    return count


def get_recent_error_lines(log_path, limit=20):
    """Return the most recent ERROR lines from the log."""
    p = Path(log_path)
    if not p.exists():
        return []
    lines = []
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "ERROR" in line or "Exception" in line or " 500 " in line:
                    lines.append(line.strip())
        return lines[-limit:]
    except Exception:
        return []
