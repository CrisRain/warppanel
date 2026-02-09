# Stage 1a: Download usque (WARP MASQUE client)
FROM alpine:latest AS usque-download
WORKDIR /tmp
RUN apk add --no-cache curl unzip
RUN curl -L -o usque.zip https://github.com/Diniboy1123/usque/releases/download/v1.4.2/usque_1.4.2_linux_amd64.zip \
    && unzip usque.zip \
    && chmod +x usque

# Stage 1b: Download gost (multi-protocol proxy)
FROM alpine:latest AS gost-download
WORKDIR /tmp
RUN apk add --no-cache curl tar
RUN curl -L -o gost.tar.gz https://github.com/ginuerzh/gost/releases/download/v2.12.0/gost_2.12.0_linux_amd64.tar.gz \
    && tar xzf gost.tar.gz \
    && chmod +x gost

# Stage 2: Build Frontend
FROM node:20-alpine AS frontend-build
WORKDIR /frontend_app
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
# Ensure we build for production
RUN npm run build

# Stage 3: Final Monolithic Image
FROM ubuntu:22.04

# Install basic deps + python + warp deps + networking tools + supervisor
RUN apt-get update && apt-get install -y \
    curl gpg lsb-release ca-certificates dbus \
    python3 python3-pip socat \
    iputils-ping iproute2 iptables procps supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Cloudflare Warp (official client - kept for fallback)
RUN curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflare-client.list \
    && apt-get update && apt-get install -y cloudflare-warp

# Copy usque binary from download stage
COPY --from=usque-download /tmp/usque /usr/local/bin/usque

# Copy gost binary from download stage
COPY --from=gost-download /tmp/gost /usr/local/bin/gost

# Setup Python App
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY controller-app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
RUN pip3 install uvicorn psutil

# Copy Backend Code
COPY controller-app/app /app/app
# Copy Frontend Build
COPY --from=frontend-build /frontend_app/dist /app/static

# Supervisor Configuration
COPY controller-app/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Ports
# 8000: Web UI + API
# 1080: SOCKS5 Proxy
# 8080: HTTP Proxy
EXPOSE 8000 1080 8080

# Copy entrypoint
COPY controller-app/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Use entrypoint to start init
CMD ["/app/entrypoint.sh"]
