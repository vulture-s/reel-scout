---
cssclasses:
  - vulture
---

# Vibe Reader × Reel Scout — 「精準度」比較 case study

> **一句話**：兩者不是同一軸上的競品，所以「精準度」在兩邊不是同一件事。Vibe Reader 的精準度＝**卡片是否忠實還原講者原話 + 時間戳是否落在對的秒數**；Reel Scout 的精準度＝**分析是否把「看到的」和「推論的」分開、每個主張是否可回溯到時間戳**。兩者唯一真正的共同主軸是「把主張錨回原始時間戳」——而恰好在這條軸上，Vibe Reader 自己公開的 share 頁面就有**可驗證的失準**（時間戳超出影片長度）。
>
> _建立於 2026-07-16。Vibe Reader 側資料全部取自公開來源（App Store / Play / Chrome Web Store / landing / share.vibe-reader.com / iubenda 隱私政策 / ToS），逐字引用附出處；未經註冊、未安裝。Reel Scout 側取自本 repo。_

---

## 0. TL;DR（給趕時間的）

| | **Vibe Reader** | **Reel Scout** |
|---|---|---|
| 一句話 | 消費端「讀得快」的理解 App | 創作端「拆得準」的研究 CLI |
| 誰用 | 想快速吸收長內容的讀者 | 想反解爆款、拍自己短影音的創作者 |
| 輸入 | 長文章 / Podcast / YouTube 長片（41–105 分實測） | YouTube Shorts / IG Reels / TikTok 短影音 |
| 輸出 | 章節式「解讀卡」（swipeable insight cards）+ 跳回時間戳 | 結構化欄位（transcript + keyframe + VLM）+ 反解 prompt pack |
| 精準度＝ | 卡片忠於講者原話 + 時間戳落在對的秒 | observation/inference 分離 + 每個主張 cite 時間戳 |
| 精準度靠什麼保證 | **無明文保證**（marketing 有暗示，ToS 明文免責） | **設計即護欄**（4 層信號 + 舉證規則 + 逐 chunk 語言重偵） |
| 實測發現的失準 | 3 支公開 share 有 2 支時間戳**超出影片長度**；1 支 clip 重疊嵌套 | （待跑，見附錄 rubric） |

**最重要的一點**：Vibe Reader 的頭號賣點是 *"Tap a chapter timestamp to land at the exact second in the original"*（點時間戳落到原片的精確那一秒），但它自己 share 出來的 3 支範例裡，**2 支的最後一個 clip 結束時間超出了影片本身的長度**（TED 那支：clip 標 `41:20–82:43`，影片只有 `41:32` 長——結束點在影片結束後 **41 分鐘**）。這是拿它自己的公開輸出驗出來的，不是使用者操作錯誤。

---

## 1. 這兩個產品不在同一條軸上

先破一個常見誤會：Vibe Reader 和 Reel Scout **不是**同類工具的兩個選項，它們是**知識供應鏈的兩端**。

```
長內容 ──▶ [Vibe Reader] ──▶ 讀者快速吸收（消費端）
爆款短片 ──▶ [Reel Scout] ──▶ 創作者反解結構、拍自己的（生產端）
```

- **Vibe Reader** 解的是「我存了一堆長文章 / Podcast / YouTube 沒時間看」——把**長**內容壓成**短**卡片給你**讀**。它把 *"A two-hour keynote becomes eight cards"* 當賣點。
- **Reel Scout** 解的是「這支短片為什麼會火、骨架怎麼抄到我自己題材」——把**短**內容拆成**結構化資料**給你**再創作**。它的 prompt pack 明講是要 *reverse-engineer why a short-form video works and extract a transferable structure*。

方向相反（一個壓縮消費、一個拆解生產），輸入長度相反（長 vs 短），使用者角色相反（讀者 vs 創作者）。所以：

> **比「精準度」時，得先問「哪一種精準度」。** 兩邊的「準」指的根本不是同一件事。

---

## 2. 「精準度」在兩邊的定義

| 面向 | Vibe Reader 的「準」 | Reel Scout 的「準」 |
|---|---|---|
| **保真對象** | 卡片內容是否＝講者**真正說的**（而非表面重點） | VLM/transcript 描述是否＝影片**真正發生的**（而非 caption 說的） |
| **時間戳** | 點章節能否落到原片**精確那一秒** | 每個結構主張能否**cite 到它依據的時間戳** |
| **抗操縱** | （無明確主張） | 明確抗 caption 操縱：*caption 寫 A、畫面在做 B，VLM 看到 B* |
| **抗幻覺** | （無明確主張；ToS 明文免責） | 明確：*observation vs. inference 分離*、看不到就說「不確定」、不准用「短影音通常會…」腦補 |
| **語言保真** | 翻成 14 種語言（宣稱） | 逐 chunk 語言重偵，救中英夾雜 drift（latin 字元還原 56%→90%，實測） |

關鍵差異：**Vibe Reader 把精準度當「結果宣稱」，Reel Scout 把精準度當「流程護欄」。** 前者說「我給你的是講者真正的點」，但沒有機制向你證明；後者把「怎麼避免騙到自己」直接寫進 prompt 的規則裡，強迫模型舉證。

---

## 3. Vibe Reader 的精準度：宣稱 vs 實際

### 3.1 它怎麼宣稱（逐字引用）

保真相關的主打文案，逐字：

- Landing：*"Not a summary. An insight, per chapter."*
- Landing：*"Each section gets its own card with **the speaker's actual point** — not a top-line recap."*
- Google Play：*"Not a summary. An interpretation. Every card tells you three things: **what the author said**, why they said it, and what it means for you."*
- Landing（時間戳賣點）：*"Jump back to the source — Tap a chapter timestamp to **land at the exact second** in the original."*

注意三個跨商店的**命名自相矛盾**：iOS 叫 *"AI Summary Cards"*、Play 叫 *"AI Insight Cards"*、但 marketing 又堅持 *"Not a summary."* ——連它自己都沒對齊「這到底是不是摘要」。

### 3.2 它實際的失準（拿它自己的公開 share 驗）

`share.vibe-reader.com` 是公開的，上面有真實的 share 卡片。把每個 clip 的 `start–end` 去比對 YouTube 原片真實長度，發現：

**時間戳超出影片長度（「精確那一秒」落在影片結束之後）：**

| Share 範例 | 影片真長 | 出問題的 clip | 超出量 |
|---|---|---|---|
| TED "Better Human"（v1, EN） | 41:32 | 最後一個 clip 標 `41:20–82:43` | 結束點在片尾後 **~41 分鐘** |
| 李宏毅 GenAI 講座（v1, ZH） | 105:14 | 最後一個 clip 標 `105:13–106:14` | 結束點在片尾後 **60 秒** |

**clip 重疊 / 嵌套（時間戳→洞見的對應是鬆的、近似的，不是精確的）：**

- 李宏毅那支：`2:04–5:20` 疊 `2:47–7:20` 疊 `5:20–8:21`；還有一個 21 分鐘長的 clip `82:32–104:24` 裡面**包住**另外兩個 clip。

> **這就是 case study 的實錘**：產品的頭號承諾是「落到精確的那一秒」，但 3 支自己公開的範例裡，2 支有 clip 結束點超出影片長度、1 支時間戳大量重疊。取樣雖小（3 支 / 42 個 clip），但**這是廠商自己的輸出**，缺陷可直接從它公開頁面重現。

### 3.3 卡片實際長什麼樣（逐字，Boris Cherny / Lenny's Podcast v2）

> **Insight 01 — AI is Already Writing 100% of Code for Top Engineers**
> Boris Cherny kicks off the conversation with a bold claim: 100% of his code is now written by Claude Code... He hasn't manually edited a single line of code since November, shipping 10-30 pull requests daily...

觀察：卡片**確實忠實轉述了講者的原話**（這點它做到了），但它**沒有把「Boris 宣稱」和「事實」分開標記**——`200% productivity` 這種講者的主張，被平鋪成敘述句，讀者無從分辨這是「講者說的」還是「被驗證的事實」。這正是 Reel Scout 的 observation/inference 護欄要解的問題（見 §4）。

### 3.4 它用什麼跑（技術揭露）

iubenda 隱私政策點名的 AI 子處理商：**OpenAI、Anthropic (Claude)、Google (Gemini)、xAI (Grok)**，用 **n8n** 編排。也就是拿通用商用 LLM 做摘要。**未揭露**：transcript 來源是 YouTube 字幕還是 ASR、哪個模型處理哪一段、chunk 策略、時間戳怎麼推導出來的——§3.2 的時間戳缺陷很可能就出在「時間戳怎麼推導」這段黑箱。

### 3.5 ToS 自己把精準度免責掉了

- ToS §Availability, Errors and Inaccuracies：*"We cannot and do not guarantee the accuracy, completeness, or reliability of any information... or any material derived or extracted from the Content."*
- 責任切割還特別點名 AI：不為 *"any content obtained from the Service, **including AI-generated content**"* 負責。

> **尖銳對比**：Marketing 說「講者真正的點 / 不是摘要，是詮釋」，ToS 說「我不保證準確，錯了算你的」。行銷層的精準度承諾在法務層被收回。

---

## 4. Reel Scout 的精準度：設計即護欄

Reel Scout 不「宣稱」精準，它把「怎麼不騙到自己」寫進流程。四個機制：

### 4.1 4 層信號可靠度（抗 caption 操縱）

不能只看 caption 就下結論。從最弱到最強：

| 層 | 來源 | 可靠度 | 為什麼 |
|---|---|---|---|
| L1 | Uploader 名稱 | ★☆☆☆☆ | 只告訴你「誰發的」，不是「內容是什麼」 |
| L2 | Caption / 標題 | ★★☆☆☆ | 作者為 engagement 寫的觀點，常操縱 |
| L3 | Transcript | ★★★★☆ | 真實對白，但慢節奏片對白少會缺 |
| L4 | VLM 視覺 | ★★★★★ | 看畫面真相，不被 caption 操縱 |

實測教訓：一支「Eric Luis 咖啡 reel」caption 寫 *"pov: doing the most..."*（故意神秘），只看 caption 會判成生活 vlog，L4 VLM 才看出真實是 coffee tutorial。**這正是 Vibe Reader 沒有的軸**——Vibe Reader 只吃 transcript（L3），沒有 L4 視覺交叉驗證，所以純視覺敘事或 caption 操縱的內容它抓不到真相。

### 4.2 observation vs. inference 分離（抗幻覺）

反解 prompt 明文規定（逐字）：

- *"只講你『真的在這支影片看到／聽到』的。看不到、聽不清就明說『不確定』，不要用『短影音通常會…』來補。"*
- *"把『觀察』（畫面/聲音裡的事實）和『推論』（你的解讀）分開標清楚。"*

對照 §3.3：Vibe Reader 的卡片把「講者宣稱」平鋪成事實敘述；Reel Scout 強迫把兩者分開標記。

### 4.3 cite-your-evidence（時間戳舉證）

- *"講『卡點』要舉證：指出哪個動作／剪接對齊哪一拍，並判斷是『刻意設計』還是『剛好時間重合』；分不出來就說『只是時間重合』，不要直接叫卡點。"*
- *"畫面裡的店名／招牌／品牌字，逐字讀出你『實際看到的字』，不要替換成你知道的相似品牌名。"*

對照 §3.2：Vibe Reader 的時間戳可以超出影片長度沒人擋；Reel Scout 的規則是「主張要能指回它依據的那一拍，指不出來就降級」。**這正是同一條軸上兩種對待方式**——一個放任、一個強制舉證。

（誠實補一句：Reel Scout 的護欄也承認殘留感知型錯誤——「卡點」「招牌看錯字」這類，靠舉證規則逼收斂、最後仍要人回去核。差別是它**明說要人核**，Vibe Reader 是**免責讓你自己承擔**。）

### 4.4 逐 chunk 語言重偵（語言保真）

Whisper `large-v3` 在長檔會把後段的另一語言「翻譯」回鎖定的語言（中英夾雜訪談，英文賓客的話會被攪成亂碼中文）。Reel Scout 的解法：`WHISPER_MULTILINGUAL=1 WHISPER_CHUNK_LENGTH=15` 逐 chunk 重偵語言，40 分鐘中主英賓訪談的 latin 字元還原率 **56%→90%**（實測）。Vibe Reader 宣稱翻 14 種語言，但**未揭露**它怎麼處理同一支影片內的語言切換——而這正是最容易失準的地方。

---

## 5. 逐面向對照

| 面向 | Vibe Reader | Reel Scout | 誰在這面向更「準」 |
|---|---|---|---|
| 忠實轉述原話 | ✅ 卡片確實還原講者原話 | ✅ transcript 逐字 | 平手 |
| 觀察/推論分離 | ❌ 平鋪成事實 | ✅ 明文強制分離 | **Reel Scout** |
| 時間戳精確度 | ❌ 自己 share 有超界/重疊 | ⚠️ 待實測（有舉證規則） | **Reel Scout（機制上）** |
| 抗 caption 操縱 | ❌ 只吃 L3，無視覺層 | ✅ L4 VLM 交叉驗證 | **Reel Scout** |
| 純視覺/無對白內容 | ❌ 無 transcript 就無料 | ✅ VLM 抓視覺真相 | **Reel Scout** |
| 語言切換保真 | ⚠️ 宣稱 14 語，機制不明 | ✅ 逐 chunk 重偵，有實測數 | **Reel Scout** |
| 精準度問責 | ❌ ToS 免責 | ✅ 明說「要人回去核」 | **Reel Scout** |
| **易用性 / 零設定** | ✅ 一鍵、手機、給一般人 | ❌ CLI、需 ffmpeg/yt-dlp、給技術用戶 | **Vibe Reader** |
| **長內容消費體驗** | ✅ swipe 卡片、跳原文、追問 | ❌ 不是為「讀」設計 | **Vibe Reader** |

**公允結論**：在「精準度」這條軸上，Reel Scout 幾乎全面領先——因為它的整個設計目的就是**保真**（給創作者當研究依據，錯了會拍錯片，代價高）。但這不代表 Vibe Reader 差，而是它的目標函數是**降低閱讀摩擦**（給讀者省時間，偶爾一張卡不精確，代價低到讀者容忍）。**Vibe Reader 用精準度換易用性，這對它的使用情境是合理取捨**——問題只在於它的 marketing 把這個取捨講反了（宣稱高保真，實則以易用為先且 ToS 免責）。

---

## 6. Reel Scout 可以從這次比較借鑑什麼

1. **「時間戳超界」是可自動化的 QA 檢查**：Vibe Reader 的缺陷（clip end > 影片長度）用一行比對就抓到。Reel Scout 可以把「任何 cite 的時間戳必須 ≤ 影片實際長度、start < end、不得嵌套」做成 pipeline 的 assert，直接把 §4.3 的舉證規則變成**機器可驗證**而非只靠模型自律。
2. **把「這是講者宣稱」標記可以產品化**：§3.3 顯示連做得不錯的 Vibe Reader 都會把宣稱平鋪成事實。Reel Scout 的 observation/inference 分離如果輸出成**帶標籤的結構化欄位**（`claim` vs `observed`），就是一個 Vibe Reader 沒有的護城河。
3. **L4 視覺層是差異化賣點**：Vibe Reader 純吃 transcript，對純視覺 / caption 操縱內容失準。Reel Scout 的 VLM 交叉驗證值得在對外定位時講清楚——這是「拆得準」相對「讀得快」的結構性優勢。

---

## 附錄 A：實測 rubric（後手，你有空再回填）

論述先交，實測留後手。以下是把上面的軸變成可打分的評分表。挑好的測試影片見附錄 B。

**評分方式**：每項 0–3 分（0＝完全失準，1＝多處錯，2＝小錯可接受，3＝準確）。同一支影片、兩個工具各跑一次、逐項對照。

| # | 評分項 | 怎麼驗 | Vibe Reader | Reel Scout |
|---|---|---|---|---|
| 1 | 時間戳不超界 | 每個 cite 的 end ≤ 影片長度？start<end？ | （已知有超界，見 §3.2） | 待跑 |
| 2 | 時間戳落點正確 | 隨機抽 5 個時間戳，跳過去看內容對不對得上該卡主張 | 待跑 | 待跑 |
| 3 | 原話忠實度 | 抽 3 張卡，逐句比對 transcript，有無捏造講者沒說的 | 待跑 | 待跑 |
| 4 | 觀察/推論分離 | 卡片/輸出有無把「講者宣稱」標記成宣稱而非事實 | （已知：無，見 §3.3） | 待跑 |
| 5 | 抗 caption 操縱 | 找一支 caption 與內容不符的片，看輸出跟著 caption 走還是跟著內容走 | 待跑 | 待跑 |
| 6 | 語言切換保真 | 用中英夾雜片，看非主語言段落有無被攪亂 | 待跑 | 待跑 |
| 7 | 幻覺結構 | 輸出有無「無中生有」一個影片裡不存在的段落/章節 | 待跑 | 待跑 |

**注意軸不對齊**：Reel Scout 設計給短影音、Vibe Reader 給長影音。要 apples-to-apples，測試影片得落在兩者重疊區（Vibe Reader 能吃、Reel Scout 也能跑的 YouTube 影片）。第 1、3、4 項我已能從 Vibe Reader 公開 share 預填（見 §3），只差把 Reel Scout 側跑出來對照。

## 附錄 B：建議的測試影片

**首選 — Boris Cherny / Lenny's Podcast（87 分, EN）**
- Vibe Reader 已有公開 v2 share（12 張卡）：`https://share.vibe-reader.com/v2/article/cH8uIA6GTA4PUibZU1fFVw` ——**你甚至不用跑 Vibe Reader，它的輸出已經公開**。
- Reel Scout 側：`reel-scout analyze "<該 YouTube URL>"`（長片、whisper 會慢，可加 `--skip-vision` 先比 transcript/結構層）。
- 為什麼選它：Vibe Reader 側零成本（公開）、內容是技術訪談（宣稱易驗證，如「200% productivity」「shipping 10-30 PRs daily」可查證是不是講者原話）、英文（排除翻譯變因，先測純結構保真）。

**次選 — 一支中英夾雜訪談（測第 6 項語言保真）**
- 專打 Reel Scout 的 §4.4 賣點 vs Vibe Reader 的「14 語」宣稱。
- 需要一支 Vibe Reader 也吃得下、且有語言切換的長片；若找不到公開 share，這支就是真正要動手跑兩邊的那一支。

**若要測 Reel Scout 主場（短影音, 第 5 項抗操縱）**
- 用 §4.1 的 Eric Luis 咖啡 reel 類型（caption 故意神秘）。但要先確認 Vibe Reader 是否吃 Shorts——目前**無法確認它支援 Shorts**，這項可能只能單跑 Reel Scout。

---

## 附錄 D：Reel Scout 主場示範（實跑，2026-07-16）

論述型 case study 的 Vibe Reader 側靠一手 artifact（§3），Reel Scout 側原本只有「設計即護欄」的機制論述。這裡補一支**本機實跑**，把 §4 的護欄從「宣稱」變成「示範」。**這不是 head-to-head**（不把 Reel Scout 丟上 Vibe Reader 的長內容主場硬打），而是在 Reel Scout 主場——一支純視覺短片——展示它的精準度機制長什麼樣。

**跑什麼**
- 影片：`Latte art in STARBUCKS`（YouTube Short，25 秒，`gYmr6sWumCQ`；uploader「face」，description 空）
- 指令：`reel-scout analyze "<url>" --resolution 1080 --score`
- Backend：**全本機**——faster-whisper `large-v3` + Ollama VLM `qwen2.5vl:7b` + Ollama LLM `qwen2.5:14b`，零 API key、零外送。
- 產出：12 keyframes、VLM 逐幀描述、merged 結構化欄位、Score **6.3**（hook 6.5 / visual 7.0 / pacing 5.5 / structure 6.0）。

### D.1 這支正好是「L3 弱、L4 扛」的純視覺片

Whisper 轉出來的 **transcript 是空的**——這支沒口白、純沖煮視覺 + BGM。對照 §4.1 的 4 層信號：L3（transcript）這層在這支**給不出料**。這正是 cheatsheet 裡「edocolala 191s 只有 outro」的同型情境。

> **結構性對照**：Vibe Reader 是 transcript-based（吃 L3）。一支零口白的短片，對它幾乎**無料可摘**——它的整條 pipeline 建立在「有話可轉、有話可摘」。而 Reel Scout 的 L4 VLM 在這支獨力產出了完整的逐幀讀解。
> （誠實標註：我**沒有**實際拿這支去跑 Vibe Reader——它未確認吃 Shorts，且我不註冊。上句是從「它是 transcript-based」推的**機制推論**，非實測結果。）

### D.2 cite-時間戳 + 逐字讀招牌字（§4.3 護欄的實證）

12 個 keyframe，每一條 VLM 描述都**錨在具體秒數**，而且逐字讀出畫面上的字——不是複述標題。節錄原始 VLM 輸出：

| 秒數 | VLM 讀到的畫面（節錄，逐字） |
|---|---|
| 0.1s | 圍裙上讀到文字 **"Aimee"** |
| 5.7s | barista 倒奶泡；圍裙有 **Starbucks logo** |
| 7.6s | 黑色制服，logo + 文字 **"Coffee Master"** |
| 11.4s | 拉花中；黑圍裙 Starbucks logo + **"Coffee Master"** |
| 22.8s | 特寫手持拉花杯，泡沫 **leaf design** |

> **關鍵驗證**：merged 輸出的 `topics` 有「Starbucks」，但這**不是**把標題（L2「Latte art in STARBUCKS」）洩進來——原始逐幀描述顯示 VLM 在 5.7s–19s **獨立讀出圍裙上的 Starbucks logo 與「Coffee Master」字樣**（`--resolution 1080` 的 on-screen-text 解析生效）。這就是 §4.3「畫面裡的招牌字，逐字讀出實際看到的字」的機制在跑，而且**每個主張都指得回它依據的那一秒**——對照 §3.2 Vibe Reader 時間戳可以超出影片長度沒人擋。

### D.3 一個誠實的失準：感知錯會傳播（§4.3「仍要人回去核」的實證）

不粉飾：**0.1s 那幀 VLM 把場景講成 "holding a mug of tea"**——其實是奶泡 / 咖啡準備，不是茶。而且這個錯**傳播**進了最終 merged 的 hook 描述（`opening_text` 出現 "holding a mug of tea and a pitcher of milk"）。

> 這正是 §4.2/§4.3 早就明說的：舉證護欄能逼模型收斂，但**殘留感知型錯誤仍在,最後要人回去核**。Reel Scout 的立場不是「我不會錯」,而是「我把每條主張錨到可核的時間戳、明說要人核」——對照 Vibe Reader ToS「不保證準確、錯了算你的」(§3.5)。**同樣會錯,差別在問責姿態:一個可審計 + 要你核,一個免責 + 甩鍋。**

### D.4 這支示範證了什麼、沒證什麼

| 證了 | 沒證（不overclaim） |
|---|---|
| L4 VLM 在純視覺片獨力產出逐幀讀解（L3 空） | 沒實跑 Vibe Reader 這支（機制推論其失準,非實測） |
| 每條主張錨到具體秒數,可逐幀審計 | 單支示範,非統計樣本 |
| 逐字讀出畫面招牌字（Starbucks/Coffee Master/Aimee）,非複述標題 | Reel Scout 的時間戳精確度未做 §附錄A 第2項的隨機抽驗 |
| 殘留感知錯（"tea"）會傳播 → 實證「仍要人核」 | 未測抗 caption 操縱（需 caption 與內容衝突的片） |

**一句話**:Reel Scout 的精準度不是「不會錯」,是「**錯得可審計、每條錨得回時間戳、明說要人核**」——這支 25 秒的實跑把 §4 的護欄從紙上規則變成了可看的輸出。

_實跑資料落在本機 `data/reel_scout.db`（video_id `554c6989a37e0ccc`）。_

---

## 附錄 C：資料出處與未能確認項

**Vibe Reader 側**（全部公開、未註冊未安裝）：landing (vibe-reader.com)、iOS App Store id6748338132、Google Play com.seekrlab.reelit、Chrome Web Store kbikkdaihbmodkofbcebllhklkjpmemn、share.vibe-reader.com（真實 share 卡片）、iubenda 隱私政策、legal.vibe-reader.com/tos.html。

**未能確認（不臆測，明列）**：
- Vibe Reader 的 transcript 來源（YouTube 字幕 vs ASR）、哪個 LLM 處理哪一段、時間戳推導方式——皆黑箱。
- 是否支援 YouTube Shorts、有無硬性長度上限。
- in-app 的「Deep Dive」「Ask AI」行為（僅 app 內，share 頁看不到，未安裝）。
- 時間戳超界是系統性還是取樣偶發（只驗 3 支；2/3 有超界，pattern 已可重現，但更大樣本會更強）。
- Google Play 逐則評論（JS 渲染，維持 read-only 未抓）；「曾被 Apple Featured」「評論全 5 星」為廠商 Threads 自述，未獨立查證。
- 使用者/媒體對「精準度」的評價：**查無**——App 太新（iOS 2025-11 上線，iOS 僅 1 則評分、Chrome 3 則）。本 case study 的精準度判斷因此**全建立在一手 artifact（share 卡片 + 時間戳）**，非使用者口碑。

_Reel Scout 側資料取自本 repo `prompts/`（signal-reliability-cheatsheet.md、hook-reverse-structure.md）與 README。_
