# Reel Scout

> [English](README.md) ｜ 繁體中文

短影音拆解 CLI 工具。

把 YouTube Shorts、Instagram Reels、TikTok 影片（以及一般長影片）**下載 → 轉錄 → 視覺分析 → 合併 → 評分**，輸出成結構化資料。

---

## 這是什麼

一條把影片變成可分析資料的 pipeline，全部在本機跑（也可接雲端模型）：

1. **crawl** — 用 yt-dlp 下載影片
2. **transcribe** — faster-whisper 逐字轉錄（含時間碼）
3. **vision** — 抽關鍵幀、用 VLM 描述畫面
4. **merge** — 用 LLM 把轉錄 + 視覺合併成結構化分析（hook / 主題 / 風格 / engagement）
5. **score** — LLM 對 craft 四維（hook / 視覺敘事 / 節奏 / 結構）評分

資料存在本機 SQLite（`data/reel_scout.db`），可再 export 成 JSON / CSV / 向量庫。

---

## 安裝

```bash
pip install -e .
pip install -e ".[whisper]"   # faster-whisper 轉錄（建議一起裝）
```

需要 `ffmpeg` 與 `yt-dlp`（Mac：`brew install ffmpeg yt-dlp`）。

---

## 快速開始

```bash
reel-scout config check                              # 檢查環境（ffmpeg / yt-dlp / 後端是否連得到）
reel-scout analyze "https://youtube.com/shorts/xxx"  # 跑完整 pipeline
reel-scout show <video_id>                           # 看完整拆解結果
```

### 常用指令

| 指令 | 用途 |
|------|------|
| `browse` | 列出某頻道／個人頁的影片清單 |
| `crawl` | 只下載影片，不分析 |
| `analyze` | 完整 pipeline（crawl + transcribe + vision + merge）|
| `transcribe` | 只轉錄本機影片／音檔 |
| `vision` | 只抽關鍵幀 + VLM 描述 |
| `score` | 對已分析影片做 LLM 評分 |
| `list` / `show` | 列出 / 檢視已分析影片 |
| `export` | 匯出分析（JSON / CSV / 向量庫）|
| `config` | 設定與環境檢查 |

常用旗標：

```bash
reel-scout analyze --file urls.txt --skip-vision   # 批次跑、跳過視覺分析（省時）
reel-scout analyze "<url>" --score                 # 跑完順便評分
reel-scout analyze "<url>" --resume                # 續跑中斷的批次
```

---

## 中英對照訪談（重要）

whisper `large-v3` 會**用開頭那段偵測到的語言鎖定整支影片**。跑長的中英夾雜訪談（中文主持 + 英文來賓）時，它會把後面**另一種語言**的內容硬「翻譯」回鎖定的語言 —— 來賓的英文就變成一堆亂碼中文。

這是**長檔語言漂移**，不是音檔壞掉：同一段單獨切出來轉，英文完全正常。

**解法** —— 強制每段重新偵測語言：

```bash
WHISPER_MULTILINGUAL=1 WHISPER_CHUNK_LENGTH=15 reel-scout analyze "<url>"
```

- 光開 `multilingual` **不夠**，一定要配短 `chunk_length`（約 15 秒），每段才會重新偵測。
- 實測一支 40 分鐘中主持／英來賓訪談：英文字母還原率 **56% → 90%**，原本亂碼的段落全部變回乾淨英文。
- **單語短影音維持關閉**（每段重偵測會增加成本，預設就是關的）。

其他語言旋鈕：

| 環境變數 | 效果 |
|----------|------|
| `WHISPER_LANGUAGE=en` | 強制單一語言 |
| `WHISPER_TASK=translate` | 一律輸出英文（不管原音）|
| `WHISPER_MULTILINGUAL=1` | 每段重新偵測語言（中英對照用）|
| `WHISPER_CHUNK_LENGTH=15` | 搭配 multilingual 的分段長度（秒）|

> 需要 `faster-whisper >= 1.1`（`multilingual` 參數自 1.1 才有）。

---

## 後端選擇

`merge` 與 `score` 需要一個 LLM／VLM 後端：

- **本機**：Ollama（`OLLAMA_BASE_URL`）或 oMLX（`OMLX_BASE_URL`）—— 免費、離線、要一張夠力的卡或 Apple Silicon。
- **雲端／代理**：Claude、Gemini、OpenClaw proxy（`OPENCLAW_BASE_URL`）—— 無需本機 GPU。

設定走 `.env`（複製 `.env.example` 再改）。跑 `reel-scout config check` 看目前解析到的設定。

---

## 接 Claude Code（MCP）

```bash
reel-scout-mcp   # stdio transport，給 Claude Code 直接呼叫
```

接好後在 Claude Code 裡就能用 `mcp__reel-scout__analyze` 等工具直接拆影片，不用每次敲 bash。設定方式：`claude mcp add reel-scout --scope user`（寫進 `~/.claude.json`，不是 settings.json）。

---

## 硬體需求（本機自跑模型）

模型是**逐階段依序載入**、不同時佔用，峰值卡在文字 LLM，所以 VRAM／統一記憶體是瓶頸：

| 階段 | 模型 | 約略大小 |
|------|------|----------|
| 轉錄 | faster-whisper large-v3 | ~3 GB |
| 關鍵幀 VLM | minicpm-v（~5.5 GB）或 llava:7b（~4.7 GB）| ~5 GB |
| 合併 + 評分 LLM | qwen2.5:14b | ~9 GB |

> 參考：一支短影音（下載 → whisper large-v3 → 關鍵幀 → VLM → 合併 → 評分）在 RTX 4070（12 GB）約 **9–10 分鐘**，whisper + VLM 最吃時間。**一次跑一支**，並行會把顯卡打爆、VLM 逾時。

**建議**（跑滿血模型順暢）：
- NVIDIA：≥12 GB VRAM（RTX 4070 / 3080 級）+ 32 GB RAM + SSD
- Apple Silicon：M2 Pro / M3 Pro+，32 GB 統一記憶體

**最低**（小模型／較慢）：
- NVIDIA：8 GB VRAM（RTX 3060 / 4060）→ 用 qwen2.5:7b + llava:7b/minicpm-v + whisper medium；16 GB RAM
- Apple Silicon：M1 / M2，16 GB 統一記憶體
- 純 CPU：能跑，但 whisper + LLM 很慢 —— 只適合批次／過夜，不適合即時

沒有 GPU？走雲端後端（Claude / Gemini / OpenClaw proxy）以上都不需要。

---

## 授權

MIT —— 個人與商業使用皆免費。
