# 部署说明

`server.py` 启动两个本地 HTTP 服务：MCP 端口和音频代理端口。建议二者都只监听 `127.0.0.1`，由 Nginx/Caddy 统一提供 HTTPS。

## 环境变量

在 systemd 的 `EnvironmentFile` 或其他私有配置文件中设置 `.env.example` 中的变量。特别注意：

- `NCM_API_BASE_URL`：你的私有 Netease-compatible API。
- `PUBLIC_BASE_URL`：外部可访问的音频代理路径，例如 `https://example.com/music-audio`。
- `NCM_COOKIE_FILE`：可选的本地 Cookie 文件绝对路径；不要写入仓库或 systemd unit。

## systemd 示例

将 `deploy/music-mcp.service.example` 复制为 systemd unit，并把用户、代码路径、环境文件路径替换为自己的值：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now music-mcp
sudo systemctl status music-mcp
```

## 反向代理要求

将 MCP 的公开路径反代到本机 MCP 端口，将音频代理路径反代到本机代理端口。MCP 端点应保留 streamable HTTP 所需的请求方法和响应头；音频代理必须透传 `Range`、`Content-Range`、`Content-Length` 和 `Content-Type`，才能稳定拖动进度条。

不要把代理配置成转发任意 URL。本服务已经限制上游音频域名，反向代理也不应移除此限制。
