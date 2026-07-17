# Reel Scout — Roadmap

> 最後校正：2026-07-15（對照實際 code 逐項驗證，非憑記憶）

## 定位與 Non-goals

**Reel Scout 是工具，不是末端產品。**

它的形態是 CLI + MCP + library：給會用終端機（或會叫 AI 幫你跑）的人，把短影音變成結構化資料。它**不會**變成雙擊即用的 GUI app。

**為什麼不產品化**（2026-07-15 決策）：

1. **平台存取隨時可能被關**。整條 pipeline 的入口靠 yt-dlp。IG 已經在 rate-limit，yt-dlp 的 IG user extractor 2026.4 就壞過。
   **實測爆炸半徑**（2026-07-15）：門一關，`crawl` / `browse` / **`analyze`（整條 pipeline，也就是核心價值）全死** —— `analyze` 只吃 URL，餵本機路徑直接 `ValueError: Unsupported platform for URL`。
   活下來的只有 `transcribe <path>` / `vision <path>`（個別階段）與 `score` / `show` / `export`（吃已存的 DB）。
   **也就是說這個風險目前零緩解措施** —— 補上 `analyze <local-path>`（見 5B）才是真正的保險。工具的存活優勢是**可以做到**，不是現在就有。
2. **追平台變動的維護成本極高**。把它做成終端使用者產品，等於簽下一份「平台每改一次、我就得修一次，而且使用者會抱怨」的長期合約。這不是這個專案想付的代價。
3. 因此 **star 數 / 使用者數不是這個 repo 的成功指標**。成功 = 自己（和會用 CLI 的人）能穩定拿到可信的分析資料。

**Non-goals**：GUI 桌面 app、一鍵安裝器、社群營運 / Product Hunt / 行銷推廣、SaaS 或託管服務。

> GUI 這條 2026-07-17 於 v1.0 收尾後重新檢驗過一次 → [`docs/gui-evaluation.md`](./gui-evaluation.md)：
> 全 GUI app **no-go**；只讀 DB 的最小本機 dashboard **conditional-go**（有日常 review 需求才做）。

---

## 現況

```
Phase 1  ████████████████████  ✅ Core Pipeline（crawl + transcribe + vision + merger + DB + CLI + MCP）
Phase 2  ████████████████████  ✅ Advanced Analysis（audio/PANNs + diarize/pyannote + scorer + LLM backends）
Phase 2.5████████████████████  ✅ 品質強化（subtitle-first / keyframe budget / prompt pack / skill / 雙語轉錄）
Phase 3  ██████████████████░░  🔨 Batch Intelligence — browse ✅、compare ✅、3C ✅、3D stats ✅；patterns ❌
Phase 4  █████░░░░░░░░░░░░░░░░  🔨 Content Strategy Engine — 4A research ✅；inspire/track/MCP擴充 ❌
Phase 5  ██████████████████░░  ✅ Tool Hygiene — LICENSE/README/CHANGELOG ✅、analyze-local ✅、yt-dlp 健壯性 ✅、CI ✅、config check ✅；PyPI build 就緒（上架待人工 token）
```

**目前版本**：v1.1.0 ｜ **測試**：162 passing ｜ **DB schema**：v6

### 已完成功能清單（2026-07-15 驗證）

- **Crawl**: yt-dlp (YT/IG/TikTok) + rate limiter + cookies + IG instaloader fallback
- **Browse**: 帳號/頻道頁列出所有影片（human / `--json` / `--urls-only`）
- **Transcribe**: subtitle-first（優先吃原生字幕，`find_subtitle`）→ faster-whisper / whisper.cpp fallback
- **中英雙語轉錄** (v0.2.0): `WHISPER_MULTILINGUAL` + `WHISPER_CHUNK_LENGTH` 每段重偵測語言，解長檔語言鎖定漂移（40 分鐘中英訪談實測：latin 還原 56%→90%）；另有 `WHISPER_LANGUAGE` / `WHISPER_TASK`
- **Vision**: keyframe 抽取（scene / interval / motion / hybrid + first/last 保底 + score）+ duration-aware frame budget + `KEYFRAME_RESOLUTION` 升採樣（讀畫面小字）+ `--start/--end` focus window + VLM (oMLX/Ollama) + fallback model + per-frame resilience（單幀逾時不炸整跑）
- **Audio**: PANNs 音訊事件偵測（onnxruntime, optional）
- **Diarize**: pyannote speaker diarization（optional）
- **LLM Backend**: omlx / ollama / **openclaw**（走 proxy 吃訂閱制，無需本機 GPU）
- **Merger**: 結構化分析 JSON + timeline / narrative arc + hook `opening_type` + `cta_type`（含 `visit` 實體造訪）
- **Scorer**: craft 四維 LLM 評分 — `hook_strength` / `visual_storytelling` / `pacing` / `structure`
- **Prompt pack**: 6 份 reverse-decode prompt（開源，作為預設分析層）
- **Skill**: cross-surface skill 打包（SKILL.md + manifests）
- **MCP Server**: stdio NDJSON JSON-RPC, 5 tools
- **CLI**: browse / crawl / analyze / transcribe / vision / list / show / export（json/csv/**html**）/ score / compare / stats / research / **view** / db / config
- **Viewer** (v1.1.0): 唯讀檢視器兩面——`export --format html`（自包含單檔、零安裝 take-home）+ `reel-scout view`（本機 server、live demo）；顯示拆解結構+keyframe+分數+逐字，無動作按鈕
- **DB**: SQLite WAL + batch resume + schema migration（→ v4）

---

## Phase 3 — Batch Intelligence（跨影片模式分析）

**目標**：從「逐支分析」進化到「跨影片批量模式識別」，回答「什麼類型的短影音表現好？」

### 3A. 批量爬取 + 頻道模式 🔨 半套（2026-07-15 補完主體）

- [x] `reel-scout browse <profile_url>` — 帳號頁瀏覽（2026-04-16）
- [ ] IG browse: instaloader fallback — **未實作**（2026-07-15 查證：`git log --all -S instaloader -- reel_scout/` 零 commit；`pyproject.toml` 有 `instagram` optional extra 但 `reel_scout/` 零引用；`InstagramCrawler.browse` 是純 yt-dlp，失敗即 `RuntimeError`。此項先前誤標已完成）
- [x] browse 三種輸出模式：human / `--json` / `--urls-only`（2026-04-16）
- [x] pyproject: `instagram` optional dependency group（2026-04-16）
- [x] `crawl --channel <URL> --limit N` — browse → crawl 串起來（2026-07-15，PR #9）
- [x] `crawl --playlist <URL>` — 播放清單批量（2026-07-15，PR #9）
- [x] `crawl --file -` 吃 stdin — `browse --urls-only | crawl --file -` 這條 browse 自己打廣告的 pipe 過去**從沒通過**（`open("-")` → `FileNotFoundError`），2026-07-15 修好（PR #9）
- [ ] `crawl --trending --platform youtube` — 平台趨勢（⚠️ 最脆弱，最可能被平台擋，優先序最低；與本檔的平台風險判斷相衝，**刻意不做**）
- [ ] 頻道 metadata 存 DB（subscriber count、avg views、niche tag）— **需先設計 channel 表**：目前沒有 channel 表也沒有 `channel_id`，唯一把手是 `videos.uploader`（自由文字、無索引、實際值長成 `Ben Aizen | Artzen Media` / `小建`）。獨立一輪處理
- [ ] `crawl --channel` 傳 VideoMeta 而非 URL — browse 已經帶回 title/uploader/duration，但 `download()` 簽章吃 URL，所以會再打一次 `yt-dlp --dump-json`（每支多一個請求）。改簽章是真 refactor，v1 先付這個代價
- [ ] `crawl` 的 batch/resume — 目前 `batches` / `batch_items` / `--resume` 全是 `analyze` 專屬（`pipeline.py`）。要給 crawl 用得把 orchestration 從 `pipeline.run` 搬出來

### 3B. 跨影片比較分析 🔨 半套

- [x] `reel-scout compare <video_id_1> <video_id_2> ...` — 結構化對比表（2026-07-17）。純讀 DB
      已存的 analyses/scores（duration / format / pacing / hook type / cta type / content type + craft 四維分 + overall），
      轉置表（欄=影片、列=欄位）+ `--json`；接受 exact id 或唯一 prefix；缺分析欄位留 `—` 不捏造；平台關門也能跑。
- [ ] `reel-scout patterns --channel <channel_id>` — 頻道模式分析（平均長度、hook 類型分佈、CTA 模式、高分 vs 低分結構差異、發布節奏）

### 3C. 模式標籤系統 ✅

- [x] Hook 類型分類：`question|statement|visual|music|none`（merger 產出，存 `analyses.hooks_json`）
- [x] CTA 類型分類：`follow|like|comment|link|visit|none`
- [x] 內容結構分類：hook-body-cta / problem-solution / listicle / story-arc / raw-moment（2026-07-17，schema v6；merger prompt 新增 `content_structure` 欄位）
- [x] 標籤正規化進可查詢欄位（2026-07-17，schema v5）：`content_type / opening_type / cta_type / style_format / style_pacing / emotion / content_structure` 從 `full_json` 鏡射進 `analyses` 索引欄，`full_json` 仍為 SSOT；舊資料 migration 自動 backfill

### 3D. 統計 ✅（2026-07-17）

- [x] `reel-scout stats` — 全局統計：tag 分佈（content_type/content_structure/format/pacing/opening/cta/emotion）+ score 聚合（overall & 四維 avg/min/max/n），純讀正規化欄位
- [x] `reel-scout stats --channel <uploader>` — 頻道維度（key on free-text `uploader` 子字串，無 channel 表故非精確 id）
- [x] `reel-scout stats --csv <path>` — 匯出 long-format CSV（`metric,dimension,key,value`）；另有 `--json`

---

## Phase 4 — Content Strategy Engine（從分析到行動）

**目標**：把分析資料變成可執行的產出。全部維持 CLI/MCP 形態。

### 4A. 競品研究報告 ✅（2026-07-17）

- [x] `reel-scout research --niche "<niche>" --channels <urls...> --depth 20` — 爬取 → 全部 analyze → 跨頻道聚合 → 產出 markdown 報告（niche 共通模式、差異化機會、內容策略）。編排復用 browse + `pipeline.run(score=True)` + `compare.collect_video`；channel 歸屬記憶體映射（無 channel 表）；`aggregate()` 純函式；LLM 合成走 `get_llm().complete()`，不可達時退回 deterministic data-only 報告；`--out` 落檔、`--json` 出聚合、`--no-analyze` 只吃現有 DB

### 4B. 內容靈感產生器

- [ ] `reel-scout inspire --based-on <video_id> --angle <twist>` — 基於高分影片的變體
- [ ] 輸出：標題建議 + hook 腳本 + 結構大綱 + 推薦長度

### 4C. MCP 擴充

- [ ] MCP tool 擴充：`reel_scout_research`、`reel_scout_inspire`（讓 agent 直接呼叫，不用經 bash）

### 4D. 表現回填 + A/B 結構比較

- [ ] `reel-scout track --my-video <url> --views 1500 --likes 89` — 記錄實際表現
- [ ] 對比分析：自己的影片 vs 競品的結構差異 → 迭代建議

---

## Phase 5 — Tool Hygiene（工具品質，非社群營運）

**目標**：讓這個工具**可安裝、可信賴、不會安靜爛掉**。這裡沒有推廣/社群項目——見「定位與 Non-goals」。

### 5A. 可安裝

- [x] LICENSE: MIT
- [x] README（EN + 繁中）+ 安裝/使用說明
- [x] `pyproject.toml` 完整（entry points、optional deps 分組）
- [ ] **PyPI 發布** — `pip install reel-scout`（目前 PyPI 404）
- [ ] 版本/CHANGELOG 流程固定（v0.2.0 已建 CHANGELOG.md）

### 5B. 不會安靜爛掉

- [x] **GitHub Actions CI** — pytest matrix Python 3.9–3.13（2026-07-17，`.github/workflows/ci.yml`）；push master + 每個 PR 觸發，只裝 base+dev（suite 全 headless，2 個 onnxruntime 測改 `importorskip`）。實測 5 條 leg 全綠
- [x] **`analyze <local-path>` — 平台關門的唯一實際保險**（見 Non-goals #1 的實測爆炸半徑）。2026-07-17 完成：
      `analyze` 的 URL 引數現在也吃本機檔路徑 → 註冊一列 `platform="local"`、`url == file_path == abspath`、`platform_id` 用內容 hash（同內容不同路徑會 dedup 到同一 video_id）的 row，Steps 2-5 完全不用改。
      duration 用獨立 probe，失敗留 `None`（**不**寫 `60.0` 謊言）；路徑打錯給 `FileNotFoundError: Local file not found` 而非 crawler 的 opaque「Unsupported platform」。
- [x] **yt-dlp 從 PATH 解析，不是用自己 pin 的那支**（2026-07-15 實測）。2026-07-17 完成：新增 `crawl/ytdlp.py`，
      所有 crawler 改走 `ytdlp.cmd(...)` — 預設用 `python -m yt_dlp`（本 venv 那支），可用 `YTDLP_BIN` 覆寫。
      實測驗證：PATH 上是 homebrew `2026.03.17`、resolved 是 venv `2026.07.04`（先前 crawl 靜默吃到過期那支）。
- [x] yt-dlp 相依健康檢查：平台 extractor 壞掉時給明確錯誤 + fallback 指引。2026-07-17：`ytdlp.format_error` 偵測
      extractor-類失敗（Unable to extract / Unsupported URL / …）時附上 `<resolved> -U` / `pip install -U yt-dlp` 更新提示。
- [x] **錯誤訊息只印 `stderr[:500]`，真因常被前 500 字的 warning 淹掉**（2026-07-15 追字幕 429 case）。2026-07-17：
      `ytdlp.format_error` 優先留 `ERROR:` 開頭的行；無 ERROR 行才退回取 stderr 尾段（真因通常在尾不在頭）。
- [x] `config check` 涵蓋所有後端可達性（2026-07-17）：yt-dlp 改用 `ytdlp.base_cmd()`（跟 runtime 一致，非硬寫）、LLM 可達性依 `LLM_BACKEND` 查、補 audio/diarize/instagram optional 後端（已配置才查，diarize 缺 token 標紅）；`_run_config_checks()` 抽成結構化可測函式

### 5C. 文件

- [ ] `docs/`：MCP 整合、LLM backend 設定、prompt pack 用法
- [ ] 範例輸入 → 範例輸出（不含版權素材）

---

## 參考案例（study cases）

### lapian-notes（2026-07 觀察）

`bkingfilm/lapian-notes` — AI 輔助電影拉片工具（TS/React/Vite，MIT）。**不同類別**（末端產品，非工具），但架構有一點值得存檔備用：

**AI-agnostic package handoff**：它自己完全不跑推論。本機抽幀 + 抓字幕 + metadata → 打包 ZIP → 使用者自己丟給任何 AI → 把回傳的 JSON 匯入 → 工具只負責視覺化。零 API key、零 GPU、零後端。

**對本專案的關聯**：目前 **不需要** — reel-scout 已有 `--llm-backend openclaw`（走 proxy 吃訂閱制，同樣不需要 GPU），是比手動貼 ZIP 更好的機制。

**未來可能用得上的情境**：若要讓完全不想配置任何後端的人也能跑 merge/score，可加 `package` / `import` 一對指令（reel-scout 已有 keyframe + transcript，工程量不大）。**等真的有這個需求再做。**

---

## 設計原則

1. **CLI-first** — 所有功能先有 CLI，再有 MCP/API
2. **Offline-capable** — 核心分析可用本機 LLM（oMLX/Ollama），不強制雲端；但雲端/訂閱後端（openclaw）也是一等公民
3. **Minimal dependencies** — urllib not requests，argparse not click，SQLite not Postgres
4. **Python 3.9** — 維持較舊系統相容
5. **Batch-friendly** — 大量影片分析是核心場景，不只是單支
6. **工具不是產品** — 見「定位與 Non-goals」

---

## 里程碑

> ⚠️ 版號與 phase 已脫鉤：v0.2.0（雙語轉錄）是計畫外的品質修復，不在原 Phase 規劃內。以下里程碑改為**以能力為準、不綁 phase 編號**。

| Milestone | 條件 |
|-----------|------|
| **v0.3** | ~~3A 補完（`crawl --channel/--playlist`）~~ ✅ 2026-07-15 + ~~3B（`compare`）~~ ✅ 2026-07-17 |
| **v0.4** | ~~3C 標籤正規化~~ ✅ + ~~3D（`stats`）~~ ✅ 2026-07-17（達成，隨 v1.0 一次發布） |
| **v0.5** | ~~4A（競品研究報告）~~ ✅ 2026-07-17（達成，隨 v1.0 一次發布） |
| **v1.0** | ~~5A + 5B 完成（PyPI build 就緒 + CI 綠 + yt-dlp 健康檢查 + config check）~~ ✅ 2026-07-17（PyPI 上架待人工 token） |
