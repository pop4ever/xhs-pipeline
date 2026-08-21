#!/usr/bin/env python3
"""03篇 scene_plan PIL 标注叠加 — 无字底图 + 白标签框+黑字+虚线连点位 (100% 准确)
仿 02 篇标注范式: 白底黑字标签框, 虚线连到点位, 中文用系统字体。
"""
import json, os
from PIL import Image, ImageDraw, ImageFont

SRC = "/tmp/xhs03-clean-local"
OUT = "/tmp/xhs03-labeled"
os.makedirs(OUT, exist_ok=True)

SP = json.load(open("/Users/weidu/projects/xhs-pipeline/scene_plans/scene_plan_xiaomi_smart.json"))

# 中文字体 (macOS PingFang)
def get_font(size):
    for p in ["/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/STHeiti Light.ttc",
              "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

# 每张图的点位坐标 (y 从上到下, 大致对应场景, 标注框放图两侧避免遮挡)
# 格式: {img_idx: [(label, x_center, y_center), ...]}  x,y 为 1024 图中比例 0-1
POSITIONS = {
    1: [  # 客厅
        ("智能开关 零火版 130cm", 0.50, 0.42), ("窗帘电机 220cm", 0.82, 0.18),
        ("人在传感器 200cm", 0.85, 0.85), ("电视墙 插座 50cm", 0.25, 0.60),
        ("智能面板 130cm", 0.15, 0.45), ("空调 智能插座 220cm", 0.75, 0.72),
        ("智能中控屏 150cm", 0.38, 0.38),
    ],
    2: [  # 玄关
        ("智能门锁 门体", 0.30, 0.55), ("玄关 智能开关 130cm", 0.62, 0.40),
        ("智能面板 130cm", 0.70, 0.55), ("人在传感器 200cm", 0.85, 0.12),
        ("鞋柜 插座 烘鞋机 30cm", 0.45, 0.85),
    ],
    3: [  # 厨房
        ("轨道插座 台面 110cm", 0.50, 0.70), ("水浸卫士 水槽下 30cm", 0.30, 0.85),
        ("烟感卫士 吊顶 220cm", 0.50, 0.10), ("天然气卫士 燃气表旁", 0.75, 0.55),
        ("冰箱 插座 50cm", 0.12, 0.50), ("烟机 插座 220cm", 0.55, 0.30),
        ("蒸烤箱 插座 50cm", 0.85, 0.45),
    ],
    4: [  # 卧室
        ("窗帘电机 220cm", 0.85, 0.15), ("人在传感器 200cm", 0.85, 0.85),
        ("床头 智能插座 70cm", 0.30, 0.60), ("空调 智能插座 220cm", 0.70, 0.72),
        ("门窗传感器 窗框", 0.15, 0.25),
    ],
    5: [  # 卫生间
        ("智能镜前灯 插座 130cm", 0.55, 0.35), ("智能马桶盖 插座 40cm", 0.85, 0.55),
        ("浴霸 开关 130cm", 0.30, 0.40), ("热水器 插座 180cm", 0.45, 0.80),
        ("人体感应 传感器 200cm", 0.85, 0.12), ("水浸卫士 地漏旁 30cm", 0.30, 0.85),
    ],
    6: [  # 书房
        ("中枢网关 30cm", 0.30, 0.35), ("全屋路由 网口+插座 40cm", 0.45, 0.45),
        ("智能插座 排插 30cm", 0.60, 0.55), ("NAS 打印机 插座 40cm", 0.70, 0.65),
        ("智能面板 130cm", 0.35, 0.65),
    ],
    7: [  # 全屋点位汇总(平面图)
        ("客厅 12点位", 0.35, 0.30), ("玄关 5点位", 0.15, 0.35),
        ("厨房 8点位", 0.20, 0.60), ("卧室 6点位", 0.65, 0.30),
        ("卫生间 4点位", 0.55, 0.65), ("书房 5点位", 0.80, 0.55),
        ("弱电箱 网线+光纤+零线", 0.50, 0.85), ("插座 五孔 30cm", 0.30, 0.75),
        ("智能开关 零火版 130cm", 0.45, 0.15), ("人在传感器 顶角 200cm", 0.85, 0.85),
    ],
}

FONT = get_font(30)
SMALL = get_font(24)

def label_box(d, x, y, text, font):
    """白底黑字标签框 + 圆角 + 下方小圆点连点位"""
    tb = d.textbbox((0, 0), text, font=font)
    w = tb[2] - tb[0] + 24
    h = tb[3] - tb[1] + 16
    x0, y0 = x - w // 2, y - h // 2
    # 白色半透明底
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=8, fill=(255, 255, 255, 235), outline=(0, 0, 0, 255), width=2)
    d.text((x0 + 12, y0 + 6), text, font=font, fill=(0, 0, 0, 255))

for idx, pos_list in POSITIONS.items():
    # 找底图
    files = sorted([f for f in os.listdir(SRC) if f.startswith(f"c-{idx:02d}-")])
    if not files:
        print(f"[{idx}] 底图缺失, 跳过")
        continue
    src = os.path.join(SRC, files[0])
    img = Image.open(src).convert("RGBA")
    W, H = img.size  # 1024x1024
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for label, fx, fy in pos_list:
        x, y = int(fx * W), int(fy * H)
        # 虚线连点位 (画到标签框上方小点)
        d.line([(x, y), (x, y - 18)], fill=(0, 0, 0, 200), width=2)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(200, 40, 40, 255))
        label_box(d, x, y - 60, label, FONT)
    final = Image.alpha_composite(img, overlay)
    out = os.path.join(OUT, f"03-{idx:02d}-labeled.png")
    final.convert("RGB").save(out)
    print(f"✅ {out}")

print("==== PIL 标注完成 ====")
