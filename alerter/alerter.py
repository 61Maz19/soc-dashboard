"""Watch auth.log and backup status, send each new alert once to the notifier.

Runs on the internal alerts network only: no internet, no bot token.
"""
import hashlib
import json
import logging
import os
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from authlog import read_events

NOTIFY_URL = os.environ.get("NOTIFY_URL", "http://soc-notifier:8080/notify")
STATE_FILE = os.environ.get("STATE_FILE", "/state/sent.json")
STATUS_FILE = os.environ.get("BACKUP_STATUS_FILE", "/run/backup-status/last-success")
MAX_AGE_HOURS = float(os.environ.get("BACKUP_MAX_AGE_HOURS", "26"))
INTERVAL = int(os.environ.get("ALERT_INTERVAL", "60"))
HOST = os.environ.get("ALERT_HOST", "server")[:32]
BURST = 3  # more new alerts than this in one check -> one summary message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alerter")


def event_key(event):
    """Stable fingerprint of one event, so it is sent only once."""
    raw = "|".join(event[k] for k in ("time", "kind", "user", "source", "detail"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def label(event):
    return "SSH login with UNKNOWN key" if event["kind"] == "Login" else event["kind"]


def describe(event):
    who = f" (user: {event['user']})" if event["user"] else ""
    return f"{label(event)}{who} at {event['time']}"


def load_state():
    """Return the set of sent keys, or None on the very first run."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f)["sent"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as err:
        log.error("State file unreadable (%s), treating as first run", err.__class__.__name__)
        return None


def save_state(sent):
    """Write atomically: a crash never leaves a half-written state file."""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"sent": sorted(sent)}, f)
    os.replace(tmp, STATE_FILE)


def notify(text):
    """True only if the notifier accepted the alert (HTTP 202)."""
    req = urllib.request.Request(NOTIFY_URL, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status == 202
    except OSError as err:
        log.warning("Notifier did not accept the alert: %s", err.__class__.__name__)
        return False


def backup_problem():
    """Return (key, text) while the backup is stale or unreadable, else None."""
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            line = f.read().strip()
        when = datetime.fromisoformat(line.split()[0])
    except (OSError, IndexError, ValueError):
        return "backup:unreadable", "Backup status missing or unreadable"
    age = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if age > MAX_AGE_HOURS:
        return "backup:" + line.split()[0], f"Last successful backup is {age:.0f} h old"
    return None


def check(sent):
    result = read_events()
    events = [e for e in reversed(result[0]) if e["alert"]] if result else []  # oldest first
    current = {event_key(e) for e in events}
    backup = backup_problem()
    if backup:
        current.add(backup[0])

    if sent is None:
        log.info("First run: %d existing alerts marked as history", len(current))
        notify(f"{HOST}: alerter started ({len(current)} existing alerts skipped)")
        return current

    new = [e for e in events if event_key(e) not in sent]
    if len(new) > BURST:
        counts = Counter(label(e) for e in new)
        summary = ", ".join(f"{n} x {kind}" for kind, n in counts.most_common())
        if notify(f"{HOST}: {len(new)} new alerts: {summary}. Open the dashboard."):
            sent.update(event_key(e) for e in new)
    else:
        for e in new:
            if not notify(f"{HOST}: {describe(e)}. Open the dashboard."):
                break  # notifier down: keep the rest for the next check, in order
            sent.add(event_key(e))

    if backup and backup[0] not in sent:
        if notify(f"{HOST}: {backup[1]}. Check the backup timer."):
            sent.add(backup[0])

    if new:
        log.info("Checked: %d new alerts", len(new))
    # Forget what left the log window: it can never come back, so the file stays small
    return sent & current


def main():
    sent = load_state()
    while True:
        try:
            sent = check(sent)
            save_state(sent)
        except Exception:  # keep watching; the healthcheck turns red if this repeats
            log.exception("Check failed")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
