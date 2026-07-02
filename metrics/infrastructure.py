"""Server infrastructure metrics via psutil and NSSM."""
import subprocess, time
try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False


def get_system_metrics():
    if not PSUTIL_OK:
        return {"cpu": None, "memory": None, "disk": None, "uptime_hrs": None}
    cpu  = psutil.cpu_percent(interval=0.5)
    mem  = psutil.virtual_memory().percent
    disk = psutil.disk_usage("C:\\").percent
    boot = psutil.boot_time()
    uptime_hrs = round((time.time() - boot) / 3600, 1)
    return {"cpu": cpu, "memory": mem, "disk": disk, "uptime_hrs": uptime_hrs}


def get_service_status(service_name):
    """Check NSSM/Windows service status. Returns True if running."""
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True, text=True, timeout=5
        )
        return "RUNNING" in result.stdout
    except Exception:
        return None


def ping_app(base_url, timeout=3):
    """HTTP GET to base_url, return response time in ms or None."""
    try:
        import urllib.request, time
        start = time.time()
        req   = urllib.request.urlopen(base_url, timeout=timeout)
        ms    = int((time.time() - start) * 1000)
        return ms if req.status < 500 else None
    except Exception:
        return None
