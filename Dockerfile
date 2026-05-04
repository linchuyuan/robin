FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_SERVER_MODE=1 \
    MCP_TRANSPORT=streamable-http \
    HOST=127.0.0.1 \
    PORT=8000 \
    MCP_PATH=/messages

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

COPY . /app
RUN useradd --create-home --shell /usr/sbin/nologin robin \
    && chown -R robin:robin /app
USER robin

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import os,socket; s=socket.create_connection((os.getenv('HOST','127.0.0.1'), int(os.getenv('PORT','8000'))), 3); s.close()"

CMD ["sh", "-c", "python server.py --transport=${MCP_TRANSPORT} --host=${HOST} --port=${PORT} --path=${MCP_PATH}"]
