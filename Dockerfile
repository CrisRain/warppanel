# ============================================================
# WarpPanel Dockerfile — multi-stage, layer-optimized build
# ============================================================

# --------------- ARGs (pinned versions) ---------------
ARG NODE_VERSION=20
ARG UBUNTU_VERSION=22.04
ARG ALPINE_VERSION=3.21

# ============================================================
# Stage 1: Download external binaries
# ============================================================
FROM alpine:${ALPINE_VERSION} AS downloader
WORKDIR /tmp
RUN apk add --no-cache curl unzip jq

# Download usque (WARP MASQUE client) — auto-detect latest release
RUN USQUE_VERSION=$(curl -fsSL https://api.github.com/repos/Diniboy1123/usque/releases/latest | jq -r '.tag_name' | sed 's/^v//') \
    && echo "Detected usque version: ${USQUE_VERSION}" \
    && curl -fSL -o usque.zip \
    "https://github.com/Diniboy1123/usque/releases/download/v${USQUE_VERSION}/usque_${USQUE_VERSION}_linux_amd64.zip" \
    && unzip usque.zip \
    && chmod +x usque \
    && rm -f usque.zip

# ============================================================
# Stage 2: Build Frontend
# ============================================================
FROM node:${NODE_VERSION}-alpine AS frontend-build
WORKDIR /build

# Install deps first (layer cache for package.json changes only)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline 2>/dev/null || npm install

# Then copy source & build
COPY frontend/ .
RUN npm run build

# ============================================================
# Stage 3: Final runtime image
# ============================================================
FROM ubuntu:${UBUNTU_VERSION}

LABEL org.opencontainers.image.title="WarpPanel" \
    org.opencontainers.image.description="Cloudflare WARP management panel with proxy support" \
    org.opencontainers.image.source="https://github.com/CrisRain/warppanel"

# ---- System dependencies (single RUN to minimize layers) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gpg lsb-release ca-certificates dbus \
    python3 python3-pip \
    socat iputils-ping iproute2 iptables procps supervisor \
    # Install Cloudflare WARP official client
    && curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
    | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/cloudflare-client.list \
    && apt-get update && apt-get install -y --no-install-recommends cloudflare-warp \
    # Cleanup
    && apt-get purge -y --auto-remove gpg lsb-release \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ---- Copy external binaries ----
COPY --from=downloader /tmp/usque /usr/local/bin/usque

# ---- Python app setup ----
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    WARP_DATA_DIR=/app/data \
    SOCKS5_PORT=1080 \
    PANEL_PORT=8000

# Install Python deps (separate layer for caching)
COPY backend/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# ---- Create runtime directories ----
RUN mkdir -p /app/data/kernels /var/lib/warp /var/log/supervisor

# ---- Supervisor config (rarely changes) ----
COPY backend/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# ---- Entrypoint (rarely changes) ----
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# ---- Application code (changes most often → last) ----
COPY backend/app /app/app
COPY --from=frontend-build /build/dist /app/static

# ---- Ports ----
# 8000: Web UI + API (default, configurable via PANEL_PORT)
# 1080: SOCKS5 Proxy (default, configurable via SOCKS5_PORT)
EXPOSE 8000 1080

# ---- Health check ----
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PANEL_PORT:-8000}/api/status || exit 1

CMD ["/app/entrypoint.sh"]
