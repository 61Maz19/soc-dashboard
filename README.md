# SOC Dashboard

A small, read-only security dashboard for a single Docker host, built with a
security-first design. It shows container health, SSH and sudo activity from
`auth.log`, and backup freshness on one page, and includes a send-only
Telegram alerting pipeline: new security events reach the owner's phone
within about a minute.

It is a learning project: every feature was added with its threat model,
tested from the attacker's side, and its limits documented below.

## Features

- **Containers**: name, state, status and image, read through a read-only
  Docker API proxy. Unhealthy containers are highlighted in red.
- **Service checks** (optional): HTTP status and response time for URLs in
  `CHECK_URLS`.
- **Authentication events** from `/var/log/auth.log`:
  - SSH logins, with the key fingerprint mapped to a known device name.
    Logins with an unknown key are shown in red.
  - Invalid and not-allowed users, with a count per source address
  - sudo commands (program name only, never arguments)
  - sudo authentication failures (from PAM, works with sudo-rs)
- **Backups**: time, file and size of the last successful backup.
  Red when older than 26 hours.
- **Alerter**: checks the auth log and backup status every minute and sends
  each new alert once. It remembers what it sent across restarts, holds an
  alert until the notifier accepts it, summarizes bursts (more than 3 new
  alerts) in one message, and reports a stale backup once, not every minute.
- **Notifier**: forwards alerts from the internal network to Telegram.
  Send-only: it never reads incoming messages.

## Architecture

```
                  +-------------------+     socket network (internal)
 auth.log (ro) -->|                   |---------------> socket-proxy --> Docker API
 backup status -->|     dashboard     |                 (GET only)
   (ro)           |  (no internet)    |
                  +-------------------+
                       127.0.0.1:8090 (SSH tunnel only)

                  +-------------------+  alerts network  +-------------------+
 auth.log (ro) -->|      alerter      |----------------->|     notifier      |---> Telegram API
 backup status -->| (no internet,     |   (internal)     | (sees no logs,    |    (TCP 443 only)
   (ro)           |  no token)        |                  |  holds the token) |
                  +-------------------+                  +-------------------+
```

## Security design

| Layer | What it does |
| --- | --- |
| Least privilege | Dashboard reads only `auth.log` and the backup status directory, both read-only. Docker access goes through a proxy that allows GET requests only. |
| Container hardening | Non-root users, read-only filesystems, all capabilities dropped, `no-new-privileges`, memory limits. |
| Separation of duties | The dashboard and the alerter see logs but have no internet. The notifier has internet but sees no logs. The bot token lives only in the notifier. |
| Egress control | Host firewall rules (`DOCKER-USER`) log and drop all outbound connections from the dashboard network, and everything except TCP 443 from the notifier network. |
| No exposed ports | The dashboard listens on 127.0.0.1 and is reached through an SSH tunnel. The alerter and the notifier publish no ports. |
| Output encoding | All values are escaped by Jinja autoescaping. Long values are clipped. |
| Response headers | Content-Security-Policy, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| Data minimization | sudo events show the program name only. Alerts carry the event type, user and time, not addresses or fingerprints. |
| Alert safety | Notifier sends plain text only, defangs URLs and domains (`hxxp://evil[.]example`) and disables link previews, so attacker-controlled text cannot become a clickable link. The token is never logged. |
| Reliable alerting | An alert is marked as sent only after the notifier accepts it. State is written atomically. The alerter healthcheck turns red if checks stop running. |
| Supply chain | The alerter and the notifier use the Python standard library only. Base images are pinned by digest at build time. CodeQL, Dependabot and secret scanning with push protection are enabled. |
| Commit hygiene | A pre-commit hook rejects non-ASCII characters and internal patterns before anything is committed. |

## Requirements

- Linux host with Docker Engine and the Compose plugin
- `iptables` for the egress rules
- A user in the `adm` group can read `/var/log/auth.log` (default on Ubuntu)

## Setup

1. Clone the repository and create the local configuration files:

   ```bash
   cp .env.example .env
   cp notifier.env.example notifier.env
   chmod 600 .env notifier.env
   ```

2. Add your SSH key fingerprints to `KNOWN_KEYS` in `.env`:

   ```bash
   ssh-keygen -lf ~/.ssh/id_ed25519.pub
   ```

   Format: `SHA256:<fingerprint>=<device-name>`, comma separated.

3. Create a `compose.override.yml` for host-specific settings (it is
   gitignored). Example:

   ```yaml
   services:
     dashboard:
       group_add:
         - "4"   # adm, to read auth.log
       volumes:
         - /var/log/auth.log:/var/log/auth.log:ro
         - /var/lib/srv-backup:/run/backup-status:ro
     alerter:
       group_add:
         - "4"
       environment:
         ALERT_HOST: my-server
       volumes:
         - /var/log/auth.log:/var/log/auth.log:ro
         - /var/lib/srv-backup:/run/backup-status:ro

   networks:
     default:
       ipam:
         config:
           - subnet: 172.30.0.0/24
   ```

4. Add the egress rules on the host (make them persistent with a systemd
   unit that runs after Docker):

   ```bash
   iptables -A DOCKER-USER -s 172.30.0.0/24 ! -d 172.30.0.0/24 -m conntrack --ctstate NEW -j DROP
   iptables -A DOCKER-USER -s 172.31.0.0/24 ! -d 172.31.0.0/24 -p tcp --dport 443 -m conntrack --ctstate NEW -j RETURN
   iptables -A DOCKER-USER -s 172.31.0.0/24 ! -d 172.31.0.0/24 -m conntrack --ctstate NEW -j DROP
   ```

5. Start the stack:

   ```bash
   docker compose up -d --build
   ```

6. Open the dashboard through an SSH tunnel:

   ```bash
   ssh -L 127.0.0.1:8091:127.0.0.1:8090 your-server
   ```

   Then browse to `http://127.0.0.1:8091`.

## Configuration

| Variable | File | Purpose |
| --- | --- | --- |
| `TZ` | `.env` | Time zone for displayed times |
| `KNOWN_KEYS` | `.env` | Known SSH key fingerprints and device names |
| `CHECK_URLS` | `.env` | Optional, comma-separated URLs to check |
| `BACKUP_STATUS_FILE` | `.env` | Path of the backup status file inside the container |
| `BACKUP_MAX_AGE_HOURS` | `.env` | Age after which the backup turns red (default 26) |
| `ALERT_HOST` | override | Server name shown in alert messages (default `server`) |
| `ALERT_INTERVAL` | override | Seconds between alerter checks (default 60) |
| `TELEGRAM_TOKEN` | `notifier.env` | Bot token, read only by the notifier |
| `TELEGRAM_CHAT_ID` | `notifier.env` | Chat that receives alerts |

The backup status file is one line written by the backup script after a
successful backup: `<ISO time> <file name> <size>`.

## Known limitations

- Notifier egress is limited by port, not destination: HTTPS to any host is
  possible. Accepted for now because the notifier sees no logs and the token
  can be revoked at any time.
- The egress rules cover IPv4 only, and DNS through Docker's embedded
  resolver is not filtered.
- The dashboard classifies events on every page load and keeps no state.
  Adding a fingerprint to `KNOWN_KEYS` turns earlier red events normal.
  The alerter's record of sent alerts is the history of what was reported.
- On its very first run the alerter treats existing events as history and
  does not report them.
- Events are read from the current `auth.log` only, not from rotated files.

## Development

Install the pre-commit hook once after cloning:

```bash
ln -s ../../scripts/precommit-check.sh .git/hooks/pre-commit
```

`tests/` contains a sample `auth.log` with normal and attack lines for local
testing. Mount it instead of the real log in your local override.

## Roadmap

- [x] `alerter`: detect new events every minute, remember what was sent,
      aggregate bursts, and forward to the notifier
- [x] Branch protection on `main`
- [ ] Destination allowlist for notifier egress

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.
