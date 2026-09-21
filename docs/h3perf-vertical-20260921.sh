#!/usr/bin/env bash
# H3 vertical perf test: render + host-scale + timing
set -u
PB=http://127.0.0.1:8190
COMFY=http://127.0.0.1:8189
JROOT=/home/david/h3postbox/data
VPROMPT="Sunrise over a misty mountain lake, slow gentle camera drift forward through pine forest, warm golden light rays, ambient birdsong and a light breeze, vertical composition."
VVOICE="晨雾漫过湖面，鸟鸣唤醒森林，早安"

wait_job () { # $1=job  $2=max_s
  local jid="$1" max="$2" t=0
  while [ $t -lt "$max" ]; do
    s=$(curl -s "$PB/jobs/$jid" | python3 -c 'import sys,json;j=json.load(sys.stdin);print(j["status"],j["stage"],j.get("error") or "")')
    case "$s" in
      done*) echo "DONE"; return 0;;
      error*) echo "FAIL $s"; return 1;;
    esac
    sleep 10; t=$((t+10))
  done
  echo "TIMEOUT"; return 1
}

for cfg in "480 864 29" "720 1280 42"; do
  set -- $cfg; W=$1; H=$2; L=$3
  T0=$(date +%s)
  BODY=$(python3 -c "import json;print(json.dumps({'prompt':'''$VPROMPT''','voice_text':'''$VVOICE''','audio_mode':'b','width':$W,'height':$H,'length':$L,'pad_video':True}))")
  JID=$(curl -s -X POST "$PB/jobs" -H 'Content-Type: application/json' -d "$BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
  echo "=== ${W}x${H}x${L} job=$JID submitted @$(date +%H:%M:%S) ==="
  R=$(wait_job "$JID" 4200)
  if [ "$R" != DONE ]; then echo "ABORT $R"; curl -s "$PB/jobs/$JID" | head -c 500; echo; continue; fi
  T1=$(date +%s)
  # host upscale (lanczos + sharpen)
  ffmpeg -y -v error -i $JROOT/job_$JID/final.mp4 -vf "scale=$W:$H:flags=lanczos,unsharp=5:5:0.6:5:5:0.0,format=yuv420p" -c:v libx264 -preset slow -crf 18 -c:a copy $JROOT/job_$JID/final_up.mp4
  T2=$(date +%s)
  N=$(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of default=nk=1:nw=1 $JROOT/job_$JID/seg.webm 2>/dev/null)
  D=$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 $JROOT/job_$JID/final_up.mp4)
  SZ=$(stat -c%s $JROOT/job_$JID/final_up.mp4)
  echo "RESULT ${W}x${H}x${L} | render_e2e=$((T1-T0))s | upscale=$((T2-T1))s | seg_frames=$N | final_dur=${D}s | size=$SZ"
done
