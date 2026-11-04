FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --no-create-home --uid 10003 alerter \
 && mkdir /state && chown alerter /state

WORKDIR /app
COPY app/authlog.py alerter/alerter.py ./

USER alerter

# Healthy only while the state file is refreshed by a successful check
HEALTHCHECK --interval=60s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import os,sys,time; sys.exit(time.time() - os.path.getmtime('/state/sent.json') > 180)"

CMD ["python", "alerter.py"]
