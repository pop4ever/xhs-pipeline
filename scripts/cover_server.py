#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XHS 封面生成 HTTP 微服务 v2 (跑在 mini host, n8n 容器通过 HTTP 调用)
POST /cover  {draft_dir, sub, indices:[1,7]}  → 生成 cover-1.png / cover-7.png → 返回 {cover_paths: [...]}
  - indices 缺省 [1] → 只生成 cover.png (兼容旧调用)
  - indices=[1,7] → 生成 cover-1.png + cover-7.png
GET  /health → {status:ok}
监听 127.0.0.1:8765 (n8n 容器 host network 可直接访问)
"""
import os, sys, json, subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8765
SCRIPT = "/home/david/xhs-cover-venv/cover_gen.py"

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode() or "{}")
            draft_dir = payload.get("draft_dir", "")
            sub = payload.get("sub", "")
            indices = payload.get("indices") or [1]
            if not isinstance(indices, list) or not indices:
                indices = [1]
            if not draft_dir or not os.path.isdir(draft_dir):
                self._send(400, {"error": "draft_dir missing or not a dir"})
                return
            has_img = any(f.startswith("img-") for f in os.listdir(draft_dir))
            if not has_img:
                self._send(400, {"error": "no img-* files in draft_dir"})
                return
            cover_paths = []
            for idx in indices:
                cmd = [sys.executable, SCRIPT, draft_dir, "--index", str(idx)]
                if sub:
                    cmd += ["--sub", sub]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if r.returncode != 0:
                    self._send(500, {"error": r.stderr.strip()[:500], "index": idx})
                    return
                # 解析输出文件名: cover-{idx}.png (idx=1 → cover.png)
                fname = f"cover-{idx}.png" if idx != 1 else "cover.png"
                cover_paths.append(os.path.join(draft_dir, fname))
            self._send(200, {"cover_paths": cover_paths, "detail": "ok"})
        except Exception as e:
            self._send(500, {"error": str(e)})

def main():
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"XHS cover server v2 on :{PORT}")
    srv.serve_forever()

if __name__ == "__main__":
    main()
