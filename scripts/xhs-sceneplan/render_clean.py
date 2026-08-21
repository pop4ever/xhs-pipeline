#!/usr/bin/env python3
"""通用 scene_plan 无字底图渲染 — 04-08 篇复用
用法: python3 render_clean.py <scene_plan.json> <out_dir> <prefix>
"""
import json, time, urllib.request, os, sys

COMFY = "http://127.0.0.1:8188"
SP_PATH, OUT, PREFIX = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)

SP = json.load(open(SP_PATH))
STYLE = SP["style_prefix"]
NEG = "text, letters, words, labels, captions, watermark, logo, checklist, table, spreadsheet, printed document, handwriting, typography, signage, tape labels, measurement marks, dimensions, numbers, ruler, scale markings, diagram, schematic, english text, english letters, alphabet, ascii, font, lettering, foreign person, white person, black person, western face"

def make_workflow(prompt_text, neg_text, idx):
    seed = int(time.time() * 1000) % 1000000000 + idx
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt_text}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": neg_text}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0], "seed": seed, "steps": 20, "cfg": 2.5, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": f"{PREFIX}-{idx:02d}"}},
    }

def submit(workflow):
    req = urllib.request.Request(f"{COMFY}/prompt", data=json.dumps({"prompt": workflow}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def poll(prompt_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"{COMFY}/history/{prompt_id}", timeout=15) as r:
                h = json.loads(r.read())
            if prompt_id in h:
                st = h[prompt_id].get("status", {})
                if st.get("completed"):
                    return h[prompt_id]
                if st.get("status_str") == "error":
                    return None
        except Exception:
            pass
        time.sleep(10)
    return None

def download(fname):
    req = urllib.request.Request(f"{COMFY}/view?filename={fname}&subfolder=&type=output")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

imgs = SP["images"]
print(f"{PREFIX}: {len(imgs)} 张无字底图", flush=True)
for i, img in enumerate(imgs, 1):
    existing = [f for f in os.listdir(OUT) if f.startswith(f"{PREFIX}-{i:02d}-")]
    if existing:
        print(f"[{i}] 已存在, 跳过", flush=True)
        continue
    prompt_text = STYLE + " " + img["scene"] + " no text, no labels, no letters, no numbers, no watermark."
    wf = make_workflow(prompt_text, NEG, i)
    print(f"[{i}/{len(imgs)}] 提交: {img['scene'][:45]}...", flush=True)
    for attempt in range(2):
        try:
            resp = submit(wf)
            pid = resp.get("prompt_id")
            print(f"  a{attempt+1}: {pid}", flush=True)
            done = poll(pid)
            if not done or done is None:
                print("  !! 失败, 重试", flush=True)
                continue
            fname = None
            for nid, o in done.get("outputs", {}).items():
                for im in o.get("images", []):
                    fname = im["filename"]
            if fname:
                data = download(fname)
                outpath = os.path.join(OUT, f"{PREFIX}-{i:02d}-{fname}")
                with open(outpath, "wb") as f:
                    f.write(data)
                print(f"  ✅ {outpath}", flush=True)
                break
        except Exception as e:
            print(f"  ❌ {e}", flush=True)
            time.sleep(5)
print(f"==== {PREFIX} 完成 ====", flush=True)
