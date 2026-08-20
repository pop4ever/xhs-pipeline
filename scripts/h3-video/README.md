# h3-video 生产脚本集 (2026-08-20)

## audio-align-remux.sh
音轨对齐 v4 方案(用户验收): 本地 edge-tts 云希 -10% 重合成 -> 去掉头静音 -> 裁到「语音结束+0.5s」-> remux 视频轨(零重渲染)。
用法: 按段配置 KEYS/TEXTS/RAWS 数组后直接跑; 输出 final/*.mp4 + concat 成片。
依赖: 本地 edge-tts CLI + ffmpeg; 服务器 raw 需先 scp 下来。

## 关键流程(轮询顺序铁律)
1. **先查 MAX(execution id) 再 POST** — n8n 接收瞬间即建 execution 行, 先 POST 再查会把"自己"算进 MAX, 永远等不到 id>BASE(2026-08-20 实测 20min 死等)
2. 轮询 sqlite: `SELECT id,status FROM execution_entity WHERE workflowId=? AND id>? ORDER BY id DESC LIMIT 1` until success
3. 下载: `ls -t /home/david/n8n-data/h3-videos/h3_video_*.mp4 | head -1` 再 scp
4. 音轨对齐: 见 audio-align-remux.sh 模式(逐段 VE 独立)

## 部署版事实(2026-08-20 核 sqlite workflow_entity)
- 生产 webhook: /webhook/h3/video-gen2 (v2 EdgeTTS clean, id=b2a3c4d5-e6f7-8a9b-0c1d-2e3f4a5b6c7d)
- 音色 zh-CN-YunxiNeural(云希) rate 0(部署)+本地 -10% 重合成
- seed 随机(Math.random()*1e9) — 跨段一致性靠 style_prefix + 文字锚点
- 视频输出: /home/david/n8n-data/h3-videos/

## 坑
- 口播文案必须先本地 edge-tts 测时长: 段长 5.17s, 语音须 3.8-4.9s(留 0.5s 呼吸), 超 5.17s 被 -t 截断("值不值没读完成"案例)
- silencedetect tail -1 有坑: 句内停顿>0.3s 也会报(02/04 段误判 1.6s 结束) — 以 ffprobe 音频流时长为准
- H3 设备脑补: 中控屏写 `square touchscreen smart control panel, white frame, mounted at switch height` + 反向 `no round wall lamp`(详见 h3-video-pipeline skill)
