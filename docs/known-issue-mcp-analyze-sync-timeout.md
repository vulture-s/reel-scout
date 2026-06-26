# Known Issue — MCP `analyze` 同步阻塞 → client timeout → 連線斷、工具全消失

> 發現於 2026-06-26（CC 用 MCP 跑兩支 YouTube 長片分析時連續觸發）。
> 影響面：任何透過 **MCP** 呼叫 `analyze` 的 client（Claude Code 等）。CLI 直跑不受影響。
> Roadmap Phase 5「Distribution — 開源 + 社群」上線後，**外部使用者會穩定踩到**，需在開源前修。

## 症狀

- 兩支長片（5:05 + 2:26）+ `skip_audio=false` + `keyframe_max=60` 一起跑 → `internal error`，結果拿不回。
- 縮成單支 + `skip_audio=true` 重試 → `MCP error -32000: Connection closed`。
- 之後該 session 內 **reel-scout 的所有 MCP 工具全部消失**（analyze / crawl / list / show / export），要重啟 client 才回得來。
- 對照組：同樣兩支片改用 **CLI**（`reel-scout analyze ... > log 2>&1 &` 背景跑 + 輪詢）→ **完全正常跑完**（下載＋轉錄＋視覺＋合併）。

## Root Cause（非環境問題，是架構限制）

`reel_scout/mcp/server.py` 的 `main()` loop 是**序列、同步、一次處理一個請求**。一個 `tools/call analyze` 會在 handler 裡**同步阻塞數分鐘**（下載 + whisper 轉錄 + VLM 視覺）。MCP client 對單一工具呼叫有 timeout；當 `analyze` 跑超過該 timeout，client 放棄並關閉 stdio pipe。server 偵測到 `BrokenPipeError` 後（按既有設計）`break` 乾淨退出——但從 client 端看到的就是「Connection closed」+ 工具全消失。

關鍵在於：這層**早已知道且只做了「斷線時別把整個 process 炸掉」的防禦**，根本問題沒解。`server.py` `main()` 註解原文：

> Processing is serial (one stdio request at a time) and a `tools/call analyze` can block for minutes; if a client gives up and closes the pipe during that wait, the next write would raise BrokenPipeError. … **(True concurrency would need a worker thread; this only makes the server survive disconnects — it does not parallelize.)**

界線：**短單支、能在 client timeout 內跑完的 → 沒事**。一旦長片 / 開音訊（PANNs）/ 批次多支 → 必然超時撞牆。與機器、與 client 無關，是「同步長工作跑在會 timeout 的 stdio 請求通道上」的結構問題。

## 修法 — async job + poll 模式

把 `analyze` 從「提交即阻塞」改成「提交即返回 + 另外輪詢」：

1. `tools/call analyze` **立刻回一個 `job_id`**（建 batch row、狀態 `queued`），不在請求裡跑分析。
2. 實際 pipeline 丟 **worker thread / 背景進程**跑，進度寫進 DB（沿用既有 `batches` / `batch_items` + `status` 欄位，CLI 的 `--resume` 已是這個模型）。
3. 新增輕量工具 `analyze_status(job_id)` / 沿用 `list` + `show` 讓 client **poll** 進度與結果——每個請求都在毫秒級回得來，永遠不碰 timeout。
4. main loop 保持序列即可（poll 請求很輕）；真正的重活在 worker，stdio 通道不再被獨佔數分鐘。

效果＝MCP 路徑拿到跟「CLI 背景跑 + 輪詢」一樣的行為，這也正是這次繞過 MCP、改在 M2 Max 用 CLI 跑能成功的原因。

## 附帶發現（順手記，不在本 issue 主修範圍）

- **`scores` 表 schema drift**：M2 Max 上 `reel-scout analyze --score` 末步報 `table scores has no column named information_density`，分析本身（transcript/vision/merge）不受影響、照常入庫。疑似 v1→v3 migration 與 scorer 寫入欄位不同步，需單獨對一次 `scorer` 寫入欄位 vs `scores` 表定義。
