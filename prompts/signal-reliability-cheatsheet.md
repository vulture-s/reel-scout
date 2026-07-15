---
cssclasses:
  - vulture
---

# 4 層信號可靠度 — 拆 reel 的資料來源分層 cheat sheet

> **用途**：拆爆款 reel 的時候，不能單看 caption 就下結論（會被誤導）。這份是「資料來源可靠度的分層判斷」 — 學界做多模態預測、業界談 engagement signal，但**全網沒人系統化整理過「資料來源可靠度分層」這個切角**。
>
> **核心一句話**：拆 reel 不是看 caption，是用工具看視覺真相 + 多層信號合一。

---

## 4 層分層（從最弱到最強）

| 層 | 信號來源 | 可靠度 | 為什麼這個分數 |
|----|---------|-------|------------|
| **L1** | Uploader 名稱 | ★ ☆ ☆ ☆ ☆（最弱） | 帳號名只是「誰發的」，不告訴你「內容是什麼」 |
| **L2** | Description / Caption | ★ ★ ☆ ☆ ☆（中等偏低） | Caption 是「作者的敘述觀點」，常為了 engagement 操縱 |
| **L3** | Transcript（語音轉文字） | ★ ★ ★ ★ ☆（強） | 真實對白內容，但慢節奏 reel 對白少會缺資料 |
| **L4** | VLM 視覺分析 | ★ ★ ★ ★ ★（最強） | 看畫面真相，不被 caption / 標題操縱 |

**判讀原則**：**4 層越合越準**。只看 L1+L2 = 容易被誤導，加 L3+L4 才看到真相。

---

## 每一層的具體內容

### L1 — Uploader 名稱（最弱）

| 你能看到的 | 限制 |
|-----------|------|
| 帳號名稱（@username） | 不代表內容主題 |
| 顯示名稱 | 可以隨時改 |
| Bio 簡介 | 不更新就過時 |

**典型誤判**：用 uploader 名稱猜內容主題。例如「@coffee_master」可能 80% 內容是咖啡，但這支特定 reel 可能是旅遊。

**音響訪談案例的 L1 教訓**：3 支參考 reel 在 Reel Scout 跑之前用 uploader 名稱 mapping 全錯 — 猜不出來小建是炸雞創作者、Eric Luis 是咖啡 tutorial。

---

### L2 — Description / Caption（中等偏低）

| 你能看到的 | 限制 |
|-----------|------|
| 影片描述文字 | 作者寫的「觀點」，不一定符合內容 |
| Hashtags | 為了 reach 而塞，不代表主題 |
| 標題（Title） | 可以為 clickbait 設計 |

**典型誤判**：完全相信 caption。

**音響訪談案例的 L2 教訓**：Eric Luis 的 caption 是「pov: doing the most...」 — 完全沒提這支是咖啡 tutorial。如果只看 caption 會以為是生活 vlog，但 VLM 看出真實是「coffee preparation tutorial」。

**Caption 為什麼會誤導**：
- 創作者為了 engagement 寫 hook，不是寫摘要
- Hashtag 是為了 reach（會塞流行 tag）
- 短影音平台鼓勵「神秘感」caption，讓人點進去看

---

### L3 — Transcript（語音轉文字，強）

| 你能看到的 | 限制 |
|-----------|------|
| 完整對白文字 | 慢節奏 reel 對白少會缺資料 |
| 講話時長分配 | 不適合純 BGM / 純視覺 reel |
| 語氣關鍵字 | 翻譯有時失準 |

**Transcript 強在哪**：
- 直接是「真實口述內容」，不是作者寫給觀眾看的描述
- 能抓到 caption 不會寫的東西（例如產品型號、推薦理由、實際使用情境）
- 是 4 層裡「主題識別」最準的那層

**何時 L3 還是不夠**：
- 慢節奏 reel 對白少（例如 edocolala 191s 影片只 transcribe 出韓文 outro）
- 純 BGM / 純視覺敘事 reel（沒有對白）
- 對白多但口音重 / 多語混雜（轉錄錯誤率高）

**這時要靠 L4 補**：純視覺敘事 reel 的「主題真相」只能用 VLM 抓。

---

### L4 — VLM 視覺分析（最強）⭐

| 你能看到的 | 為什麼最強 |
|-----------|---------|
| 每個關鍵 frame 在做什麼 | 直接看畫面真相 |
| 產品 / 場景 / 動作識別 | 不被 caption 操縱 |
| 視覺結構（hook frame / climax frame / outro frame） | 跨對白語言的通用識別 |
| 視覺密度（單位時間資訊量） | 解釋為什麼會火 |

**VLM 強在哪**：
- **不需要對白也能識別主題**（純視覺敘事 reel 唯一辦法）
- **不被 caption 操縱**（caption 寫 A、畫面在做 B，VLM 看到 B）
- **能識別「視覺奇觀」**（hook frame 為什麼會抓住人，VLM 能拆解）

**VLM 的限制**：
- 抓不到細微對白資訊（例如「這條線材是 XX 廠的 OO 型號」這種需要對白才知道）
- 對「品牌 logo / 產品型號」識別準確度有限（需要 reference 圖輔助）
- 跨幀理解較弱（單張 frame 強，整支影片的敘事弧線需要其他層補）

**所以最強做法**：L3 + L4 合用 — Transcript 抓對白真相 + VLM 抓視覺真相，兩層交叉驗證。

---

## 4 層怎麼合一（實戰流程）

### Step 1：先看 L4（VLM 視覺）
- 拿到 reel 後第一動 — 用 Reel Scout（或上傳給 Claude / Gemini）跑 VLM 描述
- 問題：「這支 reel 視覺上在做什麼？keyframe 1 / 2 / 3 各是什麼？」
- 拿到「視覺真相」當 baseline

### Step 2：對照 L3（Transcript）
- Reel Scout 自動產 transcript，或用 Whisper 跑
- 對照 VLM 描述 — 對白跟畫面說同一件事嗎？
- 不一致的地方記下來（這是有趣的訊號）

### Step 3：交叉驗證 L2（Caption）
- 看 caption 寫了什麼
- 跟 L3 + L4 合起來看 — Caption 是「誠實摘要」「操縱 hook」還是「完全誤導」？
- Caption 跟 L3/L4 一致 = 創作者誠實型
- Caption 跟 L3/L4 不一致 = clickbait / 神秘感策略

### Step 4：L1（Uploader）只當 metadata
- 看 uploader 主題（從帳號其他 reel 推估）
- 跟這支 reel 主題對得上嗎？
- 對得上 = 該創作者的「主軸內容」
- 對不上 = 該創作者的「實驗內容」（重要訊號 — 這支可能是他想拓展的新方向）

---

## Cheat Sheet 快速參考

```
拿到一支爆款 reel，4 層判讀順序：

L4 VLM 視覺 → 「畫面在做什麼」（最強基線）
   ↓
L3 Transcript → 「對白說什麼」（驗證 L4）
   ↓
L2 Caption → 「作者敘述什麼」（看是否操縱）
   ↓
L1 Uploader → 「誰發的 + 是不是主軸」（最弱，只當 metadata）

合一判斷：
- 4 層一致 = 該 reel 真實主題 ✅
- L4+L3 一致、L2 操縱 = 該 reel 是「掛羊頭賣狗肉」型 hook
- L4 跟 L1 不對齊 = 創作者實驗新方向，重要訊號
- 只看 L1/L2 下判斷 = 80% 機率被誤導 ❌
```

---

## 工具對應（4 層各用什麼跑）

| 層 | Reel Scout | 不用 Reel Scout 的 fallback |
|----|-----------|---------------------------|
| L1 | metadata 直接抓 | 看 IG / TikTok / YouTube 帳號頁 |
| L2 | metadata 直接抓 | 看 caption 欄位 |
| L3 | Whisper 內建 | 上傳 MP4 給 Claude / Gemini 跑 transcript |
| L4 | VLM 內建（Ollama / Claude API） | 上傳 MP4 給 Claude（最強）／ Gemini（YouTube 強）／ ChatGPT |

**沒有 Reel Scout 時**：用 cobalt.tools 下載 MP4 後上傳給 Claude.ai web，請 Claude 同時跑「描述每個 keyframe 在做什麼」+「轉錄對白」+「caption 跟畫面有沒有對齊」三個任務，等於人工版 4 層分層。

---

## 真實案例：一支音響訪談 reel 的 3 支參考片

| Reel | L1 Uploader | L2 Caption 寫什麼 | L4 VLM 看到什麼 | 4 層合一結論 |
|------|------------|----------------|--------------|------------|
| 小建炸雞 reel | @nicholas_xxx | 一段炸雞食譜文字 | 炸雞製作過程 + hook 是滴油慢動作 | 一致 — 真實是炸雞料理 reel，hook 用視覺奇觀 |
| Eric Luis 咖啡 reel | @ericluis_xxx | "pov: doing the most..."（神秘感） | 咖啡準備教學完整流程 | L2 操縱 — 真實是 coffee tutorial，caption 故意神秘 |
| edocolala 黑膠 reel | @edocolala | 韓文標題 | 慢節奏黑膠播放 + 環境鏡頭 | L3 弱（對白少）+ L4 強（純視覺敘事） |

**這 3 支共同教訓**：
- 只看 L1（uploader 名稱）— 完全猜不出來各自是什麼題材
- 只看 L2（caption）— Eric Luis 會被誤導成生活 vlog
- 只看 L3（transcript）— edocolala 191s 對白不足
- 加上 L4（VLM）— 3 支真實主題都浮現

**這也是「4 層信號可靠度」這個框架誕生的原因** — Reel Scout 跑這 3 支參考片驗證出來的教訓。

---

## 沒有 Reel Scout 時怎麼跑

### 手動跑 4 層分層的 prompt（給 Claude.ai web）

```
我上傳了一支 reel 的 MP4，請幫我跑「4 層信號可靠度分層」：

L4 — VLM 視覺真相：
- 描述第 5 秒 / 第 15 秒 / 第 30 秒（每 10 秒抽一張）keyframe 在做什麼
- 整支 reel 視覺上的主題是什麼
- Hook frame（前 3 秒）有什麼視覺奇觀

L3 — Transcript 對白真相：
- 完整轉錄對白
- 對白主要訊息是什麼
- 對白跟 L4 視覺真相一致嗎？

L2 — Caption 對照：
[貼上 IG / TikTok / YouTube 上的 caption 文字]
- Caption 跟 L3 + L4 合起來的真相一致嗎？
- 如果不一致，是「誠實 hook」「故意神秘」還是「完全誤導」？

L1 — Uploader metadata：
[貼上 uploader 帳號名稱 + 他的其他幾支 reel 主題（如果有看）]
- 這支 reel 的主題跟該創作者主軸內容對齊嗎？
- 對齊 = 主軸延伸 / 不對齊 = 創作者實驗新方向

最後給我「4 層合一結論」：
這支 reel 的「真實主題」是什麼？(跟 caption 寫的是不是同一件事)
```

---

## 取得層對比：GUI vs 工具（繞得過 403，繞不過逐字＋落檔）

4 層信號講的是「拿到影片後怎麼判讀」；但**先要拿得到**。各路徑在「取得層」跟「真的看影片」上天花板差很多：

| 路徑 | 取得層（繞 403?） | 真「看」影片 | 逐字＋時間戳 | 進 pipeline／落檔 |
|------|------|------|------|------|
| **Gemini GUI** | ✅ Google 自家 | ✅ 原生 multimodal | ❌ 近似、無硬時間軸 | ❌ 手動複製 |
| **ChatGPT GUI** | 〜 browsing 撈 caption | ❌ 只撈字幕/網頁 | ❌ | ❌ 手動 |
| **Reel Scout（本機）** | ❌ yt-dlp 卡 403 ＊ | ✅ Whisper＋VLM 融合 | ✅ Whisper 逐字＋時間 | ✅ 落結構化檔 |
| **Gemini API** | ✅ Google 自家 | ✅ 原生 | ❌ | ✅ 可自動化 |

＊ 403 修法：`pip install -U yt-dlp`

**三條結論**：
1. 要**快速理解、零設定** → Gemini GUI（貼 URL 叫它逐段拆）。ChatGPT GUI 對「無 caption＋內崁字幕」的片**看不到，別用**。
2. GUI 共同天花板 = 手動＋非逐字＋無精準時間軸＋進不了 pipeline。它解「這支在講什麼」，不解「結構化存進 arkiv／Reel Scout」。
3. 要**逐字＋時間戳＋落檔** → 只有本機 Whisper pipeline 給得了。GUI 繞得過取得層，繞不過這道頂。

→ 按「快速理解 vs 結構化保真」分流，沒有單一工具全包。

---

## 跟其他附件的關係

| 附件 | 跟 4 層信號的關係 |
|------|---------------|
| **hook_反推結構.md** | 拆 hook 前先跑 4 層信號取得真實主題 |
| **劇本拆解.md** | 抽出來的骨架要對齊「真實主題」（不是 caption） |
| **03_素材取得 SOP** | Path C（Reel Scout）內建 4 層信號分層 |
| **Reel Scout Quick Start** | 工具的核心 framework 之一 |

---

_最後更新：2026-05-20_
_4 層信號可靠度框架來源：Reel Scout（跑 3 支參考片驗證）_
_本框架在 Reel Scout 開發過程整理出來_
