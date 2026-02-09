FROM python:3.12-slim

LABEL maintainer="NewznabRewritarr"
LABEL description="Newznab attribute title rewrite proxy for Prowlarr/*arr stack"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY newznab_rewritarr.py .

# Default proxy port
EXPOSE 5008

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.create_connection(('localhost', ${PROXY_PORT:-5008}), timeout=2); s.close()" || exit 1

ENTRYPOINT ["python", "-u", "newznab_rewritarr.py"]
