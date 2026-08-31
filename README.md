# Music Player MCP

一个基于 [Model Context Protocol](https://modelcontextprotocol.io/) 与 `@modelcontextprotocol/ext-apps` 的聊天内音乐播放器。它提供搜索播放与按歌曲 ID 播放两项工具，并返回可播放的音乐卡片数据。

> 这是一份可部署的源码，不附带网易云账号 Cookie、密钥、音乐文件、歌词或封面资源。使用者必须自行配置兼容的音乐数据 API，并自行遵守数据源与音乐版权方的条款。

## 它如何工作

1. 模型调用 `play_music` 搜索歌名，或调用 `play_music_by_id` 直接播放歌曲 ID。
2. MCP 向配置好的、Netease/网易云兼容 API 查询搜索结果、歌曲信息、封面、歌词与临时播放地址。
3. 服务将音频地址经受限的音频代理返回，播放器使用浏览器 `<audio>` 播放，支持暂停、拖动进度和歌词时间轴。
4. `@modelcontextprotocol/ext-apps` 客户端会读取工具的 widget 元数据，直接把 `widget-src/music-player-widget.ts` 构建出的界面渲染为卡片。

网易云的播放 URL 通常是临时的，约 **20 分钟** 后可能失效；这不是播放器永久保存的下载链接。失效后应重新调用播放工具获取新链接，而不是重试旧 URL。

## 工具

| 工具 | 用途 |
| --- | --- |
| `play_music` | 输入歌名或关键词，搜索第一条可播放结果并显示播放器。 |
| `play_music_by_id` | 输入网易云歌曲 ID，直接生成播放器。 |

两项工具均可传入 `color_primary`、`color_secondary` 与 `color_bg`，自定义卡片颜色。

## 快速开始

需要 Python 3.11+、Node.js 20+，以及一个单独运行的 Netease-compatible API。

```bash
git clone <your-repository-url>
cd music-player-mcp

python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
npm install
npm run build:widget
```

复制并修改环境变量：

```bash
cp .env.example .env
```

然后由你的进程管理器加载这些变量并启动：

```bash
python server.py
```

默认情况下，MCP 监听 `127.0.0.1:3941`，音频代理监听 `127.0.0.1:3942`。生产环境应使用 Nginx 或 Caddy 暴露 HTTPS 路径，示例见 [部署说明](docs/DEPLOYMENT.md)。

## 客户端兼容性

### 支持 MCP Apps / ext-apps 的客户端

将公开的 streamable HTTP MCP 地址添加为连接器即可。只要客户端能够识别 `@modelcontextprotocol/ext-apps` 和工具的 output template，它会自动渲染播放器 widget，不需要再写前端页面。

### 自己写的聊天前端

普通网页聊天不会因为“连接了 MCP”就自动拥有卡片组件。它需要读取工具结果，并将其转换为自己的音乐消息卡片；数据结构和推荐接入方式见 [自定义前端适配](docs/CUSTOM-FRONTEND.md)。

你不需要开源自己的整套聊天应用。把这份 MCP 服务开源，再提供这一页适配说明即可。

## 安全与发布前检查

- `.env`、Cookie 文件、访问令牌与私有域名均不应提交。
- 本项目的音频代理只允许 `ALLOWED_AUDIO_HOST_SUFFIXES` 中的域名，避免成为任意 URL 的开放代理。
- 不要把音频、歌词、封面或歌曲目录打包进仓库；均应由运行时请求得到。
- 发布 GitHub 前请自行选择并添加许可证文件；当前仓库未预设许可证。

## 开发结构

```text
server.py                         # FastMCP、音乐数据请求与受限音频代理
widget-src/music-player-widget.ts # ext-apps 播放器源码
scripts/build-widget.mjs          # 构建 dist/widget/ 的脚本
docs/                             # 部署与自定义前端接入说明
```
