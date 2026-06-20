"""タイマーアイコン生成スクリプト
参照デザイン: 5色セグメントリング + 中央時刻テキスト
"""
from PIL import Image, ImageDraw, ImageFont
import math
from pathlib import Path

# ── セグメント定義（PIL角度: 0°=3時, 時計回り） ──────────────────────────
# 12時=270°, 3時=0°, 6時=90°, 9時=180°
# ギャップを 12/3/6/9 の位置に配置
SEGMENTS = [
    (272, 325, "#F5C000"),   # 金色  12〜2時
    (330, 357, "#44DD44"),   # 緑    2〜3時
    (  3,  88, "#3377EE"),   # 青    3〜6時
    ( 93, 177, "#EE3333"),   # 赤    6〜9時
    (183, 265, "#9933CC"),   # 紫    9〜12時
]

BG_COLOR  = (13, 20, 58, 255)   # 濃紺 #0d143a
FONT_PATHS = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _draw_raw(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 丸角正方形の背景
    cr = int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=cr, fill=BG_COLOR)

    cx = cy  = size / 2
    r_out    = size * 0.415    # リング外径
    r_in     = size * 0.282    # リング内径
    ring_w   = max(1, int(r_out - r_in))
    ring_bb  = [cx - r_out, cy - r_out, cx + r_out, cy + r_out]

    # セグメント弧
    for start, end, color in SEGMENTS:
        draw.arc(ring_bb, start=start, end=end, fill=color, width=ring_w)

    # ティックマーク（12/3/6/9時 の半径方向の白い短線）
    ta = r_out - size * 0.025   # 内端（外リング縁のやや内側）
    tb = r_out + size * 0.07    # 外端
    tw = max(1, round(size / 55))
    tc = (255, 255, 255, 230)
    for deg in [270, 0, 90, 180]:
        rad = math.radians(deg)
        draw.line(
            [cx + ta * math.cos(rad), cy + ta * math.sin(rad),
             cx + tb * math.cos(rad), cy + tb * math.sin(rad)],
            fill=tc, width=tw
        )

    # 中央テキスト（64px 以上で描画）
    if size >= 64:
        fsize = int(size * 0.168)
        font  = None
        for fp in FONT_PATHS:
            if Path(fp).exists():
                font = ImageFont.truetype(fp, fsize)
                break

        if font:
            text  = "60:00"
            bbox  = draw.textbbox((0, 0), text, font=font)
            tw_t  = bbox[2] - bbox[0]
            th_t  = bbox[3] - bbox[1]
            draw.text(
                (cx - tw_t / 2 - bbox[0], cy - th_t / 2 - bbox[1]),
                text,
                fill=(255, 255, 255, 255),
                font=font,
            )

    return img


def create_icon(size: int) -> Image.Image:
    """4倍サイズで描いてダウンサンプリング → スムーズなエッジ"""
    raw = _draw_raw(size * 4)
    return raw.resize((size, size), Image.Resampling.LANCZOS)


def make_ico():
    base = Path(__file__).parent
    ico_path  = base / "timer.ico"
    prev_path = base / "timer_preview.png"

    sizes = [16, 24, 32, 48, 64, 128, 256]
    print("アイコン生成中…", end="", flush=True)
    icons = [create_icon(s) for s in sizes]
    icons[-1].save(ico_path, format="ICO", append_images=icons[:-1])
    print(" 完了")

    # 512px プレビュー PNG を保存
    create_icon(512).save(prev_path)
    print(f"ICO:      {ico_path}  ({ico_path.stat().st_size:,} bytes)")
    print(f"Preview:  {prev_path}")


if __name__ == "__main__":
    make_ico()
