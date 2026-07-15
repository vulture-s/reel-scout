---
cssclasses:
  - vulture
---

# 分鏡視覺化 Prompt（鏡頭表 → AI 生成分鏡圖）

> **用途**：拿到通過焦點審計的鏡頭表後，把每一鏡寫成 AI 圖像生成工具能吃的 prompt，產出 storyboard 用的分鏡圖。
>
> **比直接寫 prompt 的價值**：避免「AI 出來像塑膠玩具版」「兩個鏡頭看起來不在同一個世界」這兩個 AI 分鏡最常見的崩壞。
>
> **位置**：研究（Hook 反推）→ 企劃（劇本拆解）→ 守門（焦點審計）→ **執行（分鏡視覺化）**

---

## Step 0：硬規則 — 沒參考圖就不要生（比公式更重要）

⭐ **這一條規矩比下面所有 prompt 公式都重要。先看這條再往下。**

任何有「實體主體」的鏡頭 — 產品、招牌、制服、品牌 logo、特定場域 — **必須先準備實物參考圖**，跟 prompt 一起上傳給 AI。

**為什麼**：AI 訓練數據裡你的品牌大概率不存在（小品牌幾乎一定沒有）。用文字描述出來會像「塑膠玩具版本」 — Logo 字型錯、產品比例錯、招牌風格錯。

**參考圖怎麼取得**：
- 自己手機拍實物 — 最準（光線跟拍攝環境一致）
- Google 搜該品牌官方圖 — 次選
- 場域實拍 — 牆面、招牌、制服都拍一張 reference

**沒有實體主體的鏡頭**（純情境、純情緒、純景色）可以直接寫 prompt，不需要參考圖。

---

## Step 0.5：多鏡頭連戲 — 第二張起用「視覺合約」鎖場景

⭐ **第二個必看的硬規則。AI 分鏡最常崩在「看起來不在同一個房間」。**

生第一張當「視覺合約」 → **第二張上傳第一張當 reference**，後續每張都引用第一張。

**比文字描述「同一個房間 / 同個小孩 / 同個光線」精準 10x**。光色、服裝、比例、空間質感都會自動 lock 住。

**操作流程**：
1. 生第 1 鏡（最具代表性的那一鏡，通常是主場景）— 用完整 prompt
2. 確認第 1 鏡產出符合預期 — 不對就重生
3. 生第 2 鏡 — 上傳第 1 鏡圖片 + 寫「reference image: scene 1, keep same character / lighting / environment」+ 第 2 鏡的差異描述（新角度 / 新動作）
4. 生第 3 鏡起 — 一律 reference 第 1 鏡（不是 reference 上一鏡，避免錯誤累積）

**例外**：場景明確切換的鏡頭（室內 → 戶外）不 reference 第 1 鏡，從新的 anchor 生（通常是該新場景的第一鏡）。

---

## 核心公式

```
[主體 + 動作 + 情緒] + [景別 / 角度] + [焦段] + [光線] + [風格]
```

兩種強度版本：

| 版本 | 字數 | 用途 | 速度 |
|------|------|------|------|
| **Minimal** | 15-20 字 | 草稿批次生成（10+ 鏡同時跑） | 快 |
| **Marketing Grade** | 35-50 字 | 客戶交付 / 對外發佈 | 慢但細節精準 |

---

## Prompt（複製貼上用）

```
我要把鏡頭表轉成 AI 圖像生成 prompt。

我的鏡頭表：
[貼上劇本拆解 prompt 產出的鏡頭表，含景別 / 焦段 / 視角 / 內容欄位]

主體 / 場域資訊：
- 主要角色：[人物特徵 — 年齡 / 體型 / 服裝 / 髮型 / 表情調性]
- 場域：[室內 / 戶外 / 混合；具體環境描述]
- 品牌調性：[暖色 / 冷色 / 高對比 / 柔和；參考既有品牌視覺]
- 是否有產品實體：[YES — 列出產品名稱 / NO — 純情境]
- 參考圖準備狀態：[已有 / 還沒拍 / 不需要]

請按以下格式為每一鏡產出 prompt：

## Shot [#] — [簡述]

### Minimal 版本（草稿用，15-20 字）
[單行英文 prompt]

### Marketing Grade 版本（交付用，35-50 字）
[完整英文 prompt，含光線 + 質感 + 細節]

### 參考圖需求
- 需要實物參考：[YES / NO]
- 連戲 reference：[第幾鏡 / 不需要]
- Negative prompt 重點：[該鏡特別要避開的詞]

### 生成順序建議
- 在 Step 0.5 連戲鎖場流程中，這鏡是 anchor / 跟隨 / 獨立場景

公式套用準則：
- 景別用標準縮寫（ECU / CU / MCU / MS / MLS / LS / ELS）翻成完整英文（"extreme close-up" / "close-up" / etc）
- 焦段給具體 mm 數（"35mm lens" / "85mm portrait lens, shallow depth of field"）
- 視角配對應英文（"low angle" / "eye level" / "POV first-person" / "bird's eye"）
- 光線給時段 + 方向（"golden hour backlight" / "soft window light from left"）
- 風格用品牌固定 style suffix（見下方品牌套版）

審計重點：
- Minimal 版本不要超過 25 字（會稀釋核心特徵）
- Marketing Grade 不要超過 60 字（會讓 AI 找不到重點）
- Negative prompt 必加（特別是 "blurry, overexposed, plastic look, stock photo feel"）
```

---

## 風格 Style Suffix 套版（直接複製貼上）

不用每次自己想風格，這幾組直接套：

### A. Storyboard 草稿風（Ghibli 手繪感，跑批用）
```
Japanese manga storyboard sketch style, soft pencil lines, Ghibli-inspired illustration, delicate fine lines with subtle gray tone shading, white paper background, warm tender atmosphere, hand-drawn animation concept art aesthetic
```
適合：分鏡稿、客戶提案、批次跑 10+ 鏡求一致性。

### B. Cinematic 高質感成品風（Marketing Grade）
```
cinematic photography, high dynamic range, authentic color science, production-ready visual quality, photorealistic, shallow depth of field, professional cinematography, film-like color grading
```
適合：最終交付、IG/YouTube 對外發佈、品牌主視覺。

### C. Anti-AI 質感（避免「一看就 AI」的塑膠感）
```
natural skin texture with subtle imperfections, authentic lighting variations, asymmetric composition, handheld camera feel, film grain texture, unposed candid moment
```
適合：人物 lifestyle、紀實感場景、避免 AI 質感的場合。

### D. 通用 Negative Prompt（任何鏡都加）
```
blurry, overexposed, harsh flash, cold blue tones, plastic look, CGI, cartoon, watermark, text overlay, cluttered background, stock photo feel, oversaturated, unnatural skin texture
```

---

## 使用範例（橡子幼兒園 Shot 1 — Hook 開場）

> 註：本範例採虛構幼兒園「橡子」做案例 — 公開附件不揭露真實客戶名。實際使用時把品牌欄填自己的真案。

### Input（從劇本拆解產出的這一鏡）

```
| # | 時間 | Act | 景別 | 焦段 | 視角 / 運鏡 | 內容 | 為什麼這樣拍 |
| 1 | 0-2s | Hook | ECU | 35mm | POV / handheld | 小朋友手伸向草地泡泡 | Hook：第一秒非預期視角 |

主體 / 場域資訊：
- 主要角色：3-5 歲小朋友，幼兒園制服（柔淡米色 polo），自然頭髮
- 場域：園所戶外草地，早晨自然光
- 品牌調性：溫暖、自然、純真；參考園所現有形象色為柔淡米色 + 嫩芽綠
- 是否有產品實體：YES — 園所制服 + 招牌（已拍實物照）
- 參考圖準備狀態：已有制服 + 場地 + 招牌照
```

### Expected Claude Output

```
## Shot 1 — Hook 開場：小朋友手伸向草地泡泡

### Minimal 版本（草稿用）
Child's hand reaching toward soap bubbles on grass, POV first-person, 35mm handheld, soft morning light, Japanese manga storyboard sketch style, Ghibli, white bg

### Marketing Grade 版本（交付用）
Extreme close-up of a young child's hand gently reaching toward floating soap bubbles above sunlit grass, first-person POV perspective, 35mm lens with subtle handheld shake, early morning diffused light from the left, soft warm beige tones, kindergarten uniform sleeve visible at frame edge, cinematic photography, natural skin texture, shallow depth of field, film grain

### 參考圖需求
- 需要實物參考：YES（園所制服特寫 + 園所戶外草地實景 + 園所招牌）
- 連戲 reference：本鏡是 Hook 的 anchor，作為 shot 2-3 的視覺合約
- Negative prompt 重點：blurry, overexposed, harsh flash, plastic look, CGI cartoon, watermark, cluttered background, stock photo feel

### 生成順序建議
這鏡是整支片的 anchor 之一（Hook Act 的第一鏡）。先生這鏡 → 確認制服色調 + 場地光線正確 → 用這鏡 reference 生 Shot 2（小朋友奔跑穿過走廊）。

Shot 2 的 prompt 加：
"reference image: scene 1, keep same kindergarten uniform color, same morning light direction, same soft warm beige tone palette"
```

---

## 何時用這個 Prompt

**最有 ROI 的時機**：
1. **鏡頭表已通過焦點審計** — 不要在還會被砍鏡的階段生圖（浪費）
2. **Storyboard 草稿要批次跑** — 用 Minimal 版本一次 10+ 鏡
3. **客戶要看 visual reference** — 用 Marketing Grade 版本 + 連戲 reference

**不要在這個階段用**：
- 還沒拍實物參考圖 — 先去拍，沒參考圖等於白生
- 鏡頭表還沒定稿 — 鏡頭表會改，生圖會白費

---

## 進階變體

### Variant 1：純情境 / 沒實體主體的鏡（純情緒 / 純景色）

如果該鏡沒有實體主體（例如「黃昏空鏡」「下雨街道」），Step 0 硬規則不適用，但仍建議：
- 提供「色調 reference」（任一張你想要的調色截圖）
- 在 prompt 加「mood reference: [描述 reference 來源]」
- 連戲 reference 還是要做（從第 2 鏡起 reference 第 1 鏡）

### Variant 2：產品特寫鏡（產品是主角）

```
產品特寫鏡的 prompt 加強：
- 一定要上傳產品實物照（不接受任何 fallback）
- 加 "macro photography, product detail shot" 風格詞
- 光線指定「side light」或「top-down light」突顯材質
- Negative prompt 額外加 "plastic toy, fake product, branded mockup"
```

### Variant 3：角色一致性跨多鏡（同一個人多場景）

```
角色一致性的特殊處理：
1. 第一鏡用「結構化角色生成模板」明確描述：年齡 / 體型 / 姿態 / 服裝 / 眼神參考（具體名人）/ 環境光色溫
2. 第二鏡起一律 reference 第一鏡，加 "same character as reference image"
3. 如果中間發現角色臉跑掉（AI 失憶），重生那一鏡，繼續 reference 第一鏡（不要 reference 跑掉的那鏡）
```

---

## 工具選擇對照

不同 AI 圖像生成工具對 prompt 長度跟風格的容忍度不同：

| 工具 | 適合場景 | Prompt 長度建議 | 連戲 reference |
|------|---------|--------------|----------------|
| **Artlist AI Toolkit** | 講師工作流，cinematic 高質感 | 30-50 字 | 支援 image-to-image |
| **Nano Banana / Higgsfield** | 角色一致性、場景連戲 | 25-40 字 | 強場景，跨鏡視覺合約 |
| **ChatGPT Image / DALL-E** | 沒訂閱付費工具的 fallback | 20-30 字 | 部分支援 reference |
| **Ideogram V3** | 需要文字 in image（logo / title） | 20-30 字 | 文字優先 |
| **Midjourney** | 風格化、抽象、藝術感 | 20-35 字（含 --ar） | 用 --cref |

**沒訂閱 Artlist 的 fallback**：ChatGPT Plus 內建 DALL-E 圖像生成 + Nano Banana（免費 quota）就能跑完整套，只是質感不如 Artlist Original 1.0。Marketing Grade 版本 prompt 對所有工具都通用，只要把風格 suffix 換成該工具偏好的詞。

---

## 跟其他 Prompt 的關係

| Prompt | 階段 | 跟分鏡視覺化的關係 |
|--------|------|----------------|
| **Hook 反推結構** | 研究 | 提供骨架 |
| **劇本拆解** | 企劃 | 提供鏡頭表 |
| **焦點審計** | 守門 | 提供「通過審計的鏡」 |
| **分鏡視覺化**（本檔） | 執行 | 把通過的鏡轉成生圖 prompt |

順序：**Hook 反推 → 劇本拆解 → 焦點審計 → 分鏡視覺化**

---

## 出 PDF 之後

生完所有分鏡圖之後，組進 Storyboard PDF 模板。見：
- `02_Figma_Storyboard_PDF_模板規格.md` — 排版規格
- 或自己用 Google Doc 排（馬爾科 Mark 推薦的極簡路線，不需要 Figma）

---

_最後更新：2026-05-20_
_Step 0／0.5 硬規則來源：馬爾科 Mark swipe file Move #3, #4_
_公式系統參考：storyboard-pdf-v2 skill camera-prompts-reference.md_
_風格 suffix 套版來自講師實戰工作流的 cinematic（成品交付）+ sketch（storyboard 草稿）兩種模式_
