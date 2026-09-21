#!/usr/bin/env python3
"""h3-postbox: p7550 video post-service.

Pipeline (one job):
  1. render   : ComfyUI official int8 graph (:8189) -> seg.webm + ambient.flac (always)
  2. tts      : edge-tts -> voice.mp3 + word cues (skip if audio_mode=ambient)
  3. subtitle : ASS from word cues, delayed to speech start
  4. mux      : audio_mode a=voice only / b=ambient bed(-12dB)+voice / ambient=H3 audio only
  5. trim     : cut to speech_end + 0.5s breathing (B v4 discipline)

Serial queue (single GPU). Data: /home/david/h3postbox/data
"""
import asyncio, json, os, re, shutil, subprocess, threading, time, uuid
from pathlib import Path
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

COMFY = os.environ.get("COMFY_API", "http://127.0.0.1:8189")
DATA_DIR = Path(os.environ.get("POSTBOX_DATA", "/home/david/h3postbox/data"))
WF_PATH = Path(os.environ.get("WF_PATH", "/home/david/h3postbox/wf_base.json"))
VOICES_FILE = DATA_DIR / "voices.txt"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="h3-postbox")
_queue_lock = threading.Lock()   # serial GPU rendering
_jobs: dict = {}
for f in DATA_DIR.glob("job_*.json"):
    try:
        j = json.loads(f.read_text()); _jobs[j["id"]] = j
    except Exception:
        pass

def _save(j):
    (DATA_DIR / f"job_{j['id']}.json").write_text(json.dumps(j, ensure_ascii=False))

def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed rc={r.returncode}: {r.stderr[-400:]}")
    return (r.stdout or "").strip()

def ffprobe_dur(p):
    return float(sh(f'ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "{p}"'))

# ---------------- 1. render ----------------
def comfy_render(p: dict, workdir: Path) -> dict:
    wf = json.loads(WF_PATH.read_text())
    wf["8"]["inputs"].update(prompt=p["prompt"], width=p["width"], height=p["height"], length=p["length"])
    wf["11"]["inputs"]["steps"] = p["steps"]
    wf["12"]["inputs"]["noise_seed"] = p["seed"]
    prefix = f"pb/pb_{uuid.uuid4().hex[:8]}"
    wf["16"]["inputs"]["filename_prefix"] = prefix
    wf["17"]["inputs"]["filename_prefix"] = prefix + "_a"
    r = requests.post(f"{COMFY}/prompt", json={"prompt": wf, "client_id": "h3postbox"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"comfy submit {r.status_code}: {r.text[:300]}")
    pid = r.json()["prompt_id"]
    deadline = time.time() + p["timeout_s"]
    while time.time() < deadline:
        h = requests.get(f"{COMFY}/history/{pid}", timeout=15).json()
        if pid in h:
            got = {}
            for nid, o in h[pid].get("outputs", {}).items():
                for f in (o.get("files") or o.get("images") or []):
                    fn = f.get("filename", "")
                    if fn.endswith(".webm"): got["webm"] = f
                    if fn.endswith(".flac"): got["ambient"] = f
            if "webm" not in got:
                raise RuntimeError("render done but no webm output")
            if "ambient" not in got:
                # SaveAudio only writes when ffmpeg exists (image-official has none) -> audio node
                # silently produced no file. Same seed => deterministic audio; recover sibling .flac via /view.
                stem = re.sub(r"_00001\.webm$", "", got["webm"]["filename"])
                fn = f"{stem}_00001.flac"
                vb = requests.get(f"{COMFY}/view", params={"filename": fn,
                                   "subfolder": got["webm"].get("subfolder", ""), "type": "output"}, timeout=60)
                if vb.ok and vb.content[:4] == b"fLaC":
                    got["ambient"] = {"filename": fn, "subfolder": got["webm"].get("subfolder", ""), "type": "output"}
            out = {"prompt_id": pid}
            for k, f in got.items():
                dst = workdir / ("seg.webm" if k == "webm" else "ambient.flac")
                vb = requests.get(f"{COMFY}/view", params={"filename": f["filename"],
                                   "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}, timeout=120)
                dst.write_bytes(vb.content)
                out[k] = str(dst)
            return out
        time.sleep(5)
    raise RuntimeError("comfy render timeout")

# ---------------- 2. tts ----------------
async def _tts_run(text, voice, rate, mp3, words_json):
    import edge_tts
    if os.environ.get("EDGE_TTS_PROXY"):
        os.environ["HTTPS_PROXY"] = os.environ["EDGE_TTS_PROXY"]
    mp = edge_tts.Communicate(text=text, voice=voice, rate=rate or "+0%",
                              boundary="WordBoundary")
    sub = edge_tts.SubMaker()
    with open(mp3, "wb") as fh:
        async for c in mp.stream():
            if c["type"] == "audio":
                fh.write(c["data"])
            elif c["type"] == "WordBoundary":
                sub.feed(c)
    cues = [{"text": o.content,
             "start": o.start.total_seconds(),
             "dur": (o.end - o.start).total_seconds()} for o in sub.cues]
    Path(words_json).write_text(json.dumps(cues, ensure_ascii=False))
    return cues

def tts(text, voice, rate, workdir: Path):
    mp3, wj = workdir / "voice.mp3", workdir / "words.json"
    cues = asyncio.run(_tts_run(text, voice, rate, str(mp3), str(wj)))
    if mp3.stat().st_size < 1000 or not cues:
        raise RuntimeError("edge-tts produced empty audio/cues (network/proxy?)")
    return str(mp3), cues

def speech_lead_and_end(mp3):
    """Return (first_speech_start, speech_end) seconds via silencedetect."""
    r = subprocess.run(f'ffmpeg -v error -i "{mp3}" -af silencedetect=n=-45dB:d=0.25 -f null -',
                       shell=True, capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", r.stderr)]
    dur = ffprobe_dur(mp3)
    lead = ends[0] if (starts and starts[0] == 0.0 and ends) else 0.0
    # speech end = last silence_start if it is a trailing silence; else file end
    tail = starts[-1] if starts else None
    end = tail if (tail is not None and tail > dur - 1.5) else dur
    return lead, end

# ---------------- 3. subtitle ----------------
def ass_from_words(cues, lead, out_path, w, h, until=None):
    """One line per chunk: <=14 chars or punctuation break; times shifted by -lead.
    until: speech-relative cutoff — cues at/after it are dropped (clip mode)."""
    lines, buf, buf_start, buf_last_end = [], "", None, None
    for c in cues:
        s, e = c["start"], c["start"] + c["dur"]
        e = min(e, until) if until is not None else e
        if until is not None and s >= until:
            break
        if buf_start is None:
            buf_start = s
        buf += c["text"]
        buf_last_end = e
        if len(buf) >= 14 or buf[-1] in "，。！？、,.;":
            lines.append((buf, buf_start, buf_last_end)); buf, buf_start = "", None
    if buf.strip():
        lines.append((buf, buf_start, buf_last_end))
    def ts(t):
        t = max(t - lead, 0.0)
        return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"
    fs = int(h * 0.062)
    a = str(out_path).replace(":", "\\:")
    text = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Noto Sans CJK SC,%d,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,30,30,%d,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n") % (w, h, fs, int(h * 0.16))
    text += "\n".join(f"Dialogue: 0,{ts(s)},{ts(e)},Default,,0,0,0,,{ln}" for ln, s, e in lines) + "\n"
    Path(out_path).write_text(text, encoding="utf-8")
    # return ffmpeg ass= filter-safe path (escape ':' , no quotes — filtergraph breaks on quotes)
    return str(out_path).replace(":", "\\:")

# ---------------- 4. mux ----------------
def mux(video, ambient, voice_mp3, mode, ass_path, out, voice_cap=None, pad_to=None):
    """voice_cap: seconds of voice to keep (cut tail, no pad) so audio never outlives video.
    pad_to: freeze video tail frames until this duration (no-truncation mode)."""
    pad = f"-t {pad_to:.2f} " if pad_to else ""
    tbe = f"-t {pad_to:.2f} " if pad_to else "-shortest "
    tbe = "" if pad_to else "-shortest "   # tpad+stop_duration already sizes the video; let mux stop at longest
    vf = "format=yuv420p"
    if pad_to:
        vf = f"tpad=stop_mode=clone:stop_duration={pad_to:.2f},{vf}"   # freeze last frame (webm has no -loop)
    if ass_path:
        vf = f"ass={ass_path},{vf}"
    vc = f"[1:a]atrim=0:{voice_cap:.2f}," if voice_cap else "[1:a]"
    if mode == "ambient":
        cmd = (f'ffmpeg -y -v error -i "{video}" -i "{ambient}" -map 0:v:0 -map 1:a:0 '
               f'-c:v libx264 -preset fast -crf 20 -vf "{vf}" -c:a aac -b:a 128k -ar 48000 -shortest "{out}"')
    elif mode == "a":
        cmd = (f'ffmpeg -y -v error -i "{video}" -i "{voice_mp3}" -filter_complex '
               f'"{vc}loudnorm=I=-16:TP=-1.5:LRA=11[a]" -map 0:v:0 -map "[a]" '
               f'-c:v libx264 -preset fast -crf 20 -vf "{vf}" -c:a aac -b:a 128k -ar 48000 {tbe}"{out}"')
    else:  # b
        if ambient:
            fc = (f'{vc}loudnorm=I=-16:TP=-1.5:LRA=11[v];[2:a]volume={os.environ.get("AMBIENT_GAIN","-8dB")},afade=t=out:st={max(ffprobe_dur(ambient)-0.3,0):.2f}:d=0.3[amb];'
                  f'[v][amb]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.87[a]')
            cmd = (f'ffmpeg -y -v error -i "{video}" -i "{voice_mp3}" -i "{ambient}" -filter_complex '
                   f'"{fc}" -map 0:v:0 -map "[a]" '
                   f'-c:v libx264 -preset fast -crf 20 -vf "{vf}" -c:a aac -b:a 128k -ar 48000 {tbe}"{out}"')
        else:  # no ambient from render -> degrade to a
            return mux(video, None, voice_mp3, "a", ass_path, out, voice_cap, pad_to)
    sh(cmd)
    return out

# ---------------- job runner ----------------
def run_job(job):
    p = job["params"]; jd = Path(job["workdir"])
    try:
        # ---- checkpoint: reuse completed stages if re-submitted with same job dir ----
        rd = {}
        seg = jd / "seg.webm"; amb = jd / "ambient.flac"
        if seg.exists():
            rd["webm"] = str(seg)
            if amb.exists():
                rd["ambient"] = str(amb)
            job["render"] = rd
        if "webm" not in rd:
            job["stage"] = "render"; _save(job)
            rd = comfy_render(p, jd)
            job["render"] = rd; _save(job)
        ass_path, voice_mp3, lead, snd_end, cues = None, None, 0.0, None, None
        v_mp3, w_json = jd / "voice.mp3", jd / "words.json"
        if p["audio_mode"] != "ambient" and p["voice_text"]:
            if v_mp3.exists() and v_mp3.stat().st_size > 1000 and w_json.exists():
                voice_mp3, cues = str(v_mp3), json.loads(w_json.read_text())
            else:
                job["stage"] = "tts"; _save(job)
                voice_mp3, cues = tts(p["voice_text"], p["voice"], p["rate"], jd)
            lead, snd_end = speech_lead_and_end(voice_mp3)
            job["tts"] = {"mp3": voice_mp3, "cues": len(cues), "lead": round(lead, 2), "speech_end": round(snd_end, 2)}
            _save(job)
        job["stage"] = "mux"; _save(job)
        v_dur = ffprobe_dur(rd["webm"])
        voice_cap, pad_to = None, None
        if voice_mp3:
            sp_avail = v_dur + lead          # speech-relative time the video can cover
            voice_dur = min(snd_end, ffprobe_dur(voice_mp3))
            if voice_dur > sp_avail:
                if p.get("pad_video"):
                    pad_to = voice_dur - v_dur + 0.5   # tpad extends video; whole voice kept
                else:
                    voice_cap = sp_avail      # keep only what fits on video (speech-rel)
                    job["tts"]["clipped"] = True
            job["tts"]["pad_video"] = bool(pad_to)
            if p["burn_subtitle"]:
                job["stage"] = "subtitle"; _save(job)
                ass_path = ass_from_words(cues, lead, jd / "subs.ass", p["width"], p["height"], until=voice_cap)
            _save(job)
        mux(rd["webm"], rd.get("ambient"), voice_mp3, p["audio_mode"], ass_path, jd / "final_raw.mp4",
            voice_cap=voice_cap, pad_to=pad_to)
        if p["trim"] and p["audio_mode"] != "ambient" and snd_end:
            job["stage"] = "trim"; _save(job)
            raw_dur = ffprobe_dur(jd / "final_raw.mp4")
            target = min(snd_end + 0.5, raw_dur)
            if target < raw_dur - 0.05:   # only trim when there's slack (pad mode: raw==speech+0.5, skip)
                sh(f'ffmpeg -y -v error -i "{jd}/final_raw.mp4" -t {target:.2f} -c copy "{jd}/final.mp4"')
            else:
                shutil.move(str(jd / "final_raw.mp4"), str(jd / "final.mp4"))
        else:
            shutil.move(str(jd / "final_raw.mp4"), str(jd / "final.mp4"))
        d = ffprobe_dur(jd / "final.mp4")
        job.update(status="done", stage="done", out=str(jd / "final.mp4"), duration=round(d, 2))
    except Exception as e:
        job.update(status="error", error=str(e)[:600])
    _save(job)

class Params(BaseModel):
    prompt: str
    voice_text: str = ""
    audio_mode: str = Field("b", pattern="^(a|b|ambient)$")
    voice: str = "zh-CN-YunxiNeural"
    rate: str = "-10%"
    width: int = 640; height: int = 352; length: int = 73; steps: int = 4
    seed: int = 1
    burn_subtitle: bool = True
    trim: bool = True
    pad_video: bool = False
    timeout_s: int = 1800

@app.post("/jobs")
def create_job(params: Params):
    if params.audio_mode == "ambient" and not params.voice_text:
        pass
    jid = uuid.uuid4().hex[:10]
    wd = DATA_DIR / f"job_{jid}"; wd.mkdir(parents=True, exist_ok=True)
    job = {"id": jid, "status": "queued", "stage": "queued", "params": params.model_dump(),
           "workdir": str(wd), "created": time.time()}
    _jobs[jid] = job; _save(job)
    def worker():
        with _queue_lock:
            job["status"] = "running"; _save(job)
            run_job(job)
    threading.Thread(target=worker, daemon=True).start()
    pending = sum(1 for j in _jobs.values() if j["status"] in ("queued", "running"))
    return {"job_id": jid, "pending": pending}

@app.get("/jobs/{jid}")
def get_job(jid: str):
    j = _jobs.get(jid)
    if not j:
        raise HTTPException(404, "no job")
    return {k: j.get(k) for k in ("id", "status", "stage", "error", "out", "duration", "render", "tts", "params")}

@app.get("/jobs")
def list_jobs():
    return [{"id": j["id"], "status": j["status"], "stage": j["stage"], "created": j.get("created")}
            for j in sorted(_jobs.values(), key=lambda x: x.get("created", 0))]

@app.post("/jobs/{jid}/retry")
def retry_job(jid: str):
    """Re-run a failed job; completed stage artifacts (seg.webm/ambient.flac/voice.mp3) are reused."""
    j = _jobs.get(jid)
    if not j:
        raise HTTPException(404, "no job")
    if j["status"] == "done":
        return {"job_id": jid, "note": "already done", "out": j.get("out")}
    j["status"] = "queued"; j["stage"] = "retry"; j.pop("error", None); _save(j)
    def worker():
        with _queue_lock:
            j["status"] = "running"; _save(j)
            run_job(j)
    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": jid, "requeued": True}

@app.get("/jobs/{jid}/file")
def job_file(jid: str):
    j = _jobs.get(jid)
    if not j or j.get("status") != "done" or not Path(j.get("out", "")).exists():
        raise HTTPException(404, "not done")
    return FileResponse(j["out"], media_type="video/mp4", filename=f"h3_{jid}.mp4")

@app.get("/health")
def health():
    ok = False
    try:
        ok = requests.get(f"{COMFY}/system_stats", timeout=5).status_code == 200
    except Exception:
        pass
    return {"ok": True, "comfy_up": ok, "jobs": len(_jobs)}

@app.get("/voices")
def voices():
    if VOICES_FILE.exists():
        return {"voices": VOICES_FILE.read_text().splitlines()}
    import edge_tts
    try:
        v = asyncio.run(edge_tts.list_voices())
        zh = sorted({x["ShortName"] for x in v if x["Locale"].startswith("zh")})
        VOICES_FILE.write_text("\n".join(zh))
        return {"voices": zh}
    except Exception as e:
        return {"voices": ["zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural"], "note": f"list failed: {e}"}
