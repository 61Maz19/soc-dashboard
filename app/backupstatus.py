"""Read the last successful backup status written by srv-backup.sh."""
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

STATUS_FILE = os.environ.get("BACKUP_STATUS_FILE", "/run/backup-status/last-success")
MAX_AGE_HOURS = float(os.environ.get("BACKUP_MAX_AGE_HOURS", "26"))


def read_backup_status():
    """Return a dict about the last backup, or None if not configured."""
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            parts = f.read().split()
    except OSError as err:
        log.warning("Cannot read backup status %s: %s", STATUS_FILE, err)
        return None

    try:
        when = datetime.fromisoformat(parts[0])
        name, size = parts[1], parts[2]
    except (IndexError, ValueError):
        return {"error": "Backup status file is unreadable"}

    age_hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    return {
        "ok": age_hours <= MAX_AGE_HOURS,
        "time": when.strftime("%Y-%m-%d %H:%M"),
        "age_hours": round(age_hours, 1),
        "file": name[:80],
        "size": size[:16],
    }
