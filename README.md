# Music Player MCP · Shared Listening Edition

一个可在支持 MCP Apps 的聊天客户端里直接渲染的音乐播放器，并带有真实、持久、可查询的共同收听状态。

本分支保留原项目的搜索、按歌曲 ID 播放、封面、歌词和聊天内 widget，同时补上共同状态架构中最重要的第一层：只有用户真的点击播放后，系统才记录为“正在听”；暂停、继续、自然播完、关闭页面都会形成对应事件，模型可通过结构化工具读取事实状态。

> 源码不附带网易云账号 Cookie、密钥、音乐文件、歌词或封面资源。使用者必须自行配置兼容的音乐数据 API，并遵守数据源与音乐版权方的条款。

## 已有能力

| 能力 | 说明 |
| --- | --- |
| `play_music` | 搜索前 5 条结果，取第一首真实可播放歌曲并生成卡片。 |
| `play_music_by_id` | 按网易云歌曲 ID 验证并生成卡片。 |
| `get_music_session` | 返回紧凑的当前状态和最近 5 条共听事件。 |
| 单服务部署 | MCP、签名音频流、事件上报和健康检查共用一个端口。 |
| 真实播放事件 | `play / pause / resume / finish / close` 由播放器实际行为触发。 |
| 持久状态 | SQLite 事务写入，默认保留最近 500 条事件。 |
| 活跃租约 | 默认 2 小时；陈旧的播放记录不会被误称为“正在听”。 |
| 隐私边界 | Cookie、临时 CDN URL 和完整歌词不进入共同状态。 |

歌单导入、共享队列、跨页面唯一播放器、今日私选和反馈是下一阶段能力；它们应继续进入同一条播放链路，而不是再造第二个播放器。

## 请求流

1. 模型调用 `play_music` 或 `play_music_by_id`。
2. 服务从私有 Netease-compatible API 获取详情、歌词，并验证真实音源。
3. 工具返回聊天内播放器，以及只对这一首歌有效的签名播放令牌。
4. 用户点击播放时，服务重新解析临时音源并通过稳定的 Range 流输出。
5. 播放器成功开始后才写入 `play`；后续状态也由真实播放器事件写入。
6. 模型调用 `get_music_session` 后，才能据此描述当前是否正在共听。

工具结果和数据库都不会保存上游临时音频 URL。

## 单机快速开始

需要 Python 3.11+、Node.js 20+，以及一个单独运行的 Netease-compatible API。

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
npm ci
npm run build:widget
cp .env.example .env
```

生成签名密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

把结果放入私有环境变量 `MUSIC_EVENT_SIGNING_SECRET`，再配置：

```dotenv
NCM_API_BASE_URL=http://127.0.0.1:3939
PUBLIC_BASE_URL=https://music.example.com
APP_HOST=127.0.0.1
APP_PORT=3941
MUSIC_STATE_PATH=./data/music_state.db
```

由进程管理器加载环境变量后启动：

```bash
python server.py
```

公开连接地址为：

```text
https://music.example.com/mcp
```

健康检查为 `GET /health`。

## 最省事的 Docker Compose

仓库附带 `compose.yaml`，会同时启动：

- 只在容器内网开放的、持续维护的 Netease-compatible API；
- 对外开放的播放器 MCP；
- 保存共同状态的 Docker volume。

先复制 `.env.example` 为 `.env`，至少填写真实的 `PUBLIC_BASE_URL` 和随机的 `MUSIC_EVENT_SIGNING_SECRET`，然后：

```bash
docker compose up -d --build
```

音乐源使用维护中的 `moefurina/ncm-api` 镜像，只通过内部网络供播放器访问，不直接暴露 3000 端口。

## 只运行播放器容器

```bash
docker build -t music-player-mcp .
docker run --rm -p 3941:3941 \
  --env-file .env \
  -v music-player-data:/data \
  music-player-mcp
```

容器默认监听 `0.0.0.0:3941`，SQLite 位于 `/data/music_state.db`。生产环境必须挂载持久卷，否则重新部署会丢失共同状态。

## 部署与安全

详细反向代理和持久化要求见 [部署说明](docs/DEPLOYMENT.md)。自建聊天前端的数据契约见 [自定义前端适配](docs/CUSTOM-FRONTEND.md)。

- `NCM_COOKIE_FILE` 只指向服务端私有文件；不要把 Cookie 放进环境变量日志、Git、聊天消息或前端。
- `MUSIC_EVENT_SIGNING_SECRET` 必须是随机长值。播放器只拿到限时签名令牌，拿不到密钥。
- 音频流只接受签名歌曲令牌；服务端再解析白名单 CDN，不提供任意 URL 代理。
- 所有跳转都重新检查音频域名，最多跟随 3 次跳转。
- 共同状态只保留歌曲元数据、动作、选择者、进度和时间。

## 开发

```bash
python -m pytest -q
npm run build:widget
```

```text
server.py                         # MCP、签名音频流、事件接口
music_state.py                    # SQLite 状态账本与签名令牌
widget-src/music-player-widget.ts # MCP Apps 播放器和真实事件上报
tests/                            # 状态、令牌和 HTTP 路由测试
```
