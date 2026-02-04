# WarpPanel

WarpPanel 是一个现代化的 Web 控制面板，专为管理单实例 Cloudflare WARP 客户端而设计。它提供了一个极具质感的响应式界面，让您可以轻松连接、断开 WARP，并在 **official** 与 **usque** 双核引擎间自由切换。

## ✨ 功能特性

- **🎯 单实例管理**：精准控制您的 WARP 容器，状态实时同步，极低资源占用。
- **🔄 无缝双核切换**：
    - **usque (MASQUE)**：高性能、轻量级，支持快速连接。
    - **Official Client**：官方稳定版，兼容性强。
    - 支持在 Web 界面一键热切换，无需重启容器，自动处理端口释放与冲突。
- **🚀 零阻塞架构**：后端采用全异步非阻塞设计，所有的耗时操作（连接、切换、检测）均在后台线程池执行，确保 Web 服务和 UI 始终流畅响应。
- **🎨 极致 UI 设计**：基于 Vue 3 和 Tailwind CSS v4 构建，采用磨砂玻璃拟态（Glassmorphism）风格，动画流畅丝滑。
- **⚡ 实时监控**：基于 WebSocket 的实时状态推送，秒级响应连接变化。
- **🛡️ 纯净日志**：智能日志过滤系统，屏蔽冗余的 "Connection open/closed" 噪音，仅保留关键业务日志；Official 后端连接命令静默执行，保护隐私。
- **🔄 智能 IP 轮换**：支持一键断开重连以获取新 IP，内置连接性检测确保 IP 可用。
- **📊 详细连接信息**：直观展示 IP 地址、城市、国家/地区、ISP 供应商、协议类型及端点信息。
- **🔒 SOCKS5 代理**：内置标准 SOCKS5 代理服务（默认端口 `1080`），方便其他应用直接接入。

## 🛠️ 技术栈

- **前端**: Vue 3 + Vite + Tailwind CSS (v4)
- **后端**: FastAPI (Python 3.10+) + AsyncIO
- **核心**: Cloudflare WARP Official Client + usque (Go implementation)
- **容器化**: Docker + Docker Compose

## 📸 效果预览

![WarpPanel UI](resources/WarpPanel-02-02-2026_09_48_PM.png)

## 🚀 快速开始

### 前置要求

- Docker Desktop (或 Docker Engine + Docker Compose)
- Git

### 方式一：Docker Hub 快速启动 (推荐)

无需构建代码，直接使用预构建镜像：

1. 创建 `docker-compose.yml` 文件：

```yaml
version: '3.8'
services:
  warp:
    image: crisocean/warppanel:latest
    container_name: warppanel
    restart: unless-stopped
    cap_add: [NET_ADMIN]
    devices: [/dev/net/tun]
    environment:
      - WARP_BACKEND=usque # 可选: 'usque' (高性能, 默认) 或 'official' (官方客户端)
    sysctls: [net.ipv6.conf.all.disable_ipv6=0]
    ports:
      - "5173:8000" # Web UI
      - "1080:1080" # SOCKS5 Proxy
    volumes:
      - warp_data:/var/lib/cloudflare-warp
      - ./warp_config:/var/lib/warp # usque 配置文件 (建议挂载)

volumes:
  warp_data:

```

### 🎮 双后端模式 (Dual Backend)

WarpPanel 现在支持两种 WARP 核心，您可以根据需要在 Web 界面随时切换：

1.  **usque (默认)**: 轻量级、高性能的开源实现 (Go)，资源占用更低，连接速度更快。
2.  **official**: Cloudflare 官方 Linux 客户端，稳定性强，兼容性好。

您也可以通过环境变量 `WARP_BACKEND` 指定容器启动时的默认后端。


2. 启动服务：


```bash
docker-compose up -d
```

### 方式二：从源码构建

如果您想修改代码或自己构建：

1. 克隆项目仓库：

```bash
git clone https://github.com/CrisRain/warppanel.git
cd warppanel
```

2. 使用 Docker Compose 构建并启动服务：

```bash
docker-compose up --build -d
```

3. 访问 Web 界面：打开浏览器访问 **http://localhost:5173**

### 端口说明

- **Web UI**: 5173
- **API**: 8000
- **SOCKS5 Proxy**: 1080

## 📖 使用说明

1. **建立连接**：点击界面中央巨大的 **Connect** 按钮启动 WARP 连接。
2. **切换内核**：在右上角或设置菜单中选择 **Usque** 或 **Official**，系统将自动处理服务重启与端口切换。
3. **查看状态**：连接成功后，卡片将显示您的实时 IP、地理位置和 ISP 信息。
4. **复制代理**：在 Proxy Address 卡片中，点击 "Copy" 按钮即可快速复制 SOCKS5 代理地址。
5. **轮换 IP**：点击底部的 **Rotate IP** 按钮，系统将自动断开并尝试获取新的 IP 地址。
6. **查看日志**：点击 "Service Logs" 卡片可以进入详细日志页面。系统会自动过滤无用信息，保持清爽。

## 💻 开发指南

### 前端开发
```bash
cd frontend
npm install
npm run dev
```

### 后端开发
```bash
cd controller-app
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 📄 许可证

MIT License - 欢迎个人学习与使用。