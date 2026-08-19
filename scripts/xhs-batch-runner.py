#!/usr/bin/env python3
"""
xhs-batch-runner: 复刻 n8n MVP-1 workflow, 批量跑多个主题。
用途: 验证文案/出图稳定性, 不占 n8n UI。
"""
import json
import os
import random
import time
import urllib.request
import urllib.parse
from datetime import datetime

THEMES = [
    "露营装备开箱 - 迪卡侬新品",
    "香港茶餐厅 3 小时探店",
    "新手健身房自救指南",
    "分手 3 个月后我做了这些事",
]

HAUHAU_URL = "http://127.0.0.1:8080/v1/chat/completions"
COMFY_URL = "http://127.0.0.1:8189"  # via mutex proxy
DRAFTS_ROOT = "/home/david/xhs-drafts"
EXAMPLES_DIR = "/home/david/xhs-examples"


def read_examples():
    files = [f for f in os.listdir(EXAMPLES_DIR) if f.endswith('.md') and 'README' not in f]
    random.shuffle(files)
    picks = files[:3]
    return "\n\n---\n\n".join(open(os.path.join(EXAMPLES_DIR, f)).read() for f in picks)


def hauhau_generate(theme, examples, max_retries=6):
    sys_msg = (
        "你是专业的小红书爆款文案师。风格: 标题15字内带emoji有钩子; "
        "正文200-400字短句多段emoji点缀; 结尾3-5个疑问句/CTA; 8-10个中文tag; "
        "3张配图prompt用英文, 每个60词内, 描述具体场景+光线+构图。\n\n"
        "严格返回JSON: {\"title\":\"...\", \"body\":\"...\", \"tags\":[\"tag1\",...], "
        "\"image_prompts\":[\"en1\",\"en2\",\"en3\"]}\n\n"
        f"参考优秀笔记范例:\n\n{examples}"
    )
    body = {
        "model": "Qwen3.6-35B-Hauhau",
        "temperature": 0.85,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": f"主题: {theme}"},
        ],
    }
    req = urllib.request.Request(
        HAUHAU_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    last_err = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            raw = d["choices"][0]["message"]["content"]
            return json.loads(raw)
        except (urllib.error.URLError, ConnectionError) as e:
            last_err = e
            wait = 20
            print(f"    hauhau retry {attempt+1}/{max_retries} after {wait}s ({e})", flush=True)
            time.sleep(wait)
    raise last_err


def comfy_gen_image(prompt_text, filename_prefix):
    seed = random.randint(1, 10**9)
    workflow = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'qwen_image_fp8_e4m3fn.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'qwen_2.5_vl_7b_fp8_scaled.safetensors', 'type': 'qwen_image'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'qwen_image_vae.safetensors'}},
        '4': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['1', 0], 'shift': 3.1}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': prompt_text}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': ''}},
        '7': {'class_type': 'EmptySD3LatentImage', 'inputs': {'width': 1024, 'height': 1024, 'batch_size': 1}},
        '8': {'class_type': 'KSampler', 'inputs': {'model': ['4', 0], 'positive': ['5', 0], 'negative': ['6', 0], 'latent_image': ['7', 0], 'seed': seed, 'steps': 20, 'cfg': 2.5, 'sampler_name': 'euler', 'scheduler': 'simple', 'denoise': 1.0}},
        '9': {'class_type': 'VAEDecode', 'inputs': {'samples': ['8', 0], 'vae': ['3', 0]}},
        '10': {'class_type': 'SaveImage', 'inputs': {'images': ['9', 0], 'filename_prefix': filename_prefix}},
    }
    req = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=json.dumps({"prompt": workflow, "client_id": "batch"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    prompt_id = d["prompt_id"]

    deadline = time.time() + 900
    while time.time() < deadline:
        with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=10) as r:
            hist = json.loads(r.read())
        if prompt_id in hist:
            entry = hist[prompt_id]
            st = entry.get("status", {})
            if st.get("completed"):
                for out in entry.get("outputs", {}).values():
                    for img in out.get("images", []):
                        url = f"{COMFY_URL}/view?filename={img['filename']}&subfolder={img.get('subfolder','')}&type=output"
                        with urllib.request.urlopen(url, timeout=30) as r:
                            return img["filename"], r.read()
            if st.get("status_str") == "error":
                raise RuntimeError(f"comfy error: {entry}")
        time.sleep(3)
    raise TimeoutError(f"prompt {prompt_id} timeout")


def run_theme(theme, idx):
    print(f"\n[{idx}/{len(THEMES)}] === {theme} ===", flush=True)
    t0 = time.time()

    print(f"  [{time.strftime('%H:%M:%S')}] hauhau...", flush=True)
    examples = read_examples()
    data = hauhau_generate(theme, examples)
    print(f"  hauhau ok: title='{data['title']}'  ({time.time()-t0:.0f}s)", flush=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_theme = f"theme{idx}"  # 用序号避免中文文件名问题
    draft_dir = f"{DRAFTS_ROOT}/{ts}-{safe_theme}"
    os.makedirs(draft_dir, exist_ok=True)

    md = f"# {data['title']}\n\n{data['body']}\n\n"
    md += " ".join(f"#{t}" for t in data.get("tags", []))
    md += "\n"

    for i, prompt in enumerate(data["image_prompts"][:3], 1):
        img_t0 = time.time()
        print(f"  [{time.strftime('%H:%M:%S')}] img {i}/3...", flush=True)
        fname, img_bytes = comfy_gen_image(prompt, f"batch-{safe_theme}-{i}")
        dest = f"{draft_dir}/img-{i}-{fname}"
        with open(dest, "wb") as f:
            f.write(img_bytes)
        md += f"\n![img-{i}](img-{i}-{fname})\n"
        print(f"    img {i} saved ({time.time()-img_t0:.0f}s, {len(img_bytes)//1024}KB)", flush=True)

    with open(f"{draft_dir}/note.md", "w") as f:
        f.write(md)

    total = time.time() - t0
    print(f"  ✅ done in {total/60:.1f}min → {draft_dir}", flush=True)
    return draft_dir


def main():
    print(f"start batch: {len(THEMES)} themes, ~{len(THEMES)*11}min", flush=True)
    results = []
    for i, theme in enumerate(THEMES, 1):
        try:
            results.append((theme, run_theme(theme, i)))
        except Exception as e:
            print(f"  ❌ {theme} FAILED: {e}", flush=True)
            results.append((theme, f"ERROR: {e}"))

    print("\n=== SUMMARY ===", flush=True)
    for theme, res in results:
        print(f"  {theme}: {res}", flush=True)


if __name__ == "__main__":
    main()
