#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XHS 封面生成器 v4 (单图封面 + 可选指定配图索引)
输入: draft 目录 (含 img-*.png + note.md)
输出: cover.png (1240x1656, 指定配图 3:4 裁切 + 顶部标题 + 底部水印)
     默认取第 1 张; --index N 取第 N 张 (1-based), 输出 cover-{N}.png

用法: python3 cover_gen.py <draft_dir> [--title "T"] [--sub "S"] [--index N] [--out cover.png]
"""
import os, sys, glob, argparse
from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1240, 1656
MARGIN = 36
TITLE_TOP = 100          # 标题起始 y
SUBTITLE_TOP = 300       # 副标题 y
FADE_H = 340             # 顶部渐变遮罩高度 (保证文字可读)
FADE_BOTTOM = 140        # 底部水印区高度
TITLE_MAX_W = CANVAS_W - 2 * MARGIN
TITLE_FONT_START = 92
TITLE_FONT_MIN = 48

FONT_CANDIDATES = [
    "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc",
    "/usr/share/fonts/google-noto-serif-cjk-vf-fonts/NotoSerifCJK-VF.ttc",
    "/System/Library/Fonts/PingFang.ttc",           # macOS
    "/System/Library/Fonts/STHeiti Light.ttc",       # macOS
    "/Library/Fonts/Arial Unicode.ttf",              # macOS
]

def find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None

def load_title(draft_dir, fallback=""):
    note = os.path.join(draft_dir, "note.md")
    try:
        with open(note, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
    except Exception:
        pass
    return fallback

def fit_font(draw, text, font_path, max_w, start_size, min_size):
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        if draw.textlength(text, font=font) <= max_w:
            return font, size
        size -= 2
    return ImageFont.truetype(font_path, min_size), min_size

def truncate_by_width(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while len(text) > 0:
        cand = text[:-1] + "…"
        if draw.textlength(cand, font=font) <= max_w:
            return cand
        text = text[:-1]
    return text[:1] + "…"

def cover_crop(img, canvas_w, canvas_h):
    iw, ih = img.size
    target_ratio = canvas_w / canvas_h  # 0.749
    cur_ratio = iw / ih
    if cur_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        x0 = (iw - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, ih))
    else:
        new_h = int(iw / target_ratio)
        y0 = (ih - new_h) // 2
        img = img.crop((0, y0, iw, y0 + new_h))
    return img.resize((canvas_w, canvas_h), Image.LANCZOS)

def add_top_fade(img, fade_h):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(fade_h):
        alpha = int(200 * (1 - y / fade_h))
        od.line([(0, y), (img.width, y)], fill=(0, 0, 0, alpha))
    img = img.convert("RGBA")
    return Image.alpha_composite(img, overlay)

def add_bottom_fade(img, fade_h):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    h = img.height
    for y in range(fade_h):
        alpha = int(200 * (1 - (fade_h - y) / fade_h))
        od.line([(0, h - fade_h + y), (img.width, h - fade_h + y)], fill=(0, 0, 0, alpha))
    img = img.convert("RGBA")
    return Image.alpha_composite(img, overlay)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft_dir")
    ap.add_argument("--title", default="")
    ap.add_argument("--sub", default="")
    ap.add_argument("--index", type=int, default=1, help="1-based 配图索引, 默认 1 (第一张)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    imgs = sorted(glob.glob(os.path.join(args.draft_dir, "img-*.png")))
    if not imgs:
        imgs = sorted(glob.glob(os.path.join(args.draft_dir, "img-*.jpeg"))) + \
               sorted(glob.glob(os.path.join(args.draft_dir, "img-*.jpg")))
    if not imgs:
        print("ERROR: no img-* files in", args.draft_dir)
        sys.exit(1)

    idx = max(1, min(args.index, len(imgs))) - 1
    img_path = imgs[idx]
    print(f"cover from (index {args.index}): {img_path}")

    canvas = Image.open(img_path).convert("RGB")
    canvas = cover_crop(canvas, CANVAS_W, CANVAS_H)
    canvas = add_top_fade(canvas, FADE_H)
    canvas = add_bottom_fade(canvas, FADE_BOTTOM)
    canvas = canvas.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    font_path = find_font()
    title = args.title or load_title(args.draft_dir)
    if not title:
        title = "装修干货"

    if font_path:
        font_title, size_used = fit_font(draw, title, font_path, TITLE_MAX_W, TITLE_FONT_START, TITLE_FONT_MIN)
        font_sub = ImageFont.truetype(font_path, 44)
        font_footer = ImageFont.truetype(font_path, 34)
    else:
        font_title = font_sub = font_footer = ImageFont.load_default()
        size_used = 0

    if size_used <= TITLE_FONT_MIN:
        title = truncate_by_width(draw, title, font_title, TITLE_MAX_W)

    tw = draw.textlength(title, font=font_title)
    draw.text(((CANVAS_W - tw) / 2, TITLE_TOP), title, fill=(255, 255, 255), font=font_title, stroke_width=2, stroke_fill=(30, 30, 30))
    print(f"title: {title!r} size={size_used}px")

    if args.sub:
        tw2 = draw.textlength(args.sub, font=font_sub)
        draw.text(((CANVAS_W - tw2) / 2, SUBTITLE_TOP), args.sub, fill=(255, 255, 255), font=font_sub, stroke_width=1, stroke_fill=(30, 30, 30))

    footer = "宅有宅的道理 | 装修干货"
    tw3 = draw.textlength(footer, font=font_footer)
    draw.text(((CANVAS_W - tw3) / 2, CANVAS_H - 90), footer, fill=(255, 255, 255), font=font_footer, stroke_width=1, stroke_fill=(30, 30, 30))

    # 输出文件名: 显式 --out 优先; 否则 index>1 时 cover-{index}.png, 默认 cover.png
    if args.out:
        out_path = args.out if os.path.isabs(args.out) else os.path.join(args.draft_dir, args.out)
    else:
        fname = f"cover-{args.index}.png" if args.index > 1 else "cover.png"
        out_path = os.path.join(args.draft_dir, fname)
    canvas.save(out_path, "PNG")
    print(f"COVER_SAVED: {out_path} {canvas.width}x{canvas.height}")

if __name__ == "__main__":
    main()
