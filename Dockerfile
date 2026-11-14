# Senora as a hosted page. The heavy video rendering is NOT done here (see docs/cloud.md); this serves the page, keeps playlists and
# receives the songs your own computer fetches (start_senora helper <this address>).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY engine engine
COPY server server
COPY samples samples
ENV SENORA_MODE=cloud SENORA_DATA=/data
VOLUME /data
EXPOSE 8001
# SENORA_PASSWORD must be set on the host, otherwise the page refuses to show anything
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8001}"]
