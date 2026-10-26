"""SOC Dashboard v1 - read-only server status page."""
import os
from datetime import datetime

import requests
from flask import Flask, render_template

app = Flask(__name__)

# Settings come from environment variables (.env), never hard-coded
DOCKER_API = os.environ.get("DOCKER_API", "http://socket-proxy:2375")
CHECK_URLS = [u.strip() for u in os.environ.get("CHECK_URLS", "").split(",") if u.strip()]
TIMEOUT = 3  # seconds


def get_containers():
    """Ask the Docker API (through the read-only proxy) for all containers."""
    try:
        resp = requests.get(f"{DOCKER_API}/containers/json",
                            params={"all": "true"}, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as err:
        app.logger.warning("Docker API error: %s", err)
        return [], f"Docker API unreachable: {err.__class__.__name__}"

    containers = []
    for c in resp.json():
        containers.append({
            "name": c["Names"][0].lstrip("/"),
            "image": c["Image"],
            "state": c["State"],
            "status": c["Status"],
        })
    containers.sort(key=lambda c: c["name"])
    return containers, None


def check_services():
    """Check that each URL answers, and how fast."""
    results = []
    for url in CHECK_URLS:
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            results.append({
                "url": url,
                "ok": resp.status_code < 500,
                "code": resp.status_code,
                "ms": int(resp.elapsed.total_seconds() * 1000),
            })
        except requests.RequestException as err:
            app.logger.warning("Health check failed for %s: %s", url, err)
            results.append({"url": url, "ok": False, "code": None,
                            "ms": None, "error": err.__class__.__name__})
    return results


@app.route("/")
def index():
    containers, error = get_containers()
    return render_template(
        "index.html",
        containers=containers,
        error=error,
        services=check_services(),
        updated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.route("/health")
def health():
    """Liveness check used by Docker: is the app itself running?"""
    return {"status": "ok"}