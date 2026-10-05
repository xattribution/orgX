# ORGX — stdlib Python + SQLite (FTS5) + static web. No pip installs.
FROM python:3.12-slim
WORKDIR /app
COPY orgx ./orgx
COPY web ./web
COPY tools ./tools
COPY data/centroids.json ./data/
COPY server.py ingest.py ./
ENV ORGX_HOST=0.0.0.0 \
    ORGX_PORT=48750 \
    ORGX_DATA=/data \
    ORGX_INBOX_SECONDS=20 \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 48750
HEALTHCHECK --interval=30s --timeout=4s --retries=3 \
  CMD python3 -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"ORGX_PORT\"]}/api/job', timeout=3)"
CMD ["python3", "server.py"]
