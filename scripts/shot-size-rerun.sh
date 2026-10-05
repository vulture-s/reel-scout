#!/bin/bash
# 用「有判準」的新提示詞重跑景別標籤（PR #103）。
#
# 🔴 2026-10-05 搬進 repo 時的狀態更正：**這支已經沒有排程了。**
# 它原本掛 com.hevin.reel-scout-shot-size-rerun（每日 03:00），而那個 plist 在
# 2026-09-19 已刪 —— 原因是它的自我卸載（本檔最後一段）只做 `launchctl bootout`，
# 而 bootout 不刪 plist，所以它在 09-07／09-17 各自「復活」跑了一次 0 支，
# 同時在 log 裡寫下「已卸載」。**一支會說謊的 job 比一支壞掉的 job 難查。**
# 現在它是手動指令：`bash scripts/shot-size-rerun.sh`。
# 最後那段 bootout 留著不動（沒有那個 label 時是 no-op），這樣將來真要重新排
# 一輪時它仍然會自己收斂。
#
# 搬進 repo 的理由同 translate-all.sh：放在 ~/Library/Application Support/ 底下
# 等於重建這台機器時復現不出來。
#
# 只跑「標籤指紋不是現行提示詞」的片：跑完就自然收斂，重跑一次不會再做第二遍，
# 中斷後續跑也不會重做已經做好的。清單是每一輪重新查的，不是開頭抓一次 ——
# 開頭抓一次的話，中途失敗的片會從清單上消失得跟做完了一模一樣。
#
# ⚠️ 本機只有一顆 ollama，翻譯 job（02:00，約 5 小時）跟這支會互搶。
# 所以這裡等的是「那支還在不在跑」這件事本身，不是等一個猜出來的時鐘點 ——
# 翻譯跑多久沒有人知道，而排一個「應該夠晚了」的時間就是在賭。
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${REEL_SCOUT_SHOT_SIZE_LOG:-$HOME/Library/Logs/reel-scout-shot-size-rerun.log}"
MODEL="${REEL_SCOUT_SHOT_SIZE_MODEL:-qwen2.5vl:7b}"
TRANSLATE=translate-all.sh
MAX_WAIT=$((8 * 3600))
cd "$REPO" || exit 1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

waited=0
while pgrep -f "$TRANSLATE" >/dev/null 2>&1; do
  if [ "$waited" -ge "$MAX_WAIT" ]; then
    say "ABORT: 等了 $((MAX_WAIT/3600)) 小時翻譯還在跑，不硬排隊（兩支搶同一顆 ollama 只會兩支都慢）"
    exit 1
  fi
  [ "$waited" -eq 0 ] && say "WAIT: 翻譯 job 還在跑，每 5 分鐘回來看一次"
  sleep 300
  waited=$((waited + 300))
done
[ "$waited" -gt 0 ] && say "WAIT: 等了 $((waited/60)) 分鐘，翻譯已結束"

# ollama 沒起來就別空跑：每一幀都會 refused，而 refused 不寫任何東西 ——
# 結果是一份看起來跑完了、其實什麼都沒換的日誌。
if ! curl -s --max-time 10 http://localhost:11434/api/tags >/dev/null 2>&1; then
  say "ABORT: ollama 沒有回應 (localhost:11434)，不啟動"
  exit 1
fi

stale_ids() {
  # 判斷交給 repo 裡的 label_shots.stale_videos()，這裡不自己寫一份 SQL ——
  # 抄一份在這裡的話，它會跟 db health 的判斷各自漂，而漂掉的樣子是
  # 「health 說 0 筆過期，這支卻一直找到事做」。
  ./.venv/bin/python -B -c "
from reel_scout import db, label_shots
for vid in label_shots.stale_videos(db.get_connection()):
    print(vid)
"
}

TOT=$(stale_ids | grep -c .)
say "START: $TOT 支帶著舊提示詞的標籤, model=$MODEL"
N=0
STUCK=""
# 跑過就記下來，下一圈跳過 —— 清單仍然每圈重查（中途失敗的片才不會從迴圈裡
# 消失得跟做完了一模一樣），但「已經試過而還在清單上」＝這支不會收斂。
#
# 🔴 2026-09-03 實犯：初版是「清單非空就取第一個」＋ 一個總數上限當守衛。
# 守衛確實擋下了無窮迴圈（它該做的），但它擋的方式是**停掉整個 run** ——
# 第 24 支 560dfe9c082f7e87 卡住空轉 71 圈，後面 70 支一支都沒跑到。
# 一支片不收斂是那支片的事，不該讓其他 70 支陪葬。
while :; do
  id=""
  for cand in $(stale_ids); do
    case " $STUCK " in *" $cand "*) continue;; esac
    id="$cand"; break
  done
  [ -z "$id" ] && break
  N=$((N+1))
  # 抓 tally 那一行本身，不要 tail -N —— 指令後面跟著幾行說明，
  # 而說明行數會隨程式改動而變，tail 抓到的就從數字漂成散文。
  RAW=$(./.venv/bin/reel-scout shot-size "$id" --model "$MODEL" 2>&1)
  OUT=$(printf '%s\n' "$RAW" | grep -m1 -E '^(shot sizes:|skipped:)')
  [ -z "$OUT" ] && OUT=$(printf '%s\n' "$RAW" | tail -1)
  say "[$N/$TOT] $id :: $OUT"
  STUCK="$STUCK $id"
done
LEFT=$(stale_ids | grep -c .)
[ "$LEFT" -gt 0 ] && say "STUCK: $LEFT 支跑過仍在清單上（模型對某些楨答了詞彙外的東西，重跑不會變）"
say "DONE: $N 支已重跑"

# 跑完自己卸掉。Hevin 要的是「這一次重跑」，不是一條常設政策 ——
# 留著每天跑的話，下次我改動提示詞就會在無人看管的深夜燒掉 50 分鐘 GPU，
# 而沒有人要求過那件事。要再跑一次就重新 bootstrap 一次，那是一行指令。
if [ "$(stale_ids | grep -c .)" -eq 0 ]; then
  say "UNLOAD: 已無舊提示詞標籤，卸載 com.hevin.reel-scout-shot-size-rerun"
  launchctl bootout "gui/$(id -u)/com.hevin.reel-scout-shot-size-rerun" 2>/dev/null
else
  say "KEEP: 仍有舊提示詞標籤沒收斂，排程保留，明天 03:00 再試"
fi
