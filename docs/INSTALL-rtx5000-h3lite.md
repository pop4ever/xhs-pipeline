# INSTALL — Precision 7550 (RTX5000 + 2080Ti eGPU) 部署为 H3 视频节点

> 状态: **✅ 2026-09-21 RTX5000 单卡验证门语义通过**(官方 int8 safetensors 管线,连贯画面+音频实测确认);2080Ti eGPU 未接入,§8 待验

> 目标: 把 Precision 7550 变成 **单机双卡双节点** 渲染单元,与 `mini-ai-svr` 并行,整线 3 节点吞吐。
> 源素材: 2026-09-16 会话(真机 BIOS 证据 + 社区实测 + 算力推算)+ 2026-09-20 补充(2080Ti 22G 魔改卡经雷电3 外接 + Docker 部署决策)

> **部署方式决策(2026-09-20)**: ⭐ **Docker Compose 双实例**。理由: 与现网 ComfyUI 容器化一致(现网 `comfyui.service` 走 podman toolbox,坑共享如 `__pycache__` 删除、`filename_prefix` 防混池);双卡 = 两个容器天然隔离,各绑一张卡;镜像/Compose 即版本化,回滚干净。容器 GPU 直通 ≈ 零性能损耗(无虚拟化层),性能不是裸机的优势。Ubuntu 上 `docker-ce` 生态最成熟;与现网 Fedora+podman 不必强求同一 runtime(两台机器独立),容器化概念一致即可。

---

## 0. 硬件事实(真机 BIOS 面板证据,非猜测)

### 0.1 笔记本自带

| 项 | 值 |
|---|---|
| 机型 | Dell Precision 7550(15.6" FHD) |
| CPU | Intel Xeon W-10855M(6C/12T, 2.8~5.1GHz) |
| 内存 | 128GB DDR4-2133 4通道 = **68GB/s 带宽**(offload 型负载的物理瓶颈) |
| dGPU | **NVIDIA Quadro RTX5000** — Turing TU104, sm_75, 16GB, 448GB/s |
| iGPU | Intel UHD P630(显示用,可释放 dGPU) |
| 存储 | M.2 SSD-0 512GB / SSD-1 2TB / SSD-2 1TB(合计 3.5TB) |

### 0.2 外接(新增, 2026-09-20)

| 项 | 值 |
|---|---|
| 显卡 | **GeForce RTX 2080 Ti 22GB(魔改版)** — Turing TU102, **sm_75**, 22GB, ~600GB/s |
| 接口 | Thunderbolt 3.1 外置坞 = **PCIe 3.0 x4 ≈ 2.75GB/s**(硬上限) |
| 备注 | 原厂 2080Ti 仅 11GB;22GB 为第三方焊接换显存(352bit × 2GB 颗粒),矿卡翻新/体质风险见 §8 |

**同架构铁证**: RTX5000(TU104)与 2080Ti(TU102)同为 Turing sm_75 → W4A8 kernel 验证结果**互证**(§7)。

---

## 1. 组件路线选型(A/B/C)

> v2 修订: 2080Ti 22GB 全常驻后成为主渲染,RTX5000 降为次节点;选型账不变(都吃 W4A8 路线)。

| 路线 | 组件 | 磁盘占用 | 显存行为 | Turing 风险 |
|---|---|---|---|---|
| **A ⭐** | W4A8 UNet 12.5GB + **4B INT4 TE 2.8GB** + 双 VAE 5.8GB | ~21.5GB | 核心 15.3GB 常驻;RTX5000 上仅 VAE 换位, **2080Ti 22GB 上全常驻(21.1GB)** | W4A8 native kernel 在 sm_75 **未验证** → 3 分钟验证门(§7);TE INT4 是 LLM 社区 Turing 成熟路径 |
| B | Q8 GGUF UNet 21.6GB + 4B INT4 TE 2.8GB | ~30GB | 全部动态 offload | **两卡都贴不进去**: RTX5000 16GB 不够,2080Ti 22GB 余量 0.4GB 必 OOM → 否决 |
| C | 官方 32B nvfp4 TE 15.7GB | ~43GB | offload 为主 | **放弃** — Turing 无 bf16/fp8/nvfp4 硬件加速,反量化无效率优势还占 16GB |

**决策**: ⭐ A(别无选择——B/C 在 16GB/22GB 上都不可行);A 的 W4A8 kernel 若 fallback(反量化 ~25GB)→ 两卡都超容量 → 转备选 D(Wan/LTX)。

---

## 2. 性能预期(方案 A 成功时,三条证据链推算)

### 2.1 已验证参考点

| 硬件 | 模式 | 画布/步数 | 耗时 |
|---|---|---|---|
| RTX 4060 Ti 16GB(Ada) | NORMAL_VRAM 核心常驻 | 640×352 / 4步 | **77s** |
| RTX 4070 Laptop 8GB(Ada) | LOW_VRAM offload | 640×352 / 4步 | 591s |
| RTX 3060 Laptop 6GB(Ampere) | offload | 608×352 / 4s | 345s |
| mini-ai-svr(Strix Halo) | GTT 常驻 + RDNA35 加速 | 480p / 8步 Turbo | **438s(7.3min)** |

### 2.2 算力对比

| 卡 | 架构 | FP16 算力 | 带宽 | vs 4060Ti 算力 |
|---|---|---|---|---|
| 4060Ti | Ada AD106 | ~21.4 TF(4352×2×2.46G) | 288 GB/s | 1.0x(基准) |
| RTX5000 | Turing TU104 | ~8.9 TF(3072×2×1.455G) | 448 GB/s | **0.42x** |
| 2080Ti 22G | Turing TU102 | ~13.4 TF(4352×2×1.545G) | ~600 GB/s | **0.63x** |

- H3 采样是 DiT 算力主导(attention+FFN 大权重)→ 速度近似跟算力走
- 推算: 640×352/4步 → 77s ÷ 0.63 ≈ **122s ≈ 2min**(2080Ti);77s ÷ 0.42 ≈ **170s ≈ 3min**(RTX5000)
- 480p(864×480)/8步: token 1.84x × 步数 2x → 4060Ti 推断 ~283s → 2080Ti **~450s ≈ 7.5min**;RTX5000 **~630s ≈ 10min**
- 2080Ti 全常驻且带宽 600GB/s → 无 68GB/s 内存瓶颈拖累,数字比 RTX5000 可信度高

### 2.3 预期表(装完回填实测,见 §7)

| 出片档位 | RTX5000 | **2080Ti(全常驻)** | 对比 |
|---|---|---|---|
| 640×352 / 4步(试稿/快速走查) | 2.5~3.5min | **~2min** | 试 prompt 便宜化,现网不停产 |
| 480p 864×480 / 8步(现网正式档) | 8~14min,中位 ~10min | **7~9min** | 与 mini-ai-svr 7.3min 持平 |
| 480p / 4步(LightX2V 合并 LoRA) | 5~7min | **~4min** | 快于现网 |

**定位结论(v2)**: 单机双卡 = 2080Ti(主)+ RTX5000(次)两节点并行,加 mini-ai-svr 整线 ≈ 3 节点吞吐(现网 ~3x);快速试稿档 2min 是甜点。

---

## 3. 前提与风险(诚实标注)

1. **W4A8 kernel 兼容性是最大前提** — 数字建立在 kernel 在 sm_75 走原生路径;fallback(逐层反量化)后权重 ~25GB 两卡都超容量 → **直接转备选 D**,B/C 不构成回退(容量贴死)
2. 2080Ti 走雷电3(PCIe 3.0 x4 = 2.75GB/s): **全常驻负载几乎无影响**(每段数据交换 <1GB); offload 型负载则是灾难 → eGPU 方案强制全常驻,决策反而简化
3. RTX5000 上 VAE 仍换位(每次 ~5.2GB 走内部 PCIe,秒级);2080Ti 上全常驻无换位
4. offload 时系统瓶颈仍是 **68GB/s 内存带宽** → 方案 A 的意义 = 核心常驻,双卡均适用
5. Turing 无 bf16/fp8 硬件加速 → nvfp4 无效率优势(路线 C 放弃理由)

---

## 4. 安装步骤

> 假设机器为裸机或 Windows。512G 做系统,2TB 放模型,1TB 做工作输出。

### 4.1 系统安装

- 发行版: **Ubuntu 24.04 LTS**(docker-ce 生态最成熟;也可 Fedora 与 mini-ai-svr 一致)
- 分区: 512GB → `/`; 2TB → `/mnt/models`; 1TB → `/mnt/work`
- 用户: 新建 `david`(与现网一致)或自定

### 4.2 BIOS 设置(Dell 7550)

- **Lid Close: 保持默认即可**(使用方式 = 开盖常开,不靠 BIOS 管合盖;防误盖由 logind 兜底,见 §4.4)
- Secure Boot: 关或 enroll MOK(见 4.3)
- **Above 4G Decoding = Enabled**(eGPU 必需)
- **Thunderbolt Boot Support = Enabled**(坞内卡开机即认)

### 4.3 NVIDIA 驱动 + 容器 runtime(宿主机,550 系直支持 Turing,同时管两卡)

```bash
sudo apt install nvidia-driver-550   # 或 570(若已进仓)
# Secure Boot 开启时按提示 enroll MOK 并重启一次
sudo reboot

# 验证(定死 Turing,看到 7.5 按路线 A 装):
nvidia-smi --query-gpu=name,compute_cap --format=csv
# 预期: Quadro RTX 5000, 7.5  /  GeForce RTX 2080 Ti, 7.5

# 持久化 + 功耗锁(自带卡 80W;2080Ti 不动,它是主卡):
sudo nvidia-smi -pm 1
sudo nvidia-smi -pl 80 -i 0   # 先查范围: nvidia-smi --query-gpu=power.limit,power.max_limit --format=csv

# Docker 容器 runtime(容器化部署唯一额外组件):
sudo apt install docker-ce docker-compose-v2 nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
# 验证容器内可见 GPU:
docker run --rm --gpus all nvidia/cuda:12.4-base-ubuntu22.04 nvidia-smi
```

### 4.4 屏幕与电源策略(开盖常开,屏幕自动关闭,主机永不休眠)

**使用方式(2026-09-20 用户确认)**: 笔记本盖子常开;**屏幕无操作自动熄灭**(如 5 分钟),**主机绝不休眠/挂起**。开盖散热更好,垫高非必需(可选)。

```bash
# 1) 屏幕自动熄灭(5 分钟无操作熄屏),不锁屏(服务器无需锁):
gsettings set org.gnome.desktop.session idle-delay 300
gsettings set org.gnome.desktop.screensaver lock-enabled false

# 2) 禁自动挂起(AC 与电池都禁;仅接电源时 AC 行即可):
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'

# 3) logind 兜底: 防误盖挂起 + 禁挂起键 + idle 不触发动作:
sudo sed -i 's/^#HandleLidSwitch=.*/HandleLidSwitch=ignore/; s/^#HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/; s/^#HandleSuspendKey=.*/HandleSuspendKey=ignore/; s/^#IdleAction=.*/IdleAction=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

> 若装的是**无桌面服务器版**(无 GNOME),gsettings 那步不存在 —— 只需 logind 三项;屏幕压根不接/不亮,熄屏无意义。
> 验证: `systemctl status sleep.target suspend.target` 无 active;屏幕上 5 分钟无操作自动熄灭,主机继续跑渲染。

### 4.5 eGPU 坞(2080Ti)

- 坞电源 **≥650W**(2080Ti ~250W TDP)+ 坞自身散热
- 热插拔风险: ComfyUI 长任务(10min+)下雷电链路抖动 → **开机常插,不热拔**
- 到手 24h 压力测试(见 §8)

### 4.6 ComfyUI 代码与模型目录(宿主侧只挂载,不安装)

```bash
sudo mkdir -p /mnt/models/comfy/ /mnt/work/h3-out && sudo chown -R $USER:$USER /mnt/models /mnt/work
sudo git clone https://github.com/comfyanonymous/ComfyUI /opt/ComfyUI
# H3 custom node 放进 /opt/ComfyUI/custom_nodes/(与 mini-ai-svr 同款,h3lite 组件以现网为准)
# 模型放 /mnt/models/comfy/{unet,text_encoders|clip,vae,lora}
```

容器内不装 Python 依赖 —— 镜像里预装(见 §5),宿主只提供代码/模型/输出目录(挂载)。

### 4.7 模型下载清单(SHA-256 核验后再用)

| 文件 | 大小 | 位置 | 说明 |
|---|---|---|---|
| W4A8 UNet(h3lite) | 12.5GB | unet/ | 路线 A 核心 |
| 4B INT4 TE | 2.8GB | text_encoders/ | LLM 社区 Turing 成熟路径 |
| 双 VAE(视频 + 音频 fp32) | 5.8GB | vae/ | 音频 VAE 必须 fp32(MiniMax-H3 坑) |
| Q8 GGUF UNet(备, 实测过) | 21.6GB | unet/ | mini-ai-svr 已实测出片模型;但双卡容量贴死,仅作存档 |
| LightX2V turbo8 LoRA | ~1GB | lora/ | 480p/4步 加速档 |

```bash
sha256sum /mnt/models/comfy/*/* | tee /mnt/work/h3-install.sha256
# ⚠️ 与官方 repo 公布的 SHA-256 逐一比对,不一致立即重下;比对完成回填上表
```

---

## 5. Docker Compose 双实例(推荐部署形态)

`/opt/comfy-h3/docker-compose.yml`:

```yaml
services:
  comfy-main:            # 2080Ti 主节点,全常驻
    image: nvidia/cuda:12.4-devel-ubuntu22.04   # 含 python3 + 构建工具;或自建镜像(见下)
    runtime: nvidia
    environment:
      - CUDA_VISIBLE_DEVICES=1                  # 2080Ti
    volumes:
      - /opt/ComfyUI:/opt/ComfyUI               # 代码 + custom_nodes(只读可加 :ro)
      - /mnt/models/comfy:/mnt/models/comfy     # 模型(2TB 盘)
      - /mnt/work/h3-out:/mnt/work/h3-out       # 输出
    ports:
      - "8188:8188"
    working_dir: /opt/ComfyUI
    command: >
      bash -c "pip install -r requirements.txt -q &&
               python main.py --listen 0.0.0.0 --port 8188
               --extra-model-paths-config /opt/ComfyUI/extra_model_paths.yaml"
    restart: unless-stopped

  comfy-second:          # RTX5000 次节点,VAE 换位
    image: nvidia/cuda:12.4-devel-ubuntu22.04
    runtime: nvidia
    environment:
      - CUDA_VISIBLE_DEVICES=0                  # RTX5000
    volumes:
      - /opt/ComfyUI:/opt/ComfyUI
      - /mnt/models/comfy:/mnt/models/comfy
      - /mnt/work/h3-out:/mnt/work/h3-out
    ports:
      - "8189:8188"                             # 宿主 8189 → 容器 8188
    working_dir: /opt/ComfyUI
    command: >
      bash -c "pip install -r requirements.txt -q &&
               python main.py --listen 0.0.0.0 --port 8188
               --extra-model-paths-config /opt/ComfyUI/extra_model_paths.yaml"
    restart: unless-stopped
```

`extra_model_paths.yaml` 指向容器内路径 `/mnt/models/comfy`(unet/clip/vae/lora 子目录)。

```bash
cd /opt/comfy-h3 && docker compose up -d
# 验证两实例:
curl -s http://127.0.0.1:8188/system_stats | head -c 200   # 2080Ti
curl -s http://127.0.0.1:8189/system_stats | head -c 200   # RTX5000
```

**说明**:
- `restart: unless-stopped` 即开机自启(docker 服务随系统启动),无需 systemd 单元
- 首次 `pip install -r requirements.txt` 在容器内执行(共用镜像时每次 20s 级,可接受);若嫌慢可自建镜像固化依赖(现网有 `strix-halo-comfyui` 镜像可参考其 Dockerfile/构建方式)
- **坑(容器化通用,skill 已踩)**: 改 custom node 后必须删容器内 `__pycache__`(`docker compose exec comfy-main bash -c 'rm -rf /opt/ComfyUI/custom_nodes/<node>/__pycache__'`)再重启,否则加载旧字节码

---

## 6. 与现网管线对接(3 节点并行调度)

- 渲染提交: 直连 `:8188`/`:8189`/mini-ai-svr `:8188`(workflow dict 参考现网 `scripts/h3-direct-test.py` / `h3-render-batch.py`)
- 并行分工: **段集按 3 份切分**(mini-ai-svr : 2080Ti : RTX5000),各自提交→轮询→下载
- 输出汇聚: scp 回 Mac `~/projects/xhs-pipeline/`,走统一拼接/QC(concat → audio-align-remux.sh → 字幕空隙/内容抽帧)
- 快速试稿(640×352/4步)优先丢 2080Ti(2min),现网与 RTX5000 保持正式档产能

---

## 7. ⭐ 验证门(装完第一个动作,3 分钟)

1. 启动两实例,先在 **2080Ti 提交 640×352 / 4步** 试稿
2. 判据:
   - ✅ **~2min 出片**,日志确认 W4A8 走 **native kernel**(无逐层反量化 fallback)→ 方案 A 成立
   - ❌ 耗时膨胀(≥4min)或日志出现 fallback → **停;双卡容量贴死,无 B/C 回退 → 转备选 D(Wan/LTX)**
3. **互证检测**: 2080Ti 过 native 后,RTX5000 再跑同参数(同 sm_75 内核)→ 预期 2.5~3.5min;也过 → 双卡定案
4. 各卡一次出片后把实测耗时**回填 §2.3**,作为基准

**决策树**: A 验证门(2080Ti→RTX5000 互证)→ D(Wan/LTX)。

### 7.1 实测结果(2026-09-21, RTX5000 单卡)⭐ 验证门语义通过

**原方案 A(W4A8 nunchaku + GGUF)被证伪,换官方 safetensors int8_convrot 管线后一次通过。**

1. **第三方 GGUF 路线废弃**:`Abiray/MiniMax-H3-Pruned-GGUF` 的 `general.architecture` 元数据错标成 `wan`(张量名实为 H3 packed-DiT `adaln_t_table`/`audio_patch_proj`),加载器按错误架构解释权重 → **端到端能跑完、GPU 满载 15GB/100%、出合法 640×352 mp4,但画面纯噪声/彩虹花屏**。Q4/Q3、int8/fp16 VAE、加/不加 SigmaShift、t2va/喂首帧全试过,几十轮全是噪声。**与显存/量化档无关**。
2. **官方正路 = ComfyUI v0.36.0 自带 blueprint** `/opt/ComfyUI/blueprints/Image to Video (MiniMax H3).json`:`UNETLoader` int8_convrot safetensors + `CLIPLoader` **type=minimax** + `LoraLoaderModelOnly` 官方 turbo8 + `res_multistep` + `SamplerCustomAdvanced`(**无** SigmaShift、**无**普通 KSampler/euler)。
3. **模型文件(Comfy-Org/MiniMax-H3 仓,非 MiniMaxAI diffusers 分片)**:unet `minimax_h3_fl2va_pruned_int8_convrot.safetensors` 20,970,379,616B;TE int8_convrot 27,141,342,152B(sm_75 首选,替代 blueprint 默认的 NVFP4_AWQ——NVFP4 原生加速需 sm_89+);LoRA `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` 1.9GB;VAE 用盘上 fp16 video + fp32 audio。下载完整性校验用 HF **`x-linked-size`** 头(`content-length` 是 ~1.1KB xet 重定向桩,别信)。
4. **实测计时(640×352 / 73帧 / 4步 / int8 TE `device=cpu`)**:**222s** = CPU TE 编码 ~135s + GPU 采样+双 VAE ~90s,GPU 峰值 **15.6/16GB**(16GB 卡放得下 unet int8 + 激活;TE 27GB 只能挂 CPU)。
5. **语义验收**:首/中/尾三帧 vision 确认连贯(日出森林:金色晨光天空+镜面湖水倒影+松树剪影+薄雾),零噪声;**音频 32kHz FLAC 3.05s 真实生成**。产物存档 `docs/assets/h3-verified-strip.png` + `h3-official-withaudio.mp4`。
6. **API 直连坑**:`SaveVideo` 的 `format` 是 `COMFY_DYNAMICCOMBO_V3` 嵌套 widget——过得了 /prompt 校验但执行时崩(`execute() missing 'format'`,烧完 215s GPU 才炸)。**末端换平铺参数的 `SaveWEBM` + `SaveAudio`**,要 mp4 就 ffmpeg 合流转容器。

**修正后决策树**: ~~A(nunchaku W4A8/GGUF)~~ → **A'(官方 int8 safetensors + TE CPU)= RTX5000 现役方案** ✅;2080Ti 接入后同管线 TE 可常驻 GPU(22GB 装得下 int8 unet 20.97GB? 否——int8 unet 常驻+激活仍超 → 2080Ti 也用 TE CPU 或换 nvfp4/bf16 组合,待 §8 实测)。

---

## 8. 魔改卡专项验收(2080Ti 22G, 2026-09-20 新增)

原厂 2080Ti 只有 11GB,22GB = 第三方焊接换显存(352bit × 2GB 颗粒)→ 验收必须加项:

- [ ] `nvidia-smi --query-gpu=name,memory.total --format=csv` 显示 22GB 且稳定(不闪变)
- [ ] 显存压力测试: `cuda_memtest` 或满载渲染循环,24h 无 ECC 错误/温度墙/崩驱动
- [ ] 满载温度监控: `nvidia-smi dmon -s pucvmt` 长时间观察,不改散热前提下温度 <85°C
- [ ] 满载功耗: 坞 PSU ≥650W,压测期间无掉电/重启
- [ ] 连续渲染(10 段)无雷电链路掉线(不热拔、坞固定)

---

## 9. 验收清单(装机完成标准)

- [ ] `nvidia-smi` 双卡可见: `Quadro RTX 5000, 7.5` + `GeForce RTX 2080 Ti, 7.5`(魔改显存 22GB 稳定)
- [ ] 驱动 550 + nvidia-container-toolkit 配好,`docker run --rm --gpus all` 容器内 nvidia-smi 正常
- [ ] 持久化 + 自带卡功耗锁 80W 生效
- [ ] 开盖常开 + 屏幕 5 分钟自动熄灭 + 主机永不休眠(gsettings + logind 三项生效)
- [ ] Above 4G + TB Boot 开启,2080Ti 冷启动即认
- [ ] 模型 21.5GB 全部下载且 SHA-256 核验通过
- [ ] `docker compose up -d` 双实例 healthy(:8188/:8189 均 200)
- [x] **验证门(RTX5000)**: ✅ 2026-09-21 官方 int8 safetensors 管线 640×352/4步 **222s**,画面+音频语义通过(见 §7.1)。⚠️ 原 W4A8+GGUF 判据作废——GGUF 出纯噪声,官方 blueprint 才是正路
- [ ] **验证门(2080Ti)**: 未测(eGPU 未接入)
- [ ] 魔改卡 24h 压力测试通过(§8)
- [ ] 3 节点并行渲 3 段,scp 回 Mac 拼接成功
- [ ] 实测时间回填 §2.3

---

## 10. 相关资产

- 现网 H3 管线: `~/projects/xhs-pipeline/`(workflows-video/, h3-workflows/, scripts/h3-video/)
- 现网渲染事实与坑: skill `h3-video-pipeline`(480p/8步 ≈ 7.3min,直连提交官方三字段 prompt,音频 VAE fp32, CreateVideo+SaveVideo 节点名, filename_prefix 防混池, __pycache__ 坑)
- 现网 ComfyUI 容器: mini-ai-svr `/opt/ComfyUI` + podman toolbox(`strix-halo-comfyui` 镜像, comfy-mutex-proxy :8189 模式可参考;7550 上两实例各自串行队列即可,或复刻 mutex proxy)
- 本机 SSH: 新机需新建 key(建议沿用 `~/.ssh/` 管理,参考 `vps-onboarding` 流程)
