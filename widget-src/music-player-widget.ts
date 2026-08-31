import { App } from "@modelcontextprotocol/ext-apps";

interface MusicData {
  audioUrl: string;
  coverUrl: string;
  songName: string;
  artistName: string;
  duration: number;
  lyrics: string;
  colorPrimary: string;
  colorSecondary: string;
  colorBg: string;
  colorBgEnd: string;
}

interface LyricLine { time: number; text: string; }

function parseLRC(lrc: string): LyricLine[] {
  if (!lrc) return [];
  const lines: LyricLine[] = [];
  for (const raw of lrc.split("\n")) {
    const m = raw.match(/\[(\d{2}):(\d{2})\.(\d{2,3})\]\s*(.*)/);
    if (!m) continue;
    const text = m[4].trim();
    if (!text || text.startsWith("作词") || text.startsWith("作曲") || text.startsWith("编曲") || text.startsWith("混音") || text.startsWith("母带") || text.startsWith("配唱") || text.startsWith("制作") || text.startsWith("企划") || text.startsWith("监制") || text.startsWith("出品") || text.startsWith("词 :") || text.startsWith("曲 :") || text.startsWith("【")) continue;
    const secs = parseInt(m[1]) * 60 + parseInt(m[2]) + parseInt(m[3].padEnd(3, "0")) / 1000;
    lines.push({ time: secs, text });
  }
  return lines.sort((a, b) => a.time - b.time);
}

function coerce(data: unknown): MusicData | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  if (typeof d.audioUrl !== "string" || !d.audioUrl) return null;
  const str = (v: unknown, fb: string) => (typeof v === "string" && v ? v : fb);
  const num = (v: unknown, fb: number) => (typeof v === "number" && isFinite(v) ? v : fb);
  return {
    audioUrl: d.audioUrl,
    coverUrl: str(d.coverUrl, ""),
    songName: str(d.songName, "未知歌曲"),
    artistName: str(d.artistName, "未知歌手"),
    duration: num(d.duration, 0),
    lyrics: str(d.lyrics, ""),
    colorPrimary: str(d.colorPrimary, "#6e7c87"),
    colorSecondary: str(d.colorSecondary, "#CAE0E8"),
    colorBg: str(d.colorBg, "#1a1d21"),
    colorBgEnd: str(d.colorBgEnd, "#2a2d31"),
  };
}

let appRef: App | null = null;
let rendered = false;

function fmtTime(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

function render(data: MusicData, platform: "claude" | "chatgpt") {
  rendered = true;
  const root = document.getElementById("root");
  if (!root) return;
  root.innerHTML = "";

  const lyricLines = parseLRC(data.lyrics);
  const hasLyrics = lyricLines.length > 0;
  let lyricsOpen = false;
  let blobUrl: string | null = null;
  let audioReady = false;

  // ── 外层容器 ──
  const wrapper = document.createElement("div");
  wrapper.id = "mp-wrapper";
  wrapper.style.cssText = `width:100%; font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei UI",sans-serif; user-select:none;`;

  // ── 主卡片 ──
  const card = document.createElement("div");
  card.id = "mp-card";
  card.style.cssText = `
    position:relative; box-sizing:border-box; width:100%; min-height:72px;
    display:flex; align-items:center; padding:12px 14px; gap:12px;
    background: linear-gradient(135deg, ${data.colorBg}, ${data.colorBgEnd});
    border-radius:12px; overflow:hidden;`;

  // 背景氛围光
  const glow = document.createElement("div");
  glow.style.cssText = `
    position:absolute; top:-30px; left:-30px; width:140px; height:140px;
    background:radial-gradient(circle, ${data.colorPrimary}30, transparent 70%);
    pointer-events:none; filter:blur(25px);`;
  card.appendChild(glow);

  const glow2 = document.createElement("div");
  glow2.style.cssText = `
    position:absolute; bottom:-20px; right:-20px; width:100px; height:100px;
    background:radial-gradient(circle, ${data.colorSecondary}20, transparent 70%);
    pointer-events:none; filter:blur(20px);`;
  card.appendChild(glow2);

  // ── 封面图 ──
  const cover = document.createElement("div");
  cover.id = "mp-cover";
  const coverSize = 52;
  cover.style.cssText = `
    width:${coverSize}px; height:${coverSize}px; border-radius:10px; flex-shrink:0;
    background:${data.coverUrl ? `url("${data.coverUrl}") center/cover no-repeat` : `linear-gradient(135deg, ${data.colorPrimary}, ${data.colorSecondary})`};
    box-shadow:0 2px 10px rgba(0,0,0,0.35); position:relative; z-index:1;
    transition:transform 0.3s;`;

  if (!data.coverUrl) {
    const note = document.createElement("div");
    note.textContent = "♪";
    note.style.cssText = `position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:20px;color:rgba(255,255,255,0.7);`;
    cover.appendChild(note);
  }
  card.appendChild(cover);

  // ── 右侧内容区 ──
  const content = document.createElement("div");
  content.style.cssText = `flex:1;min-width:0;display:flex;flex-direction:column;gap:5px;position:relative;z-index:1;`;

  // 歌名行（歌名 + 歌词按钮）
  const titleRow = document.createElement("div");
  titleRow.style.cssText = "display:flex;align-items:center;gap:6px;";

  const title = document.createElement("div");
  title.textContent = data.songName;
  title.style.cssText = `font-size:13px;font-weight:600;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;`;

  titleRow.appendChild(title);

  // 歌词按钮
  if (hasLyrics) {
    const lyricBtn = document.createElement("div");
    lyricBtn.id = "mp-lyric-btn";
    lyricBtn.textContent = "词";
    lyricBtn.style.cssText = `
      width:22px;height:22px;border-radius:6px;flex-shrink:0;cursor:pointer;
      font-size:10px;color:rgba(255,255,255,0.5);display:flex;align-items:center;justify-content:center;
      border:1px solid rgba(255,255,255,0.15);transition:all 0.2s;`;
    lyricBtn.addEventListener("click", () => {
      lyricsOpen = !lyricsOpen;
      lyricPanel.style.display = lyricsOpen ? "block" : "none";
      lyricBtn.style.color = lyricsOpen ? data.colorSecondary : "rgba(255,255,255,0.5)";
      lyricBtn.style.borderColor = lyricsOpen ? data.colorSecondary + "66" : "rgba(255,255,255,0.15)";
      reportHeight();
    });
    titleRow.appendChild(lyricBtn);
  }

  content.appendChild(titleRow);

  // 歌手
  const artist = document.createElement("div");
  artist.textContent = data.artistName;
  artist.style.cssText = `font-size:10px;color:rgba(255,255,255,0.45);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:-2px;`;
  content.appendChild(artist);

  // ── 控制栏 ──
  const controls = document.createElement("div");
  controls.style.cssText = "display:flex;align-items:center;gap:8px;margin-top:2px;";

  // 播放按钮
  const btn = document.createElement("div");
  btn.id = "mp-play";
  btn.style.cssText = `
    width:28px;height:28px;border-radius:50%;flex-shrink:0;cursor:pointer;
    background:linear-gradient(135deg, ${data.colorPrimary}, ${data.colorSecondary});
    display:flex;align-items:center;justify-content:center;
    box-shadow:0 2px 6px ${data.colorPrimary}44;transition:transform 0.1s,opacity 0.2s;`;
  btn.innerHTML =
    `<svg class="i-play" width="11" height="12" viewBox="0 0 24 24" fill="white"><path d="M8 5v14l11-7z"/></svg>` +
    `<svg class="i-pause" width="11" height="12" viewBox="0 0 24 24" fill="white" style="display:none"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>`;
  const iPlay = btn.querySelector(".i-play") as SVGElement;
  const iPause = btn.querySelector(".i-pause") as SVGElement;

  // 加载指示
  const loadingEl = document.createElement("div");
  loadingEl.style.cssText = `display:none;position:absolute;inset:0;align-items:center;justify-content:center;`;
  loadingEl.innerHTML = `<div style="width:10px;height:10px;border:2px solid white;border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite"></div>`;
  btn.style.position = "relative";
  btn.appendChild(loadingEl);

  // 进度条
  const progressWrap = document.createElement("div");
  progressWrap.style.cssText = `flex:1;height:18px;display:flex;align-items:center;cursor:pointer;position:relative;`;

  const progressBg = document.createElement("div");
  progressBg.style.cssText = `width:100%;height:3px;border-radius:2px;background:rgba(255,255,255,0.12);position:relative;overflow:visible;`;

  const progressFill = document.createElement("div");
  progressFill.style.cssText = `width:0%;height:100%;border-radius:2px;background:linear-gradient(90deg, ${data.colorPrimary}, ${data.colorSecondary});transition:width 0.25s linear;position:relative;`;

  const dot = document.createElement("div");
  dot.style.cssText = `
    position:absolute;right:-5px;top:50%;transform:translateY(-50%);
    width:10px;height:10px;border-radius:50%;
    background:${data.colorSecondary};box-shadow:0 0 6px ${data.colorPrimary}66;
    opacity:0;transition:opacity 0.2s;`;
  progressFill.appendChild(dot);
  progressBg.appendChild(progressFill);
  progressWrap.appendChild(progressBg);

  // 时间
  const timeEl = document.createElement("div");
  timeEl.style.cssText = "font-size:9px;color:rgba(255,255,255,0.4);flex-shrink:0;min-width:32px;text-align:right;";
  timeEl.textContent = fmtTime(data.duration);

  controls.append(btn, progressWrap, timeEl);
  content.appendChild(controls);
  card.appendChild(content);
  wrapper.appendChild(card);

  // ── 歌词面板 ──
  const lyricPanel = document.createElement("div");
  lyricPanel.id = "mp-lyrics";
  lyricPanel.style.cssText = `
    display:none; width:100%; max-height:180px; overflow-y:auto;
    padding:10px 14px; box-sizing:border-box;
    background:linear-gradient(180deg, ${data.colorBgEnd}, ${data.colorBg});
    border-radius:0 0 12px 12px; margin-top:-12px; padding-top:18px;
    scrollbar-width:none;`;
  lyricPanel.addEventListener("scroll", () => {}, { passive: true });

  // 渲染歌词行
  const lyricEls: HTMLDivElement[] = [];
  for (const line of lyricLines) {
    const el = document.createElement("div");
    el.textContent = line.text;
    el.style.cssText = `
      font-size:12px; color:rgba(255,255,255,0.3); padding:4px 0;
      transition:color 0.3s, transform 0.3s; text-align:center;
      transform:scale(0.95); transform-origin:center;`;
    lyricPanel.appendChild(el);
    lyricEls.push(el);
  }
  wrapper.appendChild(lyricPanel);

  // ── 注入全局样式 ──
  const style = document.createElement("style");
  style.textContent = `
    @keyframes spin { to { transform: rotate(360deg); } }
    #mp-lyrics::-webkit-scrollbar { display:none; }
    #mp-card:hover #mp-cover { transform:scale(1.03); }
  `;
  wrapper.appendChild(style);

  root.appendChild(wrapper);

  // ── 音频逻辑 ──
  const audio = document.createElement("audio");
  audio.preload = "auto";
  let playing = false;
  let raf = 0;
  let realDuration = data.duration;
  let activeLyricIdx = -1;

  // 预加载音频到blob解决seek问题
  const preloadAudio = async () => {
    loadingEl.style.display = "flex";
    iPlay.style.opacity = "0";
    try {
      const resp = await fetch(data.audioUrl);
      const blob = await resp.blob();
      blobUrl = URL.createObjectURL(blob);
      audio.src = blobUrl;
      audioReady = true;
    } catch (e) {
      console.warn("[music] preload failed, using direct URL");
      audio.src = data.audioUrl;
      audioReady = true;
    }
    loadingEl.style.display = "none";
    iPlay.style.opacity = "1";
  };

  // hover显示圆点
  progressWrap.addEventListener("mouseenter", () => { dot.style.opacity = "1"; });
  progressWrap.addEventListener("mouseleave", () => { if (!playing) dot.style.opacity = "0"; });

  const updateLyric = (currentTime: number) => {
    if (!lyricsOpen || lyricLines.length === 0) return;
    let idx = -1;
    for (let i = lyricLines.length - 1; i >= 0; i--) {
      if (currentTime >= lyricLines[i].time - 0.1) { idx = i; break; }
    }
    if (idx === activeLyricIdx) return;
    activeLyricIdx = idx;
    for (let i = 0; i < lyricEls.length; i++) {
      if (i === idx) {
        lyricEls[i].style.color = data.colorSecondary;
        lyricEls[i].style.transform = "scale(1)";
        lyricEls[i].scrollIntoView({ behavior: "smooth", block: "center" });
      } else {
        lyricEls[i].style.color = "rgba(255,255,255,0.3)";
        lyricEls[i].style.transform = "scale(0.95)";
      }
    }
  };

  const tick = () => {
    if (!playing) return;
    const dur = audio.duration || realDuration || 1;
    const prog = Math.min(audio.currentTime / dur, 1);
    progressFill.style.width = (prog * 100) + "%";
    timeEl.textContent = fmtTime(dur - audio.currentTime);
    updateLyric(audio.currentTime);
    raf = requestAnimationFrame(tick);
  };

  const toggle = async () => {
    if (!audioReady) {
      await preloadAudio();
    }
    if (playing) {
      audio.pause();
      playing = false;
      iPlay.style.display = "block";
      iPause.style.display = "none";
      dot.style.opacity = "0";
      cancelAnimationFrame(raf);
    } else {
      audio.play().then(() => {
        playing = true;
        iPlay.style.display = "none";
        iPause.style.display = "block";
        dot.style.opacity = "1";
        tick();
      }).catch((e) => console.warn("[music] playback failed:", e));
    }
  };

  btn.addEventListener("click", toggle);
  btn.addEventListener("mousedown", () => { btn.style.transform = "scale(0.92)"; });
  btn.addEventListener("mouseup", () => { btn.style.transform = "scale(1)"; });

  // 点击进度条跳转
  progressWrap.addEventListener("click", (e) => {
    const rect = progressBg.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const dur = audio.duration || realDuration || 1;
    audio.currentTime = ratio * dur;
    progressFill.style.width = (ratio * 100) + "%";
    updateLyric(audio.currentTime);
  });

  audio.addEventListener("loadedmetadata", () => {
    if (audio.duration && isFinite(audio.duration)) {
      realDuration = audio.duration;
      timeEl.textContent = fmtTime(realDuration);
    }
  });

  audio.addEventListener("ended", () => {
    playing = false;
    iPlay.style.display = "block";
    iPause.style.display = "none";
    dot.style.opacity = "0";
    cancelAnimationFrame(raf);
    progressFill.style.width = "0%";
    timeEl.textContent = fmtTime(realDuration);
    activeLyricIdx = -1;
  });

  // ── 报告高度 ──
  const reportHeight = () => {
    if (platform !== "claude") return;
    requestAnimationFrame(() => {
      const h = Math.ceil(wrapper.getBoundingClientRect().height);
      if (h <= 0) return;
      document.documentElement.style.height = h + "px";
      document.body.style.height = h + "px";
      if (appRef) {
        try { appRef.sendSizeChanged({ width: Math.ceil(window.innerWidth), height: h }); } catch {}
      }
    });
  };

  requestAnimationFrame(() => { reportHeight(); setTimeout(reportHeight, 300); });
}

function showError(msg: string) {
  if (rendered) return;
  const root = document.getElementById("root");
  if (root) root.innerHTML = `<div style="color:#888;font-size:13px;padding:10px;">${msg}</div>`;
}

function renderToolResult(
  params: { structuredContent?: unknown; content?: Array<{ type: string; text?: string }> },
  platform: "claude" | "chatgpt"
) {
  let data = coerce(params?.structuredContent);
  if (!data && Array.isArray(params?.content)) {
    for (const block of params.content) {
      if (block.type === "text" && block.text) {
        try { data = coerce(JSON.parse(block.text)); } catch {}
        if (data) break;
      }
    }
  }
  if (data) render(data, platform);
}

async function tryMcpApps() {
  try {
    const app = new App({ name: "music-player", version: "2.0.0" }, {}, { autoResize: false });
    appRef = app;
    app.addEventListener("toolresult", (params: { structuredContent?: unknown; content?: Array<{ type: string; text?: string }> }) => {
      renderToolResult(params, "claude");
    });
    await app.connect();
  } catch (e) {
    console.debug("[music] MCP Apps connect skipped:", e);
  }
}

function boot() {
  void tryMcpApps();
  setTimeout(() => showError("等待音乐数据…"), 4000);
}

boot();
