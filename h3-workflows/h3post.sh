#!/usr/bin/env bash
# h3post 客户端 — Mac 侧提交/查询/下载 p7550 h3-postbox 任务（视频生产机，16G RTX5000）
# 用法:
#   ./h3post.sh submit "<画面prompt>" "<口播文案>" [a|b|ambient] [voice] [WxHxL] [seed] [pad]
#   ./h3post.sh status <job_id>
#   ./h3post.sh get    <job_id> [out.mp4]
#   ./h3post.sh voices
# 模式: a=纯TTS口播 b=H3环境音垫底(-8dB+限幅,默认) ambient=纯H3环境音(无文案)
# pad=on: 口播超画面时长时冻结尾帧垫画面(不截语音); 默认off=画面优先截语音
# 字数安全线: 口播字数 ≤ (帧数/24)*3.4 (如73帧3s→10字); 超了会被截或需pad=on
# 例: ./h3post.sh submit "Sunrise over misty forest lake, birdsong breeze" "晨雾漫过湖面" b "" 640x352x73 1 on
PB=http://192.168.1.74:8190
KEY="$HOME/.ssh/p7550"
cmd=${1:-}
case "$cmd" in
  submit)
    prompt=$2; text=$3; mode=${4:-b}; voice=${5:-zh-CN-YunxiNeural}; geom=${6:-640x352x73}; seed=${7:-1}; pad=${8:-off}
    W=${geom%x*}; rest=${geom#*x}; H=${rest%x*}; L=${rest#*x}
    body=$(python3 - "$prompt" "$text" "$mode" "$voice" "$W" "$H" "$L" "$seed" "$pad" <<'PY'
import json,sys
p,t,m,v,w,h,l,s,pad=sys.argv[1:10]
print(json.dumps({"prompt":p,"voice_text":t,"audio_mode":m,"voice":v,
 "width":int(w),"height":int(h),"length":int(l),"steps":4,"seed":int(s),
 "burn_subtitle":bool(t),"trim":True,"pad_video":pad=="on"},ensure_ascii=False))
PY
)
    echo "$body" | curl -s -X POST "$PB/jobs" -H 'Content-Type: application/json' -d @-
    echo
    ;;
  status) curl -s "$PB/jobs/$2" | python3 -m json.tool 2>/dev/null | head -30 ;;
  get)
    jid=$2; out=${3:-h3_$jid.mp4}
    st=$(curl -s "$PB/jobs/$jid" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')
    [ "$st" != done ] && { echo "job not done: $st"; exit 1; }
    scp -i "$KEY" -q "david@192.168.1.74:/home/david/h3postbox/data/job_$jid/final.mp4" "$out" && echo "saved: $out"
    ;;
  voices) curl -s "$PB/voices"; echo ;;
  *) grep '^#   ' "$0" | sed 's/^#   //' ;;
esac
