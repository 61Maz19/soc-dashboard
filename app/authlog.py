"""Read SSH and sudo events from the auth log (read-only)."""
import os
import re
import logging
from collections import Counter, deque

log = logging.getLogger(__name__)
AUTH_LOG = os.environ.get("AUTH_LOG", "/var/log/auth.log")
MAX_LINES = 2000

# "SHA256:abc=laptop,SHA256:def=desktop" -> {"SHA256:abc": "laptop", ...}
KNOWN_KEYS = dict(
    item.strip().split("=", 1)
    for item in os.environ.get("KNOWN_KEYS", "").split(",")
    if "=" in item
)

# 2026-10-27T12:31:28.502388+03:00 myhost sshd-session[1234]: <message>
LINE = re.compile(r"^(\S+) (\S+) ([\w.-]+)(?:\[\d+\])?: (.*)$")

ACCEPTED = re.compile(r"^Accepted (\w+) for (\S+) from (\S+) port \d+ ssh2(?:: \S+ (\S+))?")
INVALID_USER = re.compile(r"^Invalid user (\S*) from (\S+)")
NOT_ALLOWED = re.compile(r"^User (\S+) from (\S+) not allowed")
SUDO_CMD = re.compile(r"^(\S+) : .*USER=(\S+) ; COMMAND=(\S+)")
SUDO_FAIL = re.compile(r"incorrect password attempt")


def clip(value, limit=64):
    """Limit attacker-controlled text before it reaches the page."""
    return value if len(value) <= limit else value[:limit] + "..."


def read_events():
    """Return (events, failures_by_ip), or None if the log cannot be read."""
    try:
        with open(AUTH_LOG, encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=MAX_LINES)
    except OSError as err:
        log.warning("Cannot read auth log %s: %s", AUTH_LOG, err)
        return None

    events = []
    failures = Counter()

    for raw in lines:
        line = LINE.match(raw.rstrip("\n"))
        if not line:
            continue
        timestamp, _host, program, message = line.groups()
        when = timestamp[:19].replace("T", " ")

        if program in ("sshd", "sshd-session"):
            if m := ACCEPTED.match(message):
                method, user, source, fingerprint = m.groups()
                device = KNOWN_KEYS.get(fingerprint)
                events.append({"time": when, "kind": "Login", "user": clip(user),
                               "source": clip(source),
                               "detail": device or f"UNKNOWN KEY ({method})",
                               "alert": device is None})
            elif m := INVALID_USER.match(message):
                user, source = m.groups()
                failures[clip(source)] += 1
                events.append({"time": when, "kind": "Invalid user", "user": clip(user),
                               "source": clip(source), "detail": "", "alert": True})
            elif m := NOT_ALLOWED.match(message):
                user, source = m.groups()
                failures[clip(source)] += 1
                events.append({"time": when, "kind": "User not allowed", "user": clip(user),
                               "source": clip(source), "detail": "", "alert": True})

        elif program == "sudo":
            if SUDO_FAIL.search(message):
                user = message.split(":", 1)[0].strip()
                events.append({"time": when, "kind": "sudo failed", "user": clip(user),
                               "source": "local", "detail": "wrong password",
                               "alert": True})
            elif m := SUDO_CMD.match(message):
                user, run_as, command = m.groups()
                events.append({"time": when, "kind": "sudo", "user": clip(user),
                               "source": "local", "detail": clip(f"{command} as {run_as}"),
                               "alert": False})
    events.reverse()
    return events[:50], failures.most_common(5)
