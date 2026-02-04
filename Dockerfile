# Stage 1: Download usque (WARP MASQUE client)
FROM alpine:latest AS usque-download
WORKDIR /tmp
RUN apk add --no-cache curl unzip
RUN curl -L -o usque.zip https://github.com/Diniboy1123/usque/releases/download/v1.4.2/usque_1.4.2_linux_amd64.zip \
    && unzip usque.zip \
    && chmod +x usque

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

# Install basic deps + python + warp deps + networking tools
RUN apt-get update && apt-get install -y \
    curl gpg lsb-release ca-certificates dbus \
    python3 python3-pip socat supervisor \
    iputils-ping iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install Cloudflare Warp (official client - kept for fallback)
RUN curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflare-client.list \
    && apt-get update && apt-get install -y cloudflare-warp

# Copy usque binary from download stage
COPY --from=usque-download /tmp/usque /usr/local/bin/usque

# Setup Python App
WORKDIR /app
COPY controller-app/requirements.txt .
# Remove docker from requirements if present, or just install what we need. 
# We'll install manually to be safe/clean or rely on updated requirements.txt. 
# Better to update requirements.txt first.
RUN pip3 install --no-cache-dir -r requirements.txt
# Install uvicorn explicitly if not in requirements
RUN pip3 install uvicorn

# Copy Backend Code
COPY controller-app/app /app/app
# Copy Frontend Build
COPY --from=frontend-build /frontend_app/dist /app/static

# Configs
COPY controller-app/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
# Ports
# 8000: Web UI + API (FastAPI serves static files now)
# 1080: SOCKS5 Proxy
EXPOSE 8000 1080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
