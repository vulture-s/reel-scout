---
cssclasses:
  - vulture
---

# claude-real-video (crv) × Reel Scout — 對標 case study

> **一句話**：兩者不在同一層。crv（含付費 Pro）是「讓 AI **看得清**一支影片」的**感知＋測量層**——把畫面／聲音／鏡頭運動**量化**成 LLM 讀得懂的原料；Reel Scout 是「反解一支短片**為什麼會紅**」的**判讀層**——帶 rubric 的 craft 評分＋reverse-decode＋競品語料庫。重疊只在最前面的 ingest（都靠 yt-dlp 抓、都在本機跑）；crv Pro 往上爬了一層到「怎麼拍的（測量）」，但**沒有**踩進 Reel Scout 的「會不會紅（判斷）」。真正該從這次對標偷的只有一項：crv Pro 的 `--motion` **實測** cuts/min，正打在 Reel Scout「pacing 分數靠 LLM 猜、且 model-dependent」的軟肋上。
>
> _建立於 2026-07-17。crv 側資料取自公開 GitHub（HUANGCHIHHUNGLeo/claude-real-video，1,699★／MIT／2026-06-30 開）＋ 付費頁 leoaido.com/crv-pro/，逐字引用附出處；付費版閉源，只讀銷售頁、未購未跑，Pro 的測量準度未驗。Reel Scout 側取自本 repo。_

---

## 0. TL;DR

| | **claude-real-video（free）** | **crv Pro（$19）** | **Reel Scout** |
|---|---|---|---|
| 定位 | 讓 LLM「看得見」影片的前處理器 | 讓 LLM 知道「怎麼拍的」的測量器 | 反解「為什麼會紅」的判讀器 |
| 層 | 感知（擷取） | 感知＋測量 | 判讀（評斷） |
| 產出 | frames＋transcript＋MANIFEST（原料） | ＋鏡頭表／cuts-per-min／情緒曲線／一次性 AI 報告 | 結構化分析＋craft 0–10 分＋競品報告 |
| 有 rubric 評分？ | ❌ | ❌（只有技法報告） | ✅ hook／visual／pacing／structure |
| 有「為什麼有效」推理？ | ❌ | ⚠️ 技法描述,非 engagement 判斷 | ✅ reverse-decode prompt pack |
| 有跨影片語料庫？ | ❌（資料夾） | ❌（資料夾） | ✅ SQLite 可累積＋competitor research |
| 平台 | YT／IG／TikTok／本地 | 同左 | YT Shorts／IG／TikTok／本地 |
| 授權／隱私 | MIT、全本地 | 閉源付費、全本地 | MIT、全本地 |
| 熱度／商業 | 1,699★／2.5 週、`npx skills add` 一鍵裝 50+ host | 開源病毒核心→$19 一次性 upsell | 刻意不追（[roadmap](./roadmap.md)「工具不是產品、star 不是成功指標」） |

**最重要的一點**：crv 免費版**完全不做判讀**——產出是 `frames.json`／`transcript.txt`／`MANIFEST.txt`，交給下游任何 LLM 自己去「看」。crv Pro 往上做的是把「怎麼拍的」**測量**出來（鏡頭種類、剪點密度、BPM、情緒曲線）＋一份用你自己 API key 生的技法報告。**兩者都止於「呈現給 LLM」,沒有 Reel Scout 那條「帶 rubric 打分＋反解會不會紅＋沉澱成可比語料」的判讀軸。** 這條界線就是 Reel Scout 唯一還乾淨的護城河。

---

## 1. 這三個東西不在同一層

先破誤會：crv 和 Reel Scout **不是同類工具的兩個選項**,是影片理解 pipeline 的**上下游**。

```
影片 ──▶ [crv free] 擷取：scene-aware 去重 frames + transcript ──┐
       ──▶ [crv Pro] ＋測量：鏡頭表 / cuts-per-min / 情緒 / OCR / 鑑識 ──┤──▶ 交給 LLM 自己看
                                                                        │
影片 ──▶ [Reel Scout] 擷取 + VLM 描述 + 判讀：craft 打分 / 反解 / 競品語料 ──▶ 給創作者可行動的結論
```

- **crv（free＋Pro）** 解的是「AI 看不懂影片、Gemini 要上傳雲端、Claude／ChatGPT 不吃影片檔」——把一支影片**變成 LLM 讀得懂又不外送的原料**,愈精細愈好。它的目標函數是**保真呈現**,不下判斷。
- **Reel Scout** 解的是「這支短片為什麼火、骨架怎麼抄到我自己題材」——把短片拆成**帶評分與反解的結構**給創作者**再創作**。它的目標函數是**判讀可信**（錯了會拍錯片,代價高）。

方向不同（一個把畫面攤平給 LLM 看,一個替創作者下判斷）,所以「誰比較強」得先問「比哪一層」。

---

## 2. crv 免費版：擷取層,做得聚焦且比 Reel Scout 前段講究

| 面向 | crv free | Reel Scout 前段 |
|---|---|---|
| Frame 取法 | **場景變化偵測＋滑窗像素去重**（全域 RGB＋局部細節）＋adaptive 慢變模式＋text-anchor 對齊字幕 | keyframe（scene／interval／motion／hybrid＋首尾保底） |
| 說話者 | 內建 diarization（pyannote） | diarization（pyannote,optional) |
| 呈現 | contact sheet 對照表＋viewer.html＋MANIFEST for LLM | `export --format html`＋`view` server＋**`inspect`（可點時間軸跳播，port 自 arkiv）** |
| 判讀 | ❌ 全交給下游 LLM | ✅ VLM 逐幀描述 |

誠實講:**光看「把影片變成 LLM 看得懂的東西」,crv free 這一件事做得比 Reel Scout 前段更精緻也更聚焦**——場景偵測＋去重比固定間隔／keyframe 更成熟,還多了 adaptive／text-anchor／contact sheet。但它**到此為止**:沒有 VLM 描述、沒有評分、沒有反解、沒有語料庫。它是把原料備好,不動判斷。

一個架構分歧值得記:**crv 把 frames 直接丟給 agent 自己的多模態模型看;Reel Scout 跑本機 VLM 先把畫面「描述成文字」再融合。** 前者省一次推論、吃下游 LLM 的視覺力;後者產出可查詢、可打分、可入庫的結構化欄位。對「要沉澱成語料」的用途,Reel Scout 的路是對的。

---

## 3. crv Pro（$19）：爬到「測量層」,還沒到「判斷層」

付費頁定位語逐字:**"Make AI understand how a video was shot — not just what it shows"**。價格 **$19 one-time**（創始價到 7/31,8/1 起 $29）。六個付費 flag:

| flag | 做的事（逐字節錄） | 性質 |
|---|---|---|
| `--motion` | 鏡頭自動分類 static／pan／tilt／zoom／handheld;**"a full shot table: per-shot duration, cuts per minute, how pacing shifts"**;高動態 0.2s 爆發幀 | **客觀測量** |
| `--senses` | 語音情緒／聲調曲線;音訊事件（笑聲／SFX／環境音）;人聲樂器分離＋BPM＋能量;無對白內容的色彩光影 mood | **客觀測量** |
| `--viewer` | 可點事件時間軸的互動 web viewer;逐字稿同步高亮;中英介面 | 呈現 |
| `--ai-report` | **用你自己的 API key** 生兩份報告:拍攝技法 ＋ 內容／對白 | LLM 報告 |
| `--ocr` | 帶時間戳可搜尋的螢幕文字;CJK 強;用字幕修正 STT | 擷取 |
| `--speed-check` | 變速／竄改鑑識(補幀指紋、運動軌跡連續性);證據式,**不下「正常速度」定論** | 鑑識 |

**判讀:Pro 是「擷取＋測量」的延伸,不是「判斷」。** 它把「怎麼拍的」量化(鏡頭種類、cuts/min、BPM、情緒曲線)＋一份技法報告。它**沒有**:

- craft 評分 rubric(Reel Scout 的 hook／visual／pacing／structure 0–10)
- reverse-decode「為什麼會紅」的推理框架 ＋ 4 層信號可靠度(L1 uploader→L4 VLM)
- 多頻道競品 research ＋ 可累積可比的 SQLite 語料庫

README teaser 那句 "and why it works" 是行銷話術;付費頁本身收斂成 "how it was shot"＋技法報告,**沒踩進 engagement／會不會紅的判斷**。這條界線成立——也是 Reel Scout 判讀層未被威脅的證據。

---

## 4. 逐面向對照

| 面向 | crv free | crv Pro | Reel Scout | 誰在這面向強 |
|---|---|---|---|---|
| Frame 擷取精緻度 | ✅ 場景偵測＋去重 | ✅ 同＋爆發幀 | ⚠️ keyframe（夠用） | **crv** |
| 鏡頭運動 / pacing **測量** | ❌ | ✅ 鏡頭表＋cuts/min | ❌（pacing 靠 LLM 猜） | **crv Pro** |
| 音訊事件 / 情緒 | ❌ | ✅ 情緒曲線＋BPM | ⚠️ PANNs 事件(optional),無情緒曲線 | **crv Pro** |
| 螢幕文字 OCR | ❌ | ✅ 時間戳＋CJK | ✅ VLM 讀招牌字＋`KEYFRAME_RESOLUTION` 升採 | 平手（機制不同） |
| VLM 逐幀**描述** | ❌ 交下游 | ❌ 交下游 | ✅ 本機 VLM 描述入庫 | **Reel Scout** |
| craft **評分**(帶 rubric) | ❌ | ❌ | ✅ 四維 0–10 | **Reel Scout** |
| 反解「為什麼會紅」 | ❌ | ⚠️ 技法報告,非 engagement | ✅ reverse-decode prompt pack | **Reel Scout** |
| 跨影片模式 / 競品 | ❌ | ❌ | ✅ compare／research／stats | **Reel Scout** |
| 語料沉澱 | ❌ 資料夾 | ❌ 資料夾 | ✅ SQLite 可累積 | **Reel Scout** |
| 互動 viewer(可點時間軸跳播) | ❌(靜態 viewer.html) | ✅ `--viewer` event timeline | ✅ `inspect` transcript↔keyframe 時間同步(port 自 arkiv,#29) | 平手 |
| 分發 / 熱度 | ✅ 1,699★＋npx 一鍵 | ✅ 病毒核心→付費漏斗 | ❌ 刻意不追(見 §6) | **crv**(但見 §6) |
| 易安裝 | ✅ pip／npx | ✅ pip | 🟡 兩行 pip（`pip install reel-scout` yt-dlp 自動帶 → `reel-scout skill install` skill 隨包出貨）＋ffmpeg 系統裝 | 接近平手（crv 略勝在 npx 一鍵；ffmpeg 系統依賴兩邊 ingest 都要） |

**公允結論**:擷取／測量層 crv 全面領先(尤其 Pro 的鏡頭運動與情緒測量);判讀／語料層 Reel Scout 全面領先(rubric 評分、反解、競品、入庫)。**兩邊各自把自己那一層做深,重疊只在最前面的 ingest。** crv Pro 是側翼威脅——它逼近但沒攻進 Reel Scout 的核心判斷軸。

---

## 5. Reel Scout 該從這次對標偷的一項:pacing 從「猜」變「量」

這是本次對標唯一真正 actionable 的技術項,而且它踩在 Reel Scout 一個**已知弱點**上:

- Reel Scout 的 `pacing`(scorer 四維之一)是**LLM 憑感覺給的、且 model-dependent**——換一顆 VLM／LLM 分數就飄(見 memory「Reel Scout 評分依賴模型」)。
- crv Pro 的 `--motion` 產出 **shot table:每分鏡時長 ＋ cuts per minute ＋ 節奏變化**——這是**客觀測量、可重現**,不靠模型主觀。
- **同樣講「節奏」,他量、你猜。**

**可偷的 move**:在 Reel Scout 的 vision 階段加一個**確定性的剪點偵測**(ffmpeg scene-change 已在用,cut 邊界資訊本來就抓得到→算 cuts/min、每鏡頭時長、節奏變化),把 `pacing` 分數從「純 LLM 判斷」改成「**實測 shot-table 當證據,LLM 只在證據上做解讀**」。這正好對齊 Reel Scout roadmap 的核心價值「保真／可信賴」,也把 vibe-reader case study §6.1 說的「舉證護欄變機器可驗證」再推一步——**分數也要能舉證,不只主張要舉證**。

> ⚠️ 邊界:crv Pro 閉源,我沒讀它 `--motion` 實作,不知它 cut 偵測用什麼閾值、handheld 怎麼判。這裡偷的是**概念**(pacing 該用實測 shot-table 背書),不是抄它的數字或宣稱它準。

已在 roadmap 開一條追蹤(見 §「評分證據化」)。

---

## 6. 為什麼「他更紅」不進 Reel Scout 的檢討清單

crv 2.5 週衝 1,699★＋$19 付費漏斗＋`npx skills add` 一鍵裝 50+ host——很漂亮的病毒開源→變現打法。但把它列成「Reel Scout 該學的教訓」是**錯把別人的目標函數套到自己頭上**:

- Reel Scout 的 [roadmap](./roadmap.md) 明文拍板:**「工具不是產品」**,Non-goals 含 GUI／一鍵安裝器／社群營運／Product Hunt／SaaS,且**「star 數／使用者數不是這個 repo 的成功指標。成功＝自己(和會用 CLI 的人)能穩定拿到可信的分析資料。」**
- 也就是說 crv 贏的那條軸(分發／熱度／變現),Reel Scout **主動選擇不站**。拿它來自責等於推翻已拍板的定位。

**crv 的漏斗值得存檔,但存的位置是「課程／內容的 case study」,不是「Reel Scout 該補的功能」。** 若哪天要跟學員講「開源工具怎麼變現」,crv Pro 是現成教材(開源病毒核心→$19 一次性→創始價 urgency);但 Reel Scout 這個 repo 維持工具身分,不因為別人紅就轉去追 star。這是**紀律,不是酸葡萄**。

---

## 附錄:資料出處與未能確認項

**crv 側**(全部公開,未購未跑):
- GitHub `HUANGCHIHHUNGLeo/claude-real-video`(README＋GitHub API metadata:1,699★／137 fork／MIT／created 2026-06-30／updated 2026-07-17／Python)。
- 付費頁 `leoaido.com/crv-pro/`(定位語、$19 one-time＋8/1 起 $29、六個 flag、free-vs-Pro 表、對 Gemini 的比較,皆逐字取自銷售頁)。
- 作者其他 repo:`claude-memory-framework`／`claude-playbook-loop`(homepage `leoaido.com`)、多份 awesome-claude-* 清單——顯示他走「Claude 生態內容＋工具」路線。

**未能確認(不臆測,明列)**:
- crv Pro 閉源付費,**未購、未安裝、未跑**;`--motion`／`--senses`／`--speed-check` 的實際準度、cut 偵測閾值、情緒模型皆黑箱,本檔只據銷售頁**宣稱**,一律打折看。
- README teaser 的 "why it works" 與付費頁的 "how it was shot" 用詞不一致;本檔以付費頁(產品實際 flag)為準,判定 Pro 止於測量＋技法報告、未達 engagement 判斷。
- crv free 的 frame 去重「比 Reel Scout 精緻」為讀 README 得出,**未讀其 source 逐行驗證**。
- 1,699★ 為 2026-07-17 當日 GitHub API 讀值,會變動。

_Reel Scout 側資料取自本 repo `reel_scout/`(scorer.py／merger.py／analyze/pipeline.py)、`prompts/`、`docs/roadmap.md`、README。_
