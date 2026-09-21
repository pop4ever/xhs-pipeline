# p7550 H3 视频生成架构（完整版）

> 状态快照：2026-09-21 ｜ 代码 `h3-workflows/`（本仓库）｜ 运维手册 `docs/INSTALL-rtx5000-h3lite.md` ｜ 性能数据 `docs/h3perf-vertical-20260921.md`
> 所有「坑 N」编号对应 hermes skill `h3-video-pipeline`（本机 `~/.hermes/skills/devops/h3-video-pipeline/`，备份于 pop4ever/hermes-skills 私有仓）。

## 一、硬件与系统底座

| 项 | 值 |
|---|---|
| 机型 | Dell Precision 7550（无头常开：开盖、屏 5min 熄灭、永不休眠） |
| GPU | **Quadro RTX 5000 with Max-Q Design 16GB**（Turing **sm_75**），驱动 580.178.04，CUDA 12.4 容器栈 |
| 系统 | Ubuntu 24.04（david 免密 sudo），Python 3.12.3 |
| 模型盘 | `/mnt/models`（2TB 独立盘）→ 容器内同路径挂载 |
| 角色铁律 | **p7550 = 视频生产专职，不跑 LLM 服务**；mini-ai-svr(.60) = LLM 专职，绝不跑 H3 渲染（2026-09-21 用户拍板双机隔离） |

## 二、服务拓扑（两层，端口互不重叠）

```
POST :8190/jobs  (h3postbox, host systemd + uvicorn)
   │  1. 参数注入 wf_base.json（模板替换）
   ▼
POST :8189/prompt  (ComfyUI 容器 comfy-h3:fixed, 0.0.0.0:8189 → 容器内 8188)
   │  2. 渲染：恒定 AV 图 → seg.webm(vp9) + ambient.flac
   ▼
   host 层（全部后期在 host，容器无 ffmpeg）：
   │  3. edge-tts 词级 cues → ASS 字幕
   │  4. ffmpeg mux：A/B/ambient 混流 + libass 烧字幕 + tpad 冻尾 pad + 裁切
   ▼
data/job_*/final.mp4   （scp / GET /jobs/{id}/file 交付）
```

### 层 1：ComfyUI 渲染容器（:8189）

- 镜像 `comfy-h3:fixed`，**ComfyUI 0.36.0**，自带 H3 官方节点 `comfy_extras/nodes_minimax_h3.py` —— **现役图零第三方自定义节点依赖**（容器里的 ComfyUI-GGUF 是 GGUF 路线废弃后的遗留，不加载）。
- 启动参数：`python3 /opt/ComfyUI/main.py --listen 0.0.0.0 --cache-lru 0 --disable-smart-memory --mmap`
- 模型路径经 `extra_model_paths.yaml`（base `/mnt/models/comfy`）：unet/text_encoders/vae/clip/lora。
- ⚠️ **容器无 ffmpeg/apt（immutable 镜像）** → 混流/烧字幕必须放 host；`SaveAudio` 无 ffmpeg 时**静默不落盘**（webm 照出）→ h3postbox 内建同 seed flac 找回兜底（同 seed+prompt 的 H3 音轨字节级确定）。

### 层 2：h3postbox 混流编排服务（:8190）

- host 进程：systemd `h3postbox.service`（`Restart=on-failure`）→ `/home/david/h3postbox/.venv/bin/uvicorn h3postbox:app --host 0.0.0.0 --port 8190`
- Python 依赖仅 4 件：`fastapi 0.141.1` / `uvicorn 0.53.0` / `edge-tts 7.2.8` / `requests 2.34.2`
- host 系统依赖：`ffmpeg 6.1.1`（libx264/libvpx-vp9 decode/libass/libmp3lame）+ `fonts-noto-cjk`（30 个 noto 字形在册）
- 环境变量：`COMFY_API=http://127.0.0.1:8189`、`EDGE_TTS_PROXY=http://192.168.1.222:7800`（可去）、`AMBIENT_GAIN=-8dB`（B 模式环境音床增益）
- 代码三处同步（改一必同步二）：
  1. p7550 `/home/david/h3postbox/h3postbox.py`（部署实体）
  2. 本仓库 `h3-workflows/h3postbox.py`（git 真相）
  3. skill `h3-video-pipeline/scripts/h3postbox-server.py`（快照）
- 接口：`POST /jobs`（入队）、`GET /jobs/{id}`（status/stage/分阶段计时）、`POST /jobs/{id}/retry`（阶段级断点续跑，复用 seg/ambient/voice 只补缺段）、`GET /jobs/{id}/file`、`GET /health`、`GET /voices`
- ⚠️ retry 短路看 job JSON `status=="done"` 而非产物存在——删了 final.mp4 照样 "already done"，重混走函数级调 mux（坑 53.5）。

## 三、ComfyUI 图（`h3-workflows/wf_base.json`，17 节点，恒定一张图）

```
[3] UNETLoader ──[5] LoraLoaderModelOnly ──[9] BasicGuiter ─────────────┐
[4] CLIPLoader(type=minimax, device=cpu)──┤                    [10] KSamplerSelect(res_multistep)
[8] MiniMaxH3ImageToVideo(clip=4, vae=6,   │      [11] BasicScheduler(simple, steps=4)
      prompt / width / height / length)────┼──cond→[9]              [12] RandomNoise(seed)
      latent(video+audio NestedTensor)─────┘         [13] SamplerCustomAdvanced
[6] VAELoader(video fp16) ──[14] VAEDecode(images) ──[16] SaveWEBM(vp9, 24fps, crf32)
[7] VAELoader(audio fp32) ──[15] VAEDecodeAudio(audio) ──[17] SaveAudio(flac)
```

关键设计决策：

- **AV 联合采样**：video + audio 在同一 latent（slot `13:#0` / `13:#1`），audio latent 躲不掉 → **A/B/C 三模式只是 host 末端混流开关（`audio_mode` 参数），一套图三模式，不维护第二张 workflow**（用户拍板）。
- 采样栈：`res_multistep` + `simple` scheduler ×4 步（turbo8 LoRA），**无 SigmaShift、无 KSampler**（与已废弃的 GGUF 老图完全不同）。
- `MiniMaxH3ImageToVideo` 空 optional（first/last_frame）= 纯 t2va；**length 强制 17k+5 帧网格**（5,22,39,56,73,90,124…@24fps，向上自动吸附）。
- `adapt_canvas()`（短边 768 / 面积 cap 768×1344）**只作用于 ref_video 输入路径**；t2v 直出按请求 W×H（32 对齐）原生出图——实测 480×864 / 720×1280 竖版 seg.webm 分辨率与请求一致。
- 末端保存节点只认 `SaveWEBM`/`SaveAudio`：`SaveVideo` 的 DYNAMICCOMBO format 过得了提交校验、但 API JSON 不解包成 execute 位置参数，跑完 ~215s 最后一步才崩（坑 51）。

## 四、模型文件清单（全在 `/mnt/models/comfy/`）

### ✅ 现役五件套（官方 HF 仓 `Comfy-Org/MiniMax-H3`，int8_convrot 路线）

| 文件 | 目录 | 大小 | 角色 |
|---|---|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | unet/ | 20.97GB | DiT 主干（int8 权重+fp16 激活——sm_75 无 FP8/FP4 的官方替代量化） |
| `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | text_encoders/ | 27.14GB | Qwen3-VL 32B 文本编码器，**device=cpu 常驻**（`--mmap`+页缓存；encode ~110-135s，之后采样全 GPU） |
| `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` | lora/ | 1.96GB | turbo 8→4 步蒸馏 LoRA（`LoraLoaderModelOnly`，strength 1.0） |
| `minimax_h3_video_vae_fp16.safetensors` | vae/ | 5.21GB | 视频 VAE（fp16；int8 版在盘不用） |
| `minimax_h3_audio_vae_fp32.safetensors` | vae/ | 0.61GB | 音频 VAE（32kHz FLAC 环境音解码） |

显存账：unet int8 分块上卡 + 双 VAE ≈ **采样峰值 15.6 / 16GB**（720p 档贴边通过；124 帧 720p 预计 OOM，长段走 480p）。

### 💤 死重 ≈58GB（待用户放行清理）

- GGUF 全系：`MiniMax-H3-FL2VA-Pruned-Q3/Q4/Q5_K_M.gguf`、TE `qwen3vl_32b_minimax_h3-Q4_K_M.gguf`、nunchaku `svdq_int4_r32_minimax_h3_t2va.safetensors`(18.5GB)、`cand_8step_v1.0_bf16`、768p turbo 变体、int8 video VAE 残档
- **废弃根因（坑 50）**：第三方 GGUF 把 `general.architecture` 错标成 `wan`（张量名却是 H3 packed-DiT）→ 加载器按错架构解释权重 → 端到端跑完必出纯噪声。与显存/量化档无关。
- `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` 15.7GB：Turing 无 FP4 硬件，备选未启用。

## 五、后期链（host ffmpeg，参数全在 h3postbox.py）

| 阶段 | 实现 | 关键参数 / 铁律 |
|---|---|---|
| 口播 | **edge-tts**（微软在线神经 TTS，免 key 免本地权重） | 默认 `zh-CN-YunxiNeural`（云希，用户选定）rate `-10%` ≈ 3.5-3.8 字/秒；词级 cues 必须显式 `boundary="WordBoundary"`（新版默认 SentenceBoundary，不设→cues 空→假报错） |
| 字幕 | 词级 cues → **ASS**（标点分句、≤18 字/行、底部安全边距避开小红书 UI）→ libass 烧录 | `ass=` 路径 `:`→`\:` 转义且不加引号；ASS 滤镜必须放 tpad **之后**（否则冻结尾段无字）；布局类 QC 禁用 vision 估算，走白字像素检测 `scripts/subtitle-gap-check.py` |
| 混流三模式 | `a` 纯口播 / **`b` 口播+环境音床（默认）** / `ambient` 纯 H3 音 | b 正确拓扑：`[2:a]volume=-8dB[amb]; [1:a]aresample=48000[vo]; [vo][amb]amix=inputs=2:duration=first:normalize=0 → 全局 loudnorm(I=-16:TP=-1.5) → alimiter(0.87)`。**铁律①：loudnorm 绝不能挂 amix 上游**（lookahead 饿死 amix 输出→音频截到 1.28s，status 依然 done）；**铁律②：normalize=0 两路直加 +3.5LU 必越 0dBFS → 尾挂 limiter**。实测成片 I=-14.9 LUFS / peak -1.8 dBFS |
| 口播溢出 | **`pad_video` 默认 True**（9/21 用户拍板"默认开"）：语音超长→尾帧冻结到说完，整句不截 | `tpad=stop_mode=clone:stop_duration=Δ+0.5`（webm 不能 `-loop 1`；stop_duration 是**增量**不是总长；pad 时禁 `-shortest`）；字幕末行 `hold_to=pad_dur-lead` 强制 hold 到冻尾。备用策略 `voice_cap`（截尾+丢过界 cues）仍可显式选用。字数安全线 ≈ 成片秒×3.4 |
| 验收 | status=done **不算数**，三查缺一不可 | ①`ffprobe stream=duration` 逐流比对 ②`ebur128=peak` 查削顶 ③抽帧落进 pad/freeze 区 vision 核字幕在场 |
| 环境音找回 | SaveAudio 静默失败时按 `<webm名>_a_00001.flac` 同 seed 找回 + `fLaC` magic 校验 | 找回失败直接 raise 带诊断，不静默降级 |

## 六、性能基线（实测，详见 docs/h3perf-vertical-20260921.md）

| 档位 | 实渲帧 | 成片 | GPU e2e |
|---|---|---|---|
| 640×352×73 横版 | 3.04s | 4.67s(pad) | **222s**（方差<0.1s） |
| 480×864×29 竖版 | 39 帧 1.63s | 5.42s | **231s** |
| 720×1280×42 竖版 | 56 帧 2.33s | 5.42s | **902s** |

- ≈ **4.0-4.3s GPU / 渲染秒 / 414k px**，线性 scaling 无 token 惩罚；720p 的 3.9× 耗时全由像素数（4.44×）买单。
- 竖屏生产选型：**480×864 甜点位**（3.9min/段）；封面级清晰才上 720×1280（15min/段）。
- 端到端 ≈ 渲染 + ~15s 后期（TTS/混流/烧字幕）+ 排队。

## 七、运维速查

```bash
# 健康: ssh -i ~/.ssh/p7550 david@192.168.1.74 'curl -s http://127.0.0.1:8190/health'
# 部署: scp h3-workflows/h3postbox.py david@192.168.1.74:/home/david/h3postbox/ && sudo -n systemctl restart h3postbox
# 渲染容器崩溃: sudo -n docker restart h3-comfyui   (模型重载占 16GB 页缓存, 冷启~90s)
# 客户端: bash h3-workflows/h3post.sh submit '{"prompt":"...","voice_text":"..."}'
#         h3post.sh status <job> | get <job> /tmp/out.mp4 | voices
```

## 八、Prompt 规范（生产定稿 = 官方三字段）

```text
integrated_multimodal_description: [Shot 1] <风格>, <场景/主体/动作>, <运镜=类型+幅度+速度>,
  one continuous shot without cuts, no people, no hands, no watermark, no logo.
overall_soundscape: <1-4 句环境声, 与画面匹配(模型会照此生成环境音轨, b 模式有用)>
non_diegetic_music: N/A            # 无 BGM; b 模式垫的是环境音不是音乐
```

- 单段内严禁时间轴分镜（官方坑：一镜到底别混分镜）；多段=多次 job 提交后 ffmpeg concat。
- 不写 "no subtitles"（官方确认反效果）。
- 真实产品必须写实际形态（H3 会把抽象设备脑补成错误东西，坑 47/圈图事故）。

## 九、已知边界与后续

- 长段：720p×124 帧预计 OOM（未测）；480×864×124 未实测，线性外推 ~400s 安全。
- I2V/首尾帧（FL2VA 能力已在模型里，`MiniMaxH3ImageToVideo` 有 first/last_frame optional，未接进 h3postbox）。
- SaveAudio 根修（给容器补 ffmpeg）可选；当前找回兜底够用。
- GGUF 死重 58GB 清理待放行；RDMA35Patch 等 mini 老管线遗产与本机无关。
- edge-tts 依赖微软在线接口（有代理兜底但无常约）；断供时回退本地 TTS 未规划。
