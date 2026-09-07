# 自定义聊天前端适配

MCP Apps 客户端会渲染服务附带的 widget；自建聊天页面则可以选择自行绘制一张卡片。不要把整段歌词、临时音频 URL 或原始 MCP 返回内容拼入模型提示词。

## 最小数据契约

从 `play_music` 或 `play_music_by_id` 的结构化结果中读取：

```ts
type MusicCard = {
  audioUrl: string;       // 服务端签名流；不暴露上游临时 CDN URL
  eventUrl: string;       // 真实播放事件上报地址
  eventToken: string;     // 限时、限单曲签名令牌
  songId: number;
  coverUrl: string;
  songName: string;
  artistName: string;
  albumName: string;
  selectedBy: "user" | "companion";
  duration: number;       // 秒
  lyrics: string;         // LRC；只交给播放卡片，不注入模型上下文
  colorPrimary: string;
  colorSecondary: string;
  colorBg: string;
  colorBgEnd: string;
};
```

建议只将“歌曲名、歌手、发送时间、歌曲 ID、选择者”作为对话记录的摘要。歌词和签名令牌属于展示/运行数据，不应为了日记或普通对话再次注入 AI 上下文。

## 消息顺序

一次 AI 回复既有文本又调用播放工具时：

1. 先渲染全部文字消息。
2. 将音乐卡片作为本轮 AI 回复的最后一条非文字消息。
3. 不自动播放；必须由用户点击播放，避免任何新消息或重渲染暂停正在播放的 `<audio>`。

## 伪代码

```ts
const card = toolResult.structuredContent as MusicCard;

appendAssistantTextMessages(reply.textMessages);
appendMusicCard({ type: "music", ...card });

// 卡片内部：audio.src = card.audioUrl
// timeupdate 时依据 LRC 时间戳更新高亮行与滚动位置。
```

只有 `audio.play()` 成功后才向 `eventUrl` 上报 `play`。用户暂停、继续、自然播完或页面关闭时分别上报 `pause`、`resume`、`finish`、`close`；未点击的卡片不能写入“正在共听”。

签名令牌过期后，显示“播放卡已过期，请重新点歌”，让模型重新调用一次播放工具；不要无限重试旧卡片。
