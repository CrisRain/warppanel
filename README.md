<div align="center">

# WarpPanel

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/crisocean/warppanel?style=flat-square&logo=docker)](https://hub.docker.com/r/crisocean/warppanel)
[![Vue 3](https://img.shields.io/badge/Frontend-Vue_3-4FC08D?style=flat-square&logo=vue.js)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)

**Modern Cloudflare WARP Management Panel**

[Features](#-features) • [Tech Stack](#-tech-stack) • [Quick Start](#-quick-start) • [Usage](#-usage) • [Linux Native](#-linux-native-deployment)

---

![WarpPanel UI](resources/WarpPanel-02-02-2026_09_48_PM.png)

</div>

**WarpPanel** is a modern Web control panel designed for managing Cloudflare WARP clients. With a stunning **Glassmorphism** interface, it offers seamless switching between **Official** and **usque** engines, helping you easily control your network connection.

## ✨ Features

- **🎯 Precise Single-Instance Management**
  Control the WARP container with precision. Real-time status synchronization and low resource usage, perfect for VPS or local deployment.

- **🔄 Dual Backend Architecture**
  - **`usque` (MASQUE)**: High-performance, lightweight Go implementation. Extremely fast and resource-efficient (**Recommended**).
  - **`official`**: Cloudflare's official Linux client for maximum compatibility.
  - **Seamless Switching**: Switch backends instantly without restarting the container.

- **🌐 SOCKS5 Proxy Mode**
  Works as a SOCKS5 proxy. External applications can route traffic through WARP via the proxy port (`:1080`).

- **🔧 MASQUE Protocol Support**
  Modern HTTP/3 tunnel protocol for better resistance to interference and faster speeds.

- **⚡ Performance & Responsiveness**
  - **Non-blocking Architecture**: Backend operations are asynchronous, ensuring the UI remains responsive.
  - **Real-time Monitoring**: WebSocket-based status updates.
  - **Smart Caching**: Efficient caching of IP and status information to minimize overhead.

- **🎨 Immersive UI**
  Built with Vue 3 + Tailwind CSS v4. Fully responsive with smooth transitions.

- **🛡️ Security & Intelligence**
  - **Secure Proxy**: SOCKS5 port binds to `127.0.0.1` by default to prevent unauthorized external access.
  - **Clean Logs**: Intelligent filtering of verbose connection logs.
  - **Custom Endpoints**: Support for specifying custom IP:PORT endpoints.
  - **Kernel Management**: Auto-update and version management for the `usque` kernel.
  - **Password Protection**: Optional web panel authentication.

## 🛠️ Tech Stack

| Module | Tech | Description |
| :--- | :--- | :--- |
| **Frontend** | Vue 3, Vite, Tailwind CSS v4 | Atomic CSS, rapid development |
| **Backend** | Python 3.10+, FastAPI, AsyncIO | High-performance async Web framework |
| **Core** | Cloudflare WARP Official + usque | Official stability + Community performance |
| **Deploy** | Docker / Linux Native | Containerized or direct installation |

## 🚀 Quick Start

### Prerequisites
- **Docker** (Desktop or Engine)
- **Git** (for source build)

### Option 1: Docker Hub (Recommended)

No build required. Run directly with the pre-built image.

1. **Create `docker-compose.yml`**

```yaml
services:
  warp:
    image: crisocean/warppanel:latest
    container_name: warppanel-client
    restart: unless-stopped
    environment:
      - WARP_BACKEND=usque # 'usque' (default) or 'official'
      # - PANEL_PASSWORD=secret # Optional: Protect the UI
    ports:
      - "5173:8000"            # Web UI
      - "127.0.0.1:1080:1080"  # SOCKS5 Proxy (Local access only)
    volumes:
      - warp_data:/var/lib/cloudflare-warp
      - warp_usque:/var/lib/warp
      - warp_config:/app/data

volumes:
  warp_data:
  warp_usque:
  warp_config:
```

2. **Start Service**

```bash
docker-compose up -d
```

### Option 2: Build from Source

```bash
# 1. Clone
git clone https://github.com/CrisRain/warppanel.git
cd warppanel

# 2. Build & Run
docker-compose up --build -d
```

Access the panel at: **[http://localhost:5173](http://localhost:5173)**

---

## 📖 Usage

1.  **Connect**
    Click the **Connect** button to start.

2.  **Switch Backend**
    Use the dropdown menu to select **Usque** or **Official**.

3.  **Kernel Management**
    Navigate to the **Kernel** page to manage `usque` versions, check for updates, or switch active versions.

4.  **Settings**
    Configure Panel Password, Ports, and Custom Endpoints in the **Settings** page.

5.  **Logs**
    View real-time service logs in the **Logs** page.

## 🔒 Security

> **Important**: The SOCKS5 proxy binds to `127.0.0.1` by default.

To access remotely, use an SSH tunnel:
```bash
ssh -L 1080:127.0.0.1:1080 your-server-ip
```

To expose publicly (not recommended), update `docker-compose.yml` ports to `"1080:1080"`.

---

## 🐧 Linux Native Deployment

Run directly on Ubuntu/Debian without Docker.

```bash
git clone https://github.com/CrisRain/warppanel.git
cd warppanel
chmod +x linux_install.sh
sudo ./linux_install.sh
```

### Management commands
```bash
sudo supervisorctl status
sudo supervisorctl restart all
```

## 💻 Development

<details>
<summary>Development Setup</summary>

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

</details>

## 📄 License
[MIT License](LICENSE)