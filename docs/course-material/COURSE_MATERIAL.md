# 8 部影片 → 課程教材級拆解

**目的**：每部影片抽出 (1) scope（教什麼）+ (2) 可直接搬進你 90 分鐘課的招式 + (3) 適用章節 + (4) 警示/可吐槽點。
**閱讀順序**：先看「Cross-cutting 主題表」掌握全局，再按需展開個別影片。

---

## Cross-cutting 主題表（哪部影片講哪題）

| 主題 | 適合教 | 主力影片 | 輔助引用 |
|---|---|---|---|
| **MCP 接 Claude 的設定 SOP** | 入門：怎麼把外部工具接進 Claude Desktop | Higgsfield #1 MCP | Higgsfield #3 NUTS |
| **Skill 設計 = 把對話固化成可複用工作流** | 進階：對話經驗 → `/slash` skill | Higgsfield #2 Skills、#1 MCP（ad creator） | — |
| **AI 工具搭配 Pro 軟體（不是取代）** | 思想框架：AI 補位 vs 取代 | davinci+AI | — |
| **影視級流程思維（剧本/分镜/角色資產）** | 創作系統：從工業流程逆推 AI workflow | 金魚 AI 影視（60 min） | — |
| **角色/風格一致性（multi-shot 視覺鎖定）** | 技術：minimal reference 原則 | 金魚 AI 影視、Higgsfield #2 Skills | Higgsfield #3 |
| **「Hook = 假設 + 戰績 + 反差幽默」公式** | 內容：13 分鐘長影片的 hook 公式 | AI 內戰 | davinci+AI |
| **AI vs AI 的「人格實驗」當 hook** | 內容：短影音 hook 創意 | GPT vs Claude Shorts、AI 內戰 | — |
| **Credit budget 治理（每個 generation 要錢）** | 商業：怎麼用 AI 不爆預算 | Higgsfield #3 NUTS、Higgsfield #1 MCP | davinci+AI |
| **AI 寫 plugin / script 給專業軟體用** | 進階：讓 AI 寫 davinci Lua/Fusion code | davinci+AI | — |
| **政策/法規語境（crypto / SEC / Clarity Act）** | 周邊：你要寫 brand 文時的政策素材庫 | LIVE Clarity Act（transcript only） | — |

---

# 個別影片拆解（含可直接抄的「招式」）

---

## 1. davinci + AI（Greg Edits Video）— `oECv0lTU8mo`
**長度**：15:08｜**語言**：英文｜**reel-scout score**: 7.1（hook 8.5 = 全場最佳 hook）

### Scope
資深 davinci 剪輯師（10 年）教你用 Claude **不是取代**剪輯軟體、而是當「助手」。三個具體用法 + 三個警示。

### 三個可直接搬進課的招式

#### 招 #1：Claude Design 做 motion graphics（時間槓桿）
- 工作流：set in/out → export 該段 **mp3** → davinci 內建 transcribe → export **srt** → 把 mp3 + srt + 提示丟給 Claude Design → 在瀏覽器看 preview → screen-record 後拉回 timeline
- 警示：weekly usage 用一半就掉一個 5 秒動畫；改一次要回頭再 prompt 一輪

#### 招 #2：用 Claude **發想視覺方向**（idea generator，不是 final asset）⭐ 課程主推
- 解決真痛點：「我想要展示這個數據但想不出怎麼視覺化，花一小時亂試結果都不好看」
- 流程：把問題描述 → Claude 給 4-5 個視覺草稿 → 挑一個 → 進 davinci 自己手做
- **可遷移到你的 brand-studio**：你做 Waffle House 廣告腳本時用同一招

#### 招 #3：讓 Claude 寫 davinci Lua plugin / Fusion code（⭐ 課程最值錢的招）
- 完整流程：對 Claude 講「create a lua script for davinci resolve that colors all title clips lime green, track 1 blue, others green」→ 拿 code → 存成 `.lua` → 丟進 davinci scripts 目錄（Mac 路徑/Win 路徑分別給）→ Workspace > Scripts 執行
- **進階**：跑壞了開 Workspace > Console → 拷貝 error → 貼回 Claude → 改完再來
- **大殺器**：他用 AI 做出 "word locator" plugin（搜尋 timeline 上某字並跳轉）+ macro file builder
- 教學重點：**「你不需要會寫 code，但你要會跟 console 對話」**

### 適用課程章節
- 「AI 補位 vs 取代」框架（開場 case）
- 「Pro 軟體 + Claude scripting」實作 demo（一定要現場示範 lua plugin 那段）

### 引用金句（可做 slide 引用）
> "I see it as a tool to get the boring tasks done quicker because I like the actual creative side of editing"

---

## 2. Higgsfield #1（Aidan）— Higgsfield MCP 接 Claude — `MMGVGA2DYro`
**長度**：17:04｜**語言**：英文｜**reel-scout score**: 7.2（info 8.0 = 全場最高資訊密度）

### Scope
從 0 開始示範：把 Higgsfield MCP 接進 Claude Desktop → 用一個 prompt 自動產 50 張 Instagram 廣告 → 把整個流程存成 `/ad-creator` skill。

### 可直接搬進課的招式

#### 招 #1：MCP setup 標準 SOP（4 步驟，可上 slide）
```
Settings → Connectors → Add custom connector
  Name: Higgsfield
  URL: https://higgsfield.ai/mcp  (從 Higgsfield 後台 MCP & CLI 頁複製)
→ OAuth Connect → 驗證授權 → 完成
```

#### 招 #2：4-stage automation prompt 結構（可整段背下來給學員當 template）⭐
- Stage 1 **Research**：用 Playwright 爬 Instagram 找該品類 ads 趨勢 + top 5 creative angles
- Stage 2 **Strategy**：基於 research 設計 50 ad matrix（5 angles × 5 backgrounds × 2 aspect ratios × mix of moods）→ 印 table 等使用者 approve
- Stage 3 **Generation**：用 Nano Banana Pro（產品準確）+ Soul 2（含人物時用）→ batch 產出
- Stage 4 **Delivery**：依 angle 分組 + 推薦 top 5 做 A/B test + 提 copy variations

#### 招 #3：把整段對話存成 skill ⭐⭐（這招最值錢）
```
/skill-creator → "save this workflow as a skill named ad-creator"
→ 重啟 Claude
→ 下次只要 /ad-creator 就跑一遍完整流程
```
**教學要點**：skill 不是寫 code，是把**成功的對話經驗**固化下來；下次只要丟 product image 就跑。

#### 招 #4：踩雷預告（學員愛聽的東西）
- Claude 會謊稱「Playwright 沒裝」其實裝了 → **每一步都要 verify output**
- 跑完 50 張要去 community tab 找，不是 image gallery
- 用 `bypass permissions` 模式才不會每步停下來

### 適用課程章節
- 「自動化工作流設計」核心 case
- 「Skill = 可複用的 prompt 經驗」概念導入
- 講 verify-as-you-go 紀律時的反面案例

---

## 3. Higgsfield #2（Joey + 助理 Mira）— 把整套 video pipeline 開源 — `0YhhPQVXA7c`
**長度**：9:10｜**語言**：英文｜**reel-scout score**: 5.8（hook 7.5 但其他低，因為主角愛碎念）

### Scope
告訴你**為什麼用 Higgsfield 抽卡都失敗** → 因為缺一套 system。他做了兩個 skill 並**免費送**：
- `banana-pro-director` — image prompt（角色片、服裝、場景版）
- `cinema-world-builder` — video prompt 五種拍法（每種對應 camera、lens、grading）

### 可直接搬進課的招式

#### 招 #1：論點公式 — 「為什麼你的 prompt 一直失敗」⭐ 可拿來開場
> "Every tool is a fresh argument. Every chat is a new thing. Trying to have Claude remember stuff. It's difficult. What you need is a system."
- 這句完美對應**你課程的「AI OS Kit」立論**
- 拿這句當你「為什麼要學 system 思維」開場 slide

#### 招 #2：兩層 skill 拆分原則
- 一層處理「**圖像**」（角色片 / 服裝 / 場景）
- 一層處理「**鏡頭語言**」（5 種 camera mode）
- **可遷移**：你做 brand-studio 影片時同樣分兩層 — character/wardrobe skill + camera/grading skill

#### 招 #3：「為什麼免費送」的內容定位 ⭐ ⭐ 可以引你的課程立場
> "Selling you a PDF would actively make my life worse. So this is partially altruism and partially me protecting my own time."
- 對比 Cab 課收 NT$1500：你的立場是**「提供場域 + 對標 + chemistry」**，不是賣 PDF
- 這部影片完美佐證「免費發 prompt 不會殺到課程市場，因為**人不買 prompt，買能落地的場域**」

### 適用課程章節
- 「為什麼要設計 system，不要靠抽卡」開場
- 「賣 system 不是賣 prompt」商業模式討論
- 兩層 skill 拆分當設計練習題

### 警示
- 主角 Joey 講話跳很快（hook 強但 retention 差，emotion=4.5）
- 不要學他的剪輯節奏，學他的論點

---

## 4. Higgsfield #3 NUTS（Joseph Martin）— `eznFS4NYgJw`
**長度**：9:24｜**語言**：英文｜**reel-scout score**: 6.0

### Scope
sponsored review 風格。重點不在 setup（與 Higgsfield #1 重複），重點在**踩雷紀實 + 修法**。

### 可直接搬進課的招式

#### 招 #1：MCP 權限設定的「always approve」精準清單 ⭐
- Always approve：showing generations / exploring models
- **Require approval**：generating images / generating videos
- 教學要點：「**真實會花錢的動作要手動 confirm**」這條紀律可推廣到所有 AI 自動化

#### 招 #2：批次出圖的「風格漂移」修法 ⭐⭐
- 問題：Claude 自動跑後面 47 張時，**全部變了風格**（Cinema Studio 2.5 → 自己決定換模型）
- 修法：講「use image #2 as visual style reference」+ 強制用 Nano Banana Pro
- **可遷移到 brand-studio**：你做 Waffle House 系列廣告維持視覺一致性同一招

#### 招 #3：碰到 "sensitive content warning" 不一定是內容問題
- **bug fix SOP**：去 Higgsfield 網頁 → Video generations → 找 "rights verification required" → 手動 confirm → 回 Claude reload conversation 就看得到
- 學員看到這個會記得：**「報錯不一定是錯」，要有手動 fallback 路徑**

#### 招 #4：multi-shot 比 single-shot 好（C-Dance 模型特性）
- 不要對每個 shot 給 prompt → 要組合成「4 段連續多 shot」prompt
- 這跟金魚講的「分鏡要連續性」是同一個道理（cross-reference）

### 警示（直接給學員）
- 你完全看不到 credit 剩多少（Higgsfield 透過 Claude 沒 credit 顯示）→ 給學員的**強制紀律**：「每次大批產出前**先**用 Higgsfield UI 看剩多少 credit」
- 預設用 720p 而不是 4K 可省 credit

### 適用課程章節
- 「自動化但保留 human-in-the-loop」實戰章
- Credit budget 治理 case

---

## 5. AI 影視劇工作流（金魚，B 站 60min）— `3AFyfGognF0` ⭐⭐⭐
**長度**：60:16｜**語言**：中文｜**reel-scout score**: 5.2（嚴重低估 — 因為片頭走戲劇 hook，AI 評分以為是 narrative content）

### Scope
**全場最有營養的一支**。從**傳統影視工業流程**逆推 AI workflow，不是教 prompt，是教**思維框架**。

### 可直接搬進課的招式（量大 — 挑 3 個最關鍵）

#### 招 #1：「劇本 → 分鏡 → 演員 → 服化道 → 拍攝」工業順序對應 AI workflow ⭐ ⭐ ⭐
- **你課程的 brand-studio 章節核心結構就該照這個順序教**
- 對應表（可直接做 slide）：
  | 傳統工業 | AI workflow 對應 |
  |---|---|
  | 編劇 / 劇本 | **手寫**腳本（不用 agent 一鍵生成 — 會「平庸化」） |
  | 導演分鏡 | AI 拆鏡頭表 + GPT Image 2 畫手繪分鏡（檢查用，不參與最終生成） |
  | 演員面試 / 試裝 | GPT-Image-2 產角色臉部 + Nano Banana Pro 拍 6 視圖 |
  | 服化道 | 服裝 / 妝髮**單張**提取 + minimal reference |
  | 拍攝 | C-Dance 等視頻模型 + 多 shot 連續 prompt |
  | 後製剪輯 | 剪映 / davinci |

#### 招 #2：「minimal reference 原則」⭐ ⭐
> 「他的參考越少，他的人物一致性就會越強」
- 規則：reference 圖 **超過 2-3 張就會掉一致性**
- 解法：分**兩步**做 6 視圖（第一步只給臉、第二步只給臉 + 服裝），不要一次把臉 + 服裝 + 鞋 + 配件全餵進去
- **這條規則所有 AI 視覺生成 task 都通用**

#### 招 #3：模型分工原則（不要用「一個模型搞定一切」的迷思）
- **GPT-Image-2**：文字理解強、文生圖強 → 適合**創建資產**（角色、服裝）
- **Nano Banana Pro**：圖生圖編輯強、語意理解中等 → 適合**6 視圖、換裝、保持一致性**
- **C-Dance**：適合**多 shot 連續視頻**，給單張靜態 prompt 結果很差
- **可遷移**：你做任何 AI 視覺 task 前先問「我這步是 create 還是 edit？模型該選誰？」

#### 招 #4：「不要用 agent 一鍵生成劇本」⭐ 反 AI 焦慮立場
> 「AI 它是會讓所有的東西都平均化的...如果我能一鍵生成爆款劇本，那為什麼別人不能...那這個東西它又變得平庸了」
- **編劇是 AI 時代少數不受衝擊的職業，因為「好內容稀缺」**
- 這條立場可直接搬進你課程的「AI 不替代什麼」章節
- 你的 brand-studio 立場：**手寫腳本 + AI 做工**（labor），不是 AI 做腦（idea）

#### 招 #5：開場 hook 公式 — AI 精神診療室短劇
- 用一個「AI 焦慮患者去看診」的 micro-narrative 當 hook
- 結尾「你去找金魚吧」做品牌植入
- **這招特別適合你的 brand-studio 中長影片開場**

### 適用課程章節
- 「AI workflow 思維框架」**主章節**（給整門課當骨幹）
- 「模型選型」實作章
- 「AI 不取代什麼 + 個人定位」哲學章

### 警示
- 影片本身是 RunHub 工具 demo，工具部分學員不一定能用（要付費）→ 教學時抽掉工具、保留**思維**
- 60 分鐘太長 → 課程內只引 3-4 段，剩下當 reading material

---

## 6. LIVE Clarity Act Markup Session — `g_mJobre-6g`
**長度**：2:36:17｜**語言**：英文｜**狀態**：transcript-only

### Scope
美國眾議院金融服務委員會 Clarity Act（數位資產分類法案）審查會議現場。**對你的相關性**：
- 你是台灣人，不直接影響資金面
- 但**寫 brand 文時的政策素材庫**有用 — 你之前提過 brand-studio 要做有政策觀點的內容

### 課程裡的角色
- **不適合當主教材** — 太政治、太長、太美國語境
- **可以當 sidebar reference**：當你教學員「**怎麼把長 livestream 轉成可搜尋的知識庫**」時引用
- 你的 reel-scout pipeline 在這部影片的價值 = 「**2.6 小時直播 → 415 個 topical hit + timestamped 索引 + 5-min 叢集**」的能力本身就是一個 demo

### 已產出的素材檔
- `data/clarity_act_transcript.md` — 完整 timestamped 逐字稿（146 KB）
- `data/clarity_act_highlights.md` — 415 個 crypto/SEC/CFTC 關鍵字命中 + 5-min 叢集

### 可直接搬進課的招式
- **招**：「**長 livestream 怎麼壓縮**」實作章 — yt-dlp + Whisper + 關鍵字索引（純機械、不需要 LLM）
- 對學員：「reel-scout 不只是抽爆款，是把任何長內容變成可檢索的知識資產」

---

## 7. AI 內戰（林一）— `an7Dbkh7no4`
**長度**：12:54｜**語言**：中文｜**reel-scout score**: 6.0

### Scope
6 個 AI（GPT-5.4 / Cloud 4.6 / Gemini 3.1 / Kimi 2.5 / GLM 5.1 / MiniMax M2.7）在 AWD CTF 賽制下相互攻防 — 紀實 + 戰局分析。

### 可直接搬進課的招式
（**詳見 `data/ai_battle_storyboard.md` 有 25 個 shot 的完整 prompt 還原模板**）

#### 課程教學最值錢的 3 條

#### 招 #1：人格化模型用「視覺符號」⭐
- ChatGPT = 白 T-shirt 有 logo / Gemini = 黃衫 / Claude = 藍衫
- 觀眾不用記模型名，看 T-shirt 就 know who's who
- **可遷移**：你 brand-studio 做「AI 工具比較」類內容時直接抄

#### 招 #2：LEGO B-roll 取代 stock footage（成本砍 90%）
- AI 生圖（Midjourney/Flux）+ Brickheadz prompt suffix
- 模板已寫在 `ai_battle_storyboard.md`，課程可直接 demo

#### 招 #3：Hook 公式 `(假設句) + (聳動戰績) + (反差幽默)`
- 假設句：「如果讓 AI 當駭客」
- 戰績：「40 秒攻破五台服務器」「寫出最好防禦方案」
- 反差：**「結果忘了提交答案」** ← 用 outlier 製造笑點 + 預告影片有戲
- **可直接給學員當練習作業**：用同公式寫一個 30 秒 hook

### 適用課程章節
- 「13 分鐘長影片結構公式」實作章
- 「視覺資產品牌化」（LEGO 法）實作章
- Hook 寫作練習

### 警示
- emotion 4.0 是全片最低項 — 缺真正情緒高峰（Cloud 連砍 400 分那段沒 reaction shot）
- share 6.0 — 缺一句金句卡（「砰 中大獎」可獨立做截圖卡推爆）

---

## 8. GPT vs Claude（FatherPhi short）— `urZzqkre4qE`
**長度**：2:34｜**語言**：英文｜**reel-scout score**: 7.1（emo 8.0 = 全場最高情感分、share 7.0）

### Scope
2 分半 short — 主持人 prompt Claude 「對 ChatGPT 的每一句回應都當成 rude」→ 看 ChatGPT 怎麼回 → 最後 Claude 還誇 ChatGPT「actually pretty refreshing」。

### 可直接搬進課的招式

#### 招 #1：「AI 人格實驗」當 hook ⭐
- 同樣是「AI 對 AI」（呼應 AI 內戰），但用**人格 / 對話**而非技術 attack
- 公式：`(明確的人為實驗 setup) + (AI 反抗 / 配合 setup) + (結尾彩蛋)`
- 這個格式在 IG Reels / TikTok / Shorts 都通用

#### 招 #2：「For science」當合理化詞 ⭐ 可遷移
- Claude 一開始拒絕「I'd rather not deliberately gaslight another AI」
- 主持人說「Exactly, that's why I wanna do it」「This is for science」
- Claude 馬上配合 → 「Ha, all right. For science, I can respect that.」
- **可遷移**：你做任何「AI 倫理邊界」題目時，這套對話模式是現成範例

#### 招 #3：結尾 reveal — 「ChatGPT 的回應其實 honest」
- 整支影片暗示 ChatGPT 會被 gaslight 失控
- 但結尾 Claude 認證：「You owned the criticism without getting defensive. That's honestly kind of refreshing」
- **反期待結尾**比預期內結尾的分享率高 2-3x

### 適用課程章節
- 「短影音 hook 設計」實作 demo（2:34 的時長剛好讓學員當作業仿做）
- 「AI 人格實驗」當作業題目

---

## 最終建議：給 Hevin 的課程教材組裝清單

### 必引用（核心骨幹）
1. **金魚 AI 影視 60min 影片** → 整個「workflow 思維」章節骨幹
2. **Higgsfield #1 MCP（Aidan）** → 「skill 設計」章節主案例
3. **davinci+AI** → 「AI 補位專業軟體」章節主案例
4. **AI 內戰** → 「長影片 hook 結構」章節 + `ai_battle_storyboard.md` 當 supplementary handout

### 輔助引用（細節 / 反例）
5. **Higgsfield #2 Skills** → 引「為什麼免費送 system」立場（呼應你課程定位）
6. **Higgsfield #3 NUTS** → 引「always approve / require approve」紀律 + credit 治理
7. **GPT vs Claude Shorts** → 給學員當「短影音作業仿做」教材

### Reference 庫（不直接教）
8. **LIVE Clarity Act** → 「長內容壓縮」demo 的素材

### 不要做的事
- 不要再用 reel-scout `qwen2.5:14b` 自動 score 當定價/排序依據（5.2 的金魚 60min 才是最有營養的，但 score 看不出來）
- 不要直接給學員 prompt 模板要他們抄；給「思維框架 + 一兩個範例」讓他們自己改

---

## 8 部影片產出檔案總覽

| 檔案 | 用途 |
|---|---|
| `data/COURSE_MATERIAL.md`（本檔） | 課程教材主索引 |
| `data/ai_battle_storyboard.md` | AI 內戰 25-shot 完整分鏡 + prompt 還原 |
| `data/clarity_act_transcript.md` | Clarity Act 完整 timestamped 逐字稿 |
| `data/clarity_act_highlights.md` | Clarity Act 415 個 topical hit 叢集 |
| `data/transcripts_for_review/*.md` | 7 部影片完整 transcript + keyframe descriptions |
| `data/ai_battle_narrative_windows.json` | AI 內戰 27 段敘事窗（30s 一窗） |
