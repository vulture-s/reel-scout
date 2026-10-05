#!/bin/bash
# 全庫中文對照翻譯。可續跑：已翻且未過期的段落會被跳過，所以中斷後重跑不會重做。
# 由 com.hevin.reel-scout-translate.plist 在 02:00 觸發（模板在 hevin-ai-os/infra/launchd/）。
#
# 2026-10-05 從 ~/Library/Application Support/reel-scout/ 搬進 repo。搬的理由：
# 它是 translations 表那 11,000+ 筆的唯一生產者，而放在 Library 底下等於
# 重建這台機器時復現不出來 —— plist 可以有模板，腳本不在版控就還是零。
# REPO 改成由本檔位置推導，不再寫死路徑（同一支腳本在任何 checkout 都對）。
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${REEL_SCOUT_TRANSLATE_LOG:-$HOME/Library/Logs/reel-scout-translate.log}"
MODEL="${REEL_SCOUT_TRANSLATE_MODEL:-qwen2.5:14b}"
# 刻意不叫 OLLAMA_HOST：ollama 自己那個變數的格式是 `localhost:11434`（無 scheme），
# 這裡要的是完整 URL，同名不同格式是現成的誤設陷阱。
OLLAMA="${REEL_SCOUT_OLLAMA_URL:-http://localhost:11434}"
cd "$REPO" || exit 1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# ollama 沒起來就別空跑一整晚：每一支都會 failed，而 failed 不寫任何東西，
# 結果是五小時的日誌跟一個沒有翻譯的資料庫。
if ! curl -s --max-time 10 "$OLLAMA/api/tags" >/dev/null 2>&1; then
  say "ABORT: ollama 沒有回應 ($OLLAMA)，不啟動"
  exit 1
fi

IDS=$(./.venv/bin/python -B -c "
from reel_scout import db
conn = db.get_connection()
for r in conn.execute(\"SELECT id FROM videos WHERE status='analyzed' ORDER BY id\"):
    print(r['id'])
")
TOT=$(echo "$IDS" | grep -c .)
say "START: $TOT 支待處理, model=$MODEL"
N=0
for id in $IDS; do
  N=$((N+1))
  OUT=$(./.venv/bin/reel-scout translate "$id" --model "$MODEL" 2>&1 | tail -2)
  say "[$N/$TOT] $id :: $OUT"
done
say "DONE"
