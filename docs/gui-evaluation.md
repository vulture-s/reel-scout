# GUI Evaluation — go / no-go

> 2026-07-17，reel-scout v1.0.0 收尾後撰寫。這是一份**決策文件**，不是實作計畫。
> 結論先講：**全 GUI app = no-go；最小唯讀本機 dashboard = conditional-go**（條件見下）。

## 為什麼現在問這題

v1.0.0 讓 reel-scout 功能完整（`stats` / `compare` / `research` / `show` / `export`）且可安裝、CI 綠。
自然會冒出「要不要包個 GUI」的念頭。但 [roadmap 的「定位與 Non-goals」](./roadmap.md#定位與-non-goals)
明確把 GUI 列為 **Non-goal**，且附了理由。這份文件把那個決策拿出來，對照 v1.0 的實際狀態重新檢驗一次，
而不是預設要動手。

## 對照三條已載的 Non-goal

roadmap 反對產品化的三條理由，逐條檢驗它們現在還成不成立：

### 1. 平台存取隨時可能被關（成立，且是最硬的一條）

整條 crawl→analyze pipeline 的入口靠 yt-dlp。IG 已在 rate-limit、yt-dlp 的 IG extractor 2026.4 壞過。
**實測爆炸半徑**（roadmap 記錄）：門一關，`crawl` / `browse` / `analyze` 全死。

- 一個**包含爬取/分析**的 GUI，等於把最脆弱的一環擺到最顯眼的位置——使用者點「分析這個頻道」跳一堆看不懂的
  extractor 錯誤，GUI 反而放大了挫折感（CLI 使用者至少看得懂 stderr）。
- v1.0 的 `analyze <local-path>` 保險**只在 CLI/library 層**有意義；GUI 把「餵本機檔」做成好用的拖放，
  才勉強繞過這條——但那已經是另一個產品（本機分析器），不是「短影音競品研究工具」。

### 2. 追平台變動的維護成本高（成立，GUI 只會加碼）

GUI 本身是**額外一整層**要維護：前端框架版本、打包（Electron/Tauri/PWA）、跨平台安裝、
UI 跟 CLI/DB schema 的同步。reel-scout 現在是 solo 維護的工具；DB schema 這輪就從 v4 動到 v6，
每次 schema 變動一個 GUI 都要跟著改 view。**維護負債 = 平台變動成本 × (CLI + GUI 兩套表面)**。

### 3. star / 使用者數非成功指標（成立，未改變）

roadmap 講明成功 = 自己（和會用 CLI 的人）穩定拿到可信分析資料。GUI 的主要理由通常是「降低非技術使用者門檻／衝採用」
——那正是這個 repo 明確**不追**的目標。沒有這個目標，GUI 的主要賣點就消失了。

## GUI 真能解決什麼痛點？（誠實盤點）

不是零價值。目前用 CLI 讀分析結果，這幾個場景確實有摩擦：

| 場景 | CLI 現況 | GUI 會不會更好 |
|---|---|---|
| 掃過一批已分析影片挑高分的 | `list` + 逐個 `show`，來回貼 id | ✅ 表格排序/篩選明顯更好 |
| 比較 3-5 支的結構 | `compare <id...>`（要先知道 id） | ✅ 勾選式選取更順 |
| 看 stats 分佈 | `stats` 純文字表 | ✅ 長條圖比文字直覺 |
| 讀 research 報告 | `--out report.md` 用編輯器開 | ➖ markdown 檢視器就夠，GUI 邊際小 |
| 實際看影片畫面 + keyframe + transcript 對照 | `show` 印文字、keyframe 是檔案路徑 | ✅ 縮圖牆 + 內嵌 transcript 明顯好 |

**關鍵觀察**：這些痛點**全都在「讀已存在 DB 的分析結果」**這一側，
**沒有一個**需要 GUI 去碰 crawler / 平台。這正好指向唯一低風險的形態。

## 若真要動：最小風險形態

**一個吃現有 SQLite DB 的純本機唯讀 dashboard。**

- **不碰 crawler、不碰平台、不寫 DB**——完全規避 Non-goal #1（平台關門它照樣能用，因為它只讀已分析資料）。
- 形態選 **`reel-scout dashboard` 起一個本機 read-only web server**（stdlib `http.server` + 靜態 HTML/JS，
  零前端框架、零打包、零 Electron），而不是桌面 app。這樣維護負債最小：它只是 `stats`/`compare`/`show` 的 HTML 檢視層，
  跟現有 CLI 共用同一個 `db.py` 讀取層。
- 明確**不做**：任何觸發爬取/分析的按鈕（那些留在 CLI）。Dashboard 只回答「我已經分析的東西長怎樣」。

這個形態把「GUI 的真實好處（表格/圖表/縮圖牆）」跟「GUI 的真實成本（平台脆弱性 + 打包維護）」切開，只拿好處那半。

### 對比：全 GUI app 的負債

包含爬取/分析、要打包安裝的桌面 app —— 命中全部三條 Non-goal，維護成本最高、跟 repo 定位直接衝突。**不建議。**

## 建議

| 選項 | 判決 | 理由 |
|---|---|---|
| 全功能 GUI 桌面 app（含爬取） | ❌ **No-go** | 命中三條 Non-goal，維護負債最大，與「工具非產品」定位衝突 |
| 最小唯讀本機 dashboard（`reel-scout dashboard`，只讀 DB） | 🟡 **Conditional-go** | 規避最硬的平台風險；只在你**有實際日常 review 影片的需求**時才值得——若你多半是「跑完 research 報告就結束」，markdown 報告已足夠，不需要 |
| 什麼都不做 | ✅ 合理預設 | 現有 CLI + `research --out` 已覆蓋主要工作流 |

**觸發 conditional-go 的具體條件**：你開始**每天/每週**手動掃一批已分析影片、需要縮圖牆 + 排序篩選來挑素材，
而且這件事用 CLI `list`/`show` 來回貼 id 已經明顯拖慢你。**在那之前，預設不做。**

## 若之後決定做（給未來的自己）

- scope 鎖死在**唯讀 + 只讀 DB**；第一個想加「分析按鈕」的時候就是 scope creep，退回 CLI。
- 技術選型：stdlib `http.server` + 單檔 HTML（inline JS/CSS），資料走一個 `/api/*` JSON 端點直接 `db.py` 查詢。
  不要引入前端框架、不要 Electron/Tauri（那些是為了「桌面 app 分發」，而我們不追採用率）。
- 復用 `stats.compute_stats` / `compare.build_comparison` / `db.get_*`——GUI 只是它們的 HTML 檢視層，零商業邏輯重寫。
- DB schema 已到 v6；任何 view 綁欄位前先確認 migration 穩定。
