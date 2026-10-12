# 設計：雲端 vision 後端（VLM_BACKEND=openai／anthropic）

> 狀態：**設計稿，未實作**。這份 PR 只放文件，等拍板再寫碼。
> 日期：2026-10-12 ｜ 對象版本：v1.5.0

## 要解的問題

「看畫面」（逐張描述關鍵影格）目前只有兩條路：

| 路 | 前提 |
|---|---|
| 本機 VLM（`omlx`／`ollama`） | 電腦跑得動 7–8B 的視覺模型（約 8GB VRAM／16GB 統一記憶體） |
| agent 自己看（SKILL Capability 1） | 人在 Claude Code 或 Claude Desktop＋MCP 裡操作 |

缺的那一格：**沒有本機模型、又不是在 agent 裡跑**的人 —— 例如純 CLI 批次、排程、或電腦太弱的筆電 —— 沒辦法拿一把 API key 讓雲端模型看畫面。評分那一步已經有 `LLM_BACKEND=openclaw` 接任何 OpenAI 相容端點，看畫面這一步沒有對應的東西。

## 現況裡已經有的（所以這件事比看起來小）

1. **`OmlxVLM` 送的就是 OpenAI 格式**：`POST {base}/chat/completions`，`content` 是 `image_url`（base64 data URI）＋文字。它跟一個雲端 OpenAI 相容端點之間，只差 `Authorization` 標頭、可設定的網址、和比較長的 timeout。
2. **來源追溯已經在**：每張影格描述存檔時記 `vlm_backend` 與 `vlm_model`（`db.save_vision_description`）。換成雲端模型，資料庫自然記得是誰看的。
3. **VLM 全掛的保護已經在**（#189）：一張都沒描述成功就停在 merge 前，不會對空視覺層打分。

## 提案

### 後端一：`VLM_BACKEND=openai`（OpenAI 相容，一支涵蓋多家）

- 新 class `OpenAICompatVLM`，從 `OmlxVLM` 抽出共用的「組 payload／解析回覆」，差在：
  - `VLM_API_BASE_URL`（預設 `https://api.openai.com/v1`）
  - `VLM_API_KEY` → `Authorization: Bearer …`（只從環境變數／`.env` 讀；`config show` 只印「已設定／未設定」，**不印值**）
  - timeout 改可設（`VLM_API_TIMEOUT`，預設 120 秒）
- 同一支可接：OpenAI、Google Gemini 的 OpenAI 相容端點、OpenRouter 等 —— **每家都要實測一張圖才列進文件**，沒測過的不寫「支援」。
- Anthropic 也有 OpenAI SDK 相容端點；**它是否吃 base64 圖片要先實測**。吃 → 不需要後端二；不吃 → 做後端二。

### 後端二（視實測結果）：`VLM_BACKEND=anthropic`

- 原生 Messages API：`POST https://api.anthropic.com/v1/messages`，`x-api-key`＋`anthropic-version` 標頭，圖用 `{"type":"image","source":{"type":"base64",…}}`。
- 仍然只用 `urllib`（本 repo 規則：不引入 `requests` 或官方 SDK）。

### 共通

| 項目 | 做法 | 為什麼 |
|---|---|---|
| 429／5xx | 指數退避，最多 N 次（沿用 `LLM_MAX_RETRIES`／`LLM_RETRY_BACKOFF` 的形狀，另開 `VLM_*`） | 雲端會限流；本機不會，所以現有 VLM 路徑沒有這層 |
| 錯誤分類 | 401／403（key 錯）→ **整批立刻停**，不要每張圖各失敗一次 | 否則 40 張圖 = 40 次一樣的失敗＋40 行一樣的錯 |
| fallback 模型 | 雲端後端**不走** Ollama 的 `VLM_FALLBACK_MODEL`；失敗的影格留空等下次重試 | 現在的 fallback 寫死 Ollama（`pipeline.py` 的 `fallback_blocked_because`），混用會把雲端失敗的圖丟給一台不存在的本機 |
| 預設 | 兩個新後端都**不是**預設；不設就跟現在一樣 | 影格會離開這台電腦，必須是使用者明確選的 |

## 三個要先講清楚的代價

1. **隱私**：每張關鍵影格（含畫面上的字、人臉、浮水印）會上傳到第三方。選這個後端時，`analyze` 開頭印一行：「N 張影格將上傳至 <host>」。不做成每次都問（批次跑不了），但要看得到。
2. **錢**：影格數有上限（長片 40 張），單張 token 依解析度約 800–2,800（v1.5.0 文件裡用真實影格量過的數字）。實作時加 `--estimate`：只算影格數與預估 token，不送出。**價目不寫死在程式或文件裡**（會過期），只給 token 數讓人自己乘。
3. **同一把尺**：雲端模型打的視覺層，跟本機模型打的不能混著比。`stats` 已經依 `model_used` 分組（#75），這裡要確認 `vlm_model` 也進同一個分組鍵，否則 `patterns` 會把兩種眼睛看出來的結果平均在一起。

## 不做的事

- 不做「本機失敗就自動改送雲端」的自動降級 —— 那會讓影格在使用者沒選的情況下離開電腦。
- 不在這一版碰評分（`LLM_BACKEND`）—— 已經有 `openclaw` 可接 OpenAI 相容端點；要不要把它改名成 `openai`、讓兩邊變數一致，另案討論。

## 驗收

- 單元測試：payload 形狀、標頭、401 整批停、429 退避、key 不出現在任何 log／`config show`。
- 實測：每個要寫進文件的服務，至少一支真實短片端到端跑完（下載 → 抽影格 → 雲端描述 → merge → 評分），記下實際 token 數。
- 文件：README 的後端表、`.env.example`、SKILL.md 的 capability 矩陣（雲端 VLM 算 Capability 2 的一種：有一個「模型」在描述，只是不在本機）。

## 待拍板

1. 先只做後端一（OpenAI 相容），Anthropic 原生看實測結果再說？—— 建議是。
2. 變數名用 `VLM_API_BASE_URL`／`VLM_API_KEY`（跟 VLM 綁），還是 `OPENAI_BASE_URL`／`OPENAI_API_KEY`（跟服務綁、可被 LLM 共用）？—— 建議前者：同時接兩家（例如評分用 A、看畫面用 B）時不會打架。
3. 上傳提示要不要做成一次性確認（`VLM_CLOUD_ACK=1` 之前每次問）？—— 建議只印不問，理由見上。
