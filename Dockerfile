FROM node:20-bookworm-slim AS widget
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY scripts ./scripts
COPY widget-src ./widget-src
RUN npm run build:widget

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=3941 \
    MUSIC_STATE_PATH=/data/music_state.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py music_state.py ./
COPY --from=widget /src/dist ./dist
RUN useradd --create-home --uid 10001 music && mkdir -p /data && chown music:music /data
USER music
VOLUME ["/data"]
EXPOSE 3941
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3941/health', timeout=3)"
CMD ["python", "server.py"]
