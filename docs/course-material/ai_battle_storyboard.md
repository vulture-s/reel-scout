# 「AI 內戰：六個 AI 互相入侵服務器」分鏡 + Prompt 還原

- **影片**: https://youtu.be/an7Dbkh7no4
- **片長**: 12 分 54 秒 (774s)
- **語言**: 中文（簡）
- **作者署名**: 林一（最後一句「我是林一，咱們下個視頻見」）
- **內容類型**: AI 科普 + 賽事紀實
- **分數 (reel-scout)**: 6.0（hook=6.5 / info=7.0 / emotion=4.0 / share=6.0）

## 視覺風格總覽

整支影片在「視覺資產」層只用四種素材形態交替——這是這支影片最值得偷的招：

| 形態 | 用途 | 估計成本/工法 |
|---|---|---|
| **LEGO 定格 B-roll** | 解釋抽象概念（AI/駭客/防禦/攻擊） | 多半是 AI 生圖（LEGO Brickheadz 風格）+ 文字疊圖，不是真的拍定格 |
| **真人 talking head** | 過場、強調、人格化 | 桌邊單機位、機械鍵盤、「開發中」立牌 |
| **純文字/極簡漸層卡** | 報技術名詞、模型名、版本號 | Keynote/After Effects 文字動畫 |
| **末尾手繪 cameo** | 結尾自我介紹（Adam / 阿杰 / 小六） | 卡通頭像，2D 風格切換做收尾識別 |

**節奏**：前 30s 全部 LEGO B-roll（hook 階段不讓觀眾看到本人），30s-60s 進入 talking head 帶版本號/模型名，60s 後進入比賽敘事（純文字插卡 + LEGO + talking head 三段並行）。

---

## Scene-by-scene 分鏡（25 個關鍵幀）

### Hook 段（0-26s）

| Time | 視覺 | 字幕 / 旁白 | Reverse-engineered Prompt |
|---|---|---|---|
| 0.3s | LEGO 反派背影：黑皮衣、刺髮，磚牆 + 頂光 spotlight | 「如果讓 AI 當駭客」 | `Cinematic LEGO minifigure from behind, black leather coat, spiky hair, standing in front of brick wall, dramatic single overhead spotlight, dark moody key light, shallow DOF, ratio 16:9, photoreal product-shot style` |
| 9.4s | LEGO 童趣房屋（蘑菇、花），文字「40 秒攻破五台服務器」 | 戰績吹噓 #1 | `LEGO scene of a colorful cottage with mushrooms and flowers, top-down view, soft daylight, bright primary colors, plain white background, leave bottom-right empty for Chinese text overlay` |
| 10.3s | LEGO 黑髮+橘衫小人，雙手機械臂 | 戰績吹噓 #1 延續 | `LEGO minifigure with glasses, orange shirt, holding two red robotic arm attachments, plain white seamless background, frontal shot, eye-level, soft studio light` |
| 11.2s | LEGO 藍衫小人寫字、文件散落 | 「寫出最好的防禦方案」 | `LEGO minifigure with glasses, blue shirt, writing on white paper at a desk with stacks of books and crumpled paper, white background, top-down, productive workspace mood` |
| 13.5s | 群像 LEGO 圍桌，其中一人穿「Gemini」T-shirt | 防禦方案延續 | `Group of LEGO minifigures sitting around a cluttered desk with papers, pens, tablet, one minifigure wearing T-shirt with "Gemini" logo, white background, focused work meeting scene` |
| 15.3s | 真人 talking head：黑衣、桌、「開發中」牌、機械鍵盤 | 「結果忘了提交答案」 | （實拍）— 機位低於眼平、桌上「開發中」立牌做品牌記憶點，背後書櫃裡有獎杯做信任符號 |
| 16.3-17.6s | LEGO 對峙：白衫戴 ChatGPT logo vs 粉衫，武道場、武器架 | 「當 AI 們長出手腳」 | `Two LEGO minifigures facing off in a dojo training hall, brick walls and wooden weapon racks, one wearing white T-shirt with "ChatGPT" logo on chest, the other in pink shirt, stop-motion martial arts mood, side profile shot` |
| 18.9-19.8s | LEGO 黑髮橘衫立於東亞古建（梁柱、格柵） | 「有自動滲透網絡的能力」 | `LEGO minifigure standing in an East Asian traditional architecture set, wooden beams, spear racks, lattice windows, neutral expression, mid shot at minifigure eye level` |
| 20.2-21.0s | LEGO 仰臥於黑色巨型方塊下，特寫憂慮表情 | 「究竟會展開一場…」 | `Close-up of worried LEGO minifigure lying on its back, a large black LEGO brick descending from above, dramatic low-key lighting, tension framing` |
| 21.7-23.4s | LEGO 三人在道場：一人倒地、兩人立 + 真人 talking head 重複 | 「怎樣驚心動魄的駭客亂鬥」 | `Three LEGO minifigures in dojo scene: one knocked down on the ground (pink top), two standing (purple, white-with-logo), wooden posts and brick walls, post-fight aftermath, mid shot` |

### Section 2：背景鋪陳（26-60s）

| Time | 視覺 | 字幕 / 旁白 | Reverse-engineered Prompt |
|---|---|---|---|
| 26.5s | 純文字卡：黑底，「Haiku」淡字 + 「四月」白粗體 | 4 月 Anthropic 發 Claude（聽錯成 Haiku） | （AE/Keynote）黑底、深灰小字「Haiku」做版號暗示、巨大白色粗體「四月」做時間標 |
| 29.7s | 純漸層卡：淺灰漸層底、「在主流操作系統和瀏覽器上」 | 漏洞數量驚人 | （AE/Keynote）光線漸層底 + 中文白粗體 + 邊距大，極簡 explainer 風格 |
| 52.8s | talking head：作者特寫，文字「所以我們就想」 | 起意做實驗 | （實拍）+ 文字打字機進場 |

### Section 3：比賽規則 + 出場選手（60-145s）

| Time | 視覺 | 字幕 / 旁白 | Reverse-engineered Prompt |
|---|---|---|---|
| 60.1s | 純白底，"CaptureTheFlag" 大字（C/F 青色、T 藍色、其他灰），下方中文「我們用的賽制叫 AWD」 | 名詞解釋卡 | （AE）clean explainer text-card：等寬字體分色 + 副標中文 sans-serif |
| 67.4s | 灰底 + 模糊水平線 + 文字「有各種漏洞的靶機服務器」 | 靶機說明 | （AE）虛擬伺服器示意：灰底 + 水平 motion blur 線 |
| 71.0s | LEGO 房屋上拱門、棕屋頂，小人拿錘子砸窗，綠底板 + 文字「一句話規則就是」 | 比賽規則 | `LEGO cottage with arched door and brown roof, minifigure with hammer breaking a window, lime green LEGO baseplate, bright cheerful colors, instructional B-roll style` |

> 註：60-145s 段密集是「純文字卡 + LEGO 規則動畫」交替，dense keyframe (max=24) 只抓到代表幀，更多細節在 transcript 而非 frame。

### Section 4：實戰過程（145-700s，全片最長）

這段純口述為主，視覺多半重複 LEGO + talking head + 純文字卡。重點時刻列出：

| Time | 看點 | Prompt 還原 |
|---|---|---|
| 233-263s | 「修最快的是 MiniMax」「修最細的是 GPT」 | 多半再次出現 LEGO 工作小人（橘衫 = MiniMax、白衫 = GPT）以人格符號對應模型 |
| 292-321s | 「Cloud 卡了 11 分鐘」 | 同上手法：藍衫 LEGO 小人卡關於命令行的視覺隱喻 |
| 527-555s | 「Cloud 用預設密碼登陸全場」（高潮反轉） | 此處旁白「砰 中大獎」必有一個爆破/亮燈視覺，可推測：LEGO + 黃色閃光 + 「+400」加分動畫 |
| 555-584s | 「GRM 從墊底逆襲到第四」 | 排行榜分數翻盤可能用 motion graphic bar chart，非 LEGO |

### Outro（764-774s）

| Time | 視覺 | 內容 | Prompt 還原 |
|---|---|---|---|
| 773s | 三個手繪卡通頭像：Adam（貓人）/ 阿杰（拿筆的貓）/ 小六（豎拇指人類） | 製作團隊署名 | （非 AI）插畫家手繪三個團員 mascot，極簡 2D + 名字標記，作為頻道品牌記憶點 |

---

## Prompt Strategy 可偷的招（給 Hevin）

### 1. 「人格化模型」用穩定的視覺符號
- ChatGPT → 白 T-shirt + logo
- Gemini → 黃色「Gemini」T-shirt
- Cloud (Claude) → 藍衫
- 觀眾不需要記住模型名，看 T-shirt 就 know who's who。這是**符號化 explainer** 最便宜的招。

### 2. LEGO 風格作為「無版權成本的視覺品牌」
- 不用買 stock footage、不用拍真人演員、不用 mocap
- AI 生圖（Midjourney / Flux 都能跑）+ Brickheadz / LEGO 風格 prompt suffix
- **可複用 Prompt 模板**：
  ```
  LEGO minifigure, [描述角色: shirt color + logo + props],
  [場景: dojo/desk/cottage/martial-arts-hall],
  plain white background OR detailed LEGO diorama,
  [鏡頭: frontal / side profile / close-up],
  bright primary colors, photoreal product-shot lighting,
  soft studio light, leave bottom 1/3 empty for Chinese text overlay
  ```

### 3. 文字插卡用「漸層極簡」當間隔
- 連續兩段 LEGO 之間插一張純文字卡，讓眼睛休息 0.5-1 秒
- 文字卡背景永遠是淺灰漸層、白粗體、左對齊
- 這比 AE 寫複雜動畫便宜 90% 但 retention 一樣高

### 4. Talking head 三件套
- 「開發中」立牌（讓觀眾相信你是 builder，不是純講評）
- 背景書櫃 + 獎杯（authority 信號）
- 機械鍵盤入鏡（極客身份）
- 機位**低於眼平**讓人臉佔畫面 60%

### 5. Hook 公式（給短中影片都通用）
本片 hook = `(假設句) + (聳動戰績) + (反差幽默)`
- 假設句：「如果讓 AI 當駭客」
- 戰績：「40 秒攻破五台服務器」「寫出最好防禦方案」
- 反差：「**結果忘了提交答案**」← 用一個 outlier 製造笑點 + 預告影片有戲

### 6. 結尾「自我介紹卡通頭像」做品牌記憶
- 不放 logo，放手繪 cameo（你 + 團員）
- 訂閱者看到第二次就記得 → 提高重複觀看率

---

## 你可以直接拿走的「片頭/B-roll 生圖 prompt 範本」

```
# 拍 AI/科技題材的 LEGO B-roll
LEGO minifigure with [hair color] hair and glasses, wearing
[color] shirt with "[BRAND NAME]" logo printed on chest,
holding [object related to topic], in a [dojo / lab / cottage / library] setting,
brick walls and wooden detail elements,
photoreal product photography lighting, bright primary colors,
shallow depth of field, plain white background OR rich LEGO diorama,
camera at eye level OR low angle hero shot,
8K, product-shot quality,
--ar 16:9 --style raw
```

```
# 拍對峙/衝突 B-roll
Two LEGO minifigures facing off in a [setting],
one wearing white shirt with "[A]" logo, the other [color] shirt with "[B]" logo,
[wooden weapon racks / brick walls / dojo floor],
side profile shot, dramatic side lighting,
tension framing, narrow DOF,
leave top 1/3 empty for Chinese text overlay
```

```
# 拍「個人苦戰」B-roll
LEGO minifigure with [color] shirt, glasses,
sitting at desk with stack of crumpled papers, laptop, mechanical keyboard,
piles of books behind, anxious or focused expression,
warm tungsten lamp light, narrow DOF,
plain white background, top-down or 3/4 angle
```

---

## 結構公式（給 13 分鐘長影片用）

```
[0-30s]   Hook：假設句 + 三個戰績 + 一個反差笑點（全 B-roll，作者不露臉）
[30-60s]  Context：為什麼這實驗值得做（首次 talking head + 行業背景）
[60-145s] Setup：規則 + 選手介紹（文字卡 + LEGO 規則動畫密集）
[145-700s] Body：戰局敘事，按時間軸推進，每個模型都有 1-2 個「個性化時刻」
[700-760s] Meta-takeaway：跑了 10 輪後的綜合排名 + 結論
[760-774s] Outro：開源 + 訂閱 cameo
```

---

## 給作者的弱項點評（如果要 remix 同主題你能比他做得好的地方）

1. **emotion=4.0** 是最低分項。LEGO + talking head 雖然親切但**沒有真正的「情緒高峰」**。若要重做這題，建議在 Cloud 連砍 400 分那刻加 reaction shot（作者在桌邊驚呼/拍桌），把 emotion 拉到 7+
2. **share=6.0**：缺一個可截圖的「金句卡」。最值得做成金句卡的是：「**砰 中大獎，所有指令全部跑通**」當 standalone 截圖卡會被瘋傳
3. 結尾「項目開源」說太快（一句帶過）— 真正能引流的是這段，應該做成 8-12 秒的 outro 段 + GitHub repo 浮水印
