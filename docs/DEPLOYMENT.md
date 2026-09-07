# 部署说明

`server.py` 只启动一个 ASGI 服务。MCP、签名音频流、共同状态事件和健康检查共用同一端口：

| 路径 | 用途 |
| --- | --- |
| `/mcp` | Streamable HTTP MCP 连接地址 |
| `/music-audio/stream` | 使用限时签名令牌解析并转发音频 Range 流 |
| `/music-state/event` | 播放器上报真实播放事件 |
| `/health` | 部署健康检查 |

## 必需配置

- `NCM_API_BASE_URL`：私有 Netease-compatible API。
- `PUBLIC_BASE_URL`：本服务对外的 HTTPS origin，不带 `/mcp`。
- `MUSIC_EVENT_SIGNING_SECRET`：随机长值；用于签发歌曲级限时令牌。
- `MUSIC_STATE_PATH`：SQLite 文件路径。容器部署时应位于持久卷中。

可选：

- `NCM_COOKIE_FILE`：服务端 Cookie 文件的绝对路径。
- `MUSIC_ACTIVE_LEASE_SECONDS`：活跃共听租约，默认 7200 秒。
- `MUSIC_EVENT_TOKEN_TTL_SECONDS`：播放器令牌时长，默认 86400 秒。
- `ALLOWED_AUDIO_HOST_SUFFIXES`：允许的音频 CDN 后缀，默认 `.music.126.net`。

## 反向代理

只需把整个公网域名反代到 `127.0.0.1:3941`。必须保留 `GET`、`POST`、`OPTIONS`，不要缓存 `/mcp` 或 `/music-state/event`。

Nginx 最小示例：

```nginx
server {
    listen 443 ssl http2;
    server_name music.example.com;

    location / {
        proxy_pass http://127.0.0.1:3941;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

音频响应会透传 `Range`、`Content-Range`、`Content-Length` 和 `Content-Type`，因此进度条可以稳定跳转。不要在前置代理层移除这些头。

## systemd

将 `deploy/music-mcp.service.example` 复制为 systemd unit，并替换用户、代码路径和环境文件路径：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now music-mcp
sudo systemctl status music-mcp
```

## 容器持久化

Dockerfile 默认使用 `/data/music_state.db`。部署平台需要挂载持久磁盘到 `/data`；若平台只有临时文件系统，共同状态会在重新部署时清空。

只运行一个实例是最简单的选择。SQLite 能安全处理同一文件的并发事务，但不适合多个容器跨机器共享同一个普通文件卷；需要水平扩容时，应把状态层迁移到托管数据库。

仓库的 `compose.yaml` 还会启动一个只在容器内网开放的兼容音乐源，并把 `NCM_API_BASE_URL` 自动指向它。这样无需单独暴露或手工连接音乐源服务。

## 上线检查

1. `GET https://你的域名/health` 返回 `ok: true`。
2. MCP 地址填写 `https://你的域名/mcp`。
3. 点歌后卡片可见，但未点击时 `get_music_session` 仍为 `idle`。
4. 点击播放后变为 `listening`；暂停为 `paused`；自然播完或关闭后为 `idle`。
5. Range 请求返回 `206` 和正确的 `Content-Range`。
6. 日志、工具结果和数据库中都没有 Cookie 或临时 CDN URL。
