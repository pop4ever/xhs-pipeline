#!/usr/bin/env bash
# 02篇 全片处理: 6段 音轨对齐(-10% 云希) + 裁切 + 拼接 (bash3 兼容, 不用关联数组)
set -uo pipefail
cd /private/tmp/h3/45s-01/v3
mkdir -p final

KEYS=("01-hook" "02-compare" "03-flicker" "04-box" "05-solutions" "06-cta")
TEXTS=(
  "装智能开关最怕的坑,就是没留零线"
  "零火版开关有独立零线,供电稳灯不会闪"
  "单火版没零线只能靠偷电,LED灯极易闪"
  "电工进场前交代师傅,每个底盒都留好零线"
  "已经装了单火版,就加个适配器最省事"
  "关注我,下期讲七个空间的插座布置"
)
RAWS=(
  "./02-raw.mp4"
  "./02-02-compare-raw.mp4"
  "./02-03-flicker-raw.mp4"
  "./02-04-box-raw.mp4"
  "./02-05-solutions-raw.mp4"
  "./02-06-cta-raw.mp4"
)

for idx in "${!KEYS[@]}"; do
  KEY="${KEYS[$idx]}"; TEXT="${TEXTS[$idx]}"; RAW="${RAWS[$idx]}"
  OUT="./final/02-${KEY}-final.mp4"
  edge-tts --voice zh-CN-YunxiNeural --rate=-10% --text "$TEXT" --write-media "./02-${KEY}-v.mp3" 2>/dev/null
  VE=$(ffmpeg -i "./02-${KEY}-v.mp3" -af "silenceremove=start_periods=1:start_threshold=-45dB,silencedetect=n=-38dB:d=0.25" -f null - 2>&1 | grep silence_start | tail -1 | sed 's/.*: \([0-9.]*\)/\1/')
  [ -z "$VE" ] && VE=3.5
  CUT=$(python3 -c "print(round(min(float('$VE')+0.5, 5.166),3))")
  ffmpeg -y -loglevel error -i "$RAW" -i "./02-${KEY}-v.mp3" -map 0:v -map 1:a \
    -c:v copy -c:a aac -af "silenceremove=start_periods=1:start_threshold=-45dB,apad" \
    -t "$CUT" "$OUT"
  V=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$OUT")
  A=$(ffprobe -v error -select_streams a:0 -show_entries stream=duration -of default=noprint_wrappers=1:nokey=1 "$OUT")
  echo "[$KEY] voice_end=${VE}s cut=${CUT}s -> v=$V a=$A"
done

echo "==== concat ===="
printf "file '%s'\n" final/02-01-hook-final.mp4 final/02-02-compare-final.mp4 final/02-03-flicker-final.mp4 final/02-04-box-final.mp4 final/02-05-solutions-final.mp4 final/02-06-cta-final.mp4 > list02.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i list02.txt -c copy final/xiaomi-smart-02-final.mp4
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,duration -of default=noprint_wrappers=1 final/xiaomi-smart-02-final.mp4
ffmpeg -i final/xiaomi-smart-02-final.mp4 -af volumedetect -f null - 2>&1 | grep -E "max_volume|mean_volume"
echo "==== 02 DONE ===="