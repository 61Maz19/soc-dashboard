# SOC Dashboard

A small read-only dashboard that shows Docker container status and basic service health checks.

## Security design
- Talks to Docker only through a socket proxy that allows read-only container listing (`POST: 0`)
- Runs as a non-root user, read-only filesystem, all Linux capabilities dropped
- Published on `127.0.0.1` only; access it through an SSH tunnel

## Run
```bash
cp .env.example .env   # adjust values
docker compose up -d --build
```
Then open http://127.0.0.1:8090