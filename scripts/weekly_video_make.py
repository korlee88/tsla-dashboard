"""
TSLA 주간 나레이션 영상 생성 (moviepy 2.x + 애니메이션)
weekly_video_prep.py 실행 후 사용.
script.json + scene_XX.png → edge-tts MP3 → 애니메이션 MP4

필요 패키지:
  pip install edge-tts moviepy pillow numpy
"""

import os, json, sys, asyncio, math
from pathlib import Path

REPORT_BASE   = Path(__file__).parent.parent / "data" / "weekly-report"
VOICE         = "ko-KR-HyunsuNeural"   # 캐주얼 남성 (활기찬 MC 톤)
RATE          = "+50%"                 # 약간 여유있게 (너무 빠르면 전달력↓)
PITCH         = "+12%"                 # 톤업 → 밝고 에너지 넘치는 느낌
FPS           = 24
W, H          = 1280, 720
MIN_SCENE_SEC = 5.0

ACCENT_COLORS = [
    (167, 139, 250),  # scene1 purple
    (34,  197,  94),  # scene2 green
    (239,  68,  68),  # scene3 red
    (245, 158,  11),  # scene4 amber
    (6,  182, 212),   # scene5 cyan
]
SCENE_MOODS = ["excited", "happy", "worried", "focused", "happy"]

# ── 유틸 ──────────────────────────────────────────────────────────────────────

def find_latest_report():
    if not REPORT_BASE.exists():
        return None
    dirs = sorted(
        [d for d in REPORT_BASE.iterdir()
         if d.is_dir() and (d / "script.json").exists()],
        reverse=True,
    )
    return dirs[0] if dirs else None


def find_font():
    for p in [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(p):
            return p
    return None


def clean_for_tts(lines):
    table = {
        '【': '', '】': '', '①': '첫째,', '②': '둘째,', '③': '셋째,',
        '④': '넷째,', '⑤': '다섯째,', '$': '달러 ', '%': '퍼센트,',
        '+': '플러스 ', '─': '', '▲': '', '▼': '',
        '🟢': '', '🔴': '', '📊': '', '📈': '', '✓': '', '⚡': '',
    }
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        for k, v in table.items():
            line = line.replace(k, v)
        result.append(line)
    return ' '.join(result)

# ── TTS ───────────────────────────────────────────────────────────────────────

async def gen_audio(text, path):
    import edge_tts
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    await comm.save(str(path))

# ── 로봇 마스코트 ─────────────────────────────────────────────────────────────

def draw_robot_pil(img, rx, ry, mood="neutral", accent=(167, 139, 250)):
    """Pillow 도형으로 로봇 캐릭터를 img 위에 합성."""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d     = ImageDraw.Draw(layer)
    BODY  = (38, 44, 60)
    METAL = (78, 88, 112)
    SHINE = (215, 225, 240)
    _G    = (34, 197, 94)
    _R    = (239, 68, 68)
    _A    = (245, 158, 11)

    ax = rx + 50
    d.line([ax, ry-26, ax, ry], fill=METAL, width=3)
    d.ellipse([ax-8, ry-36, ax+8, ry-20], fill=accent, outline=SHINE, width=1)
    d.rounded_rectangle([rx, ry, rx+100, ry+86], radius=18, fill=BODY, outline=METAL, width=2)

    ey = ry + 22
    lx, rx2 = rx+13, rx+57
    ew, eh  = 28, 22

    if mood == "happy":
        d.arc([lx, ey, lx+ew, ey+eh], start=200, end=340, fill=accent, width=4)
        d.arc([rx2, ey, rx2+ew, ey+eh], start=200, end=340, fill=accent, width=4)
    elif mood == "excited":
        d.ellipse([lx, ey-2, lx+ew, ey+ew-2], fill=accent)
        d.ellipse([rx2, ey-2, rx2+ew, ey+ew-2], fill=accent)
        d.ellipse([lx+4, ey+2, lx+9, ey+7], fill=SHINE)
        d.ellipse([rx2+4, ey+2, rx2+9, ey+7], fill=SHINE)
    elif mood == "worried":
        d.line([lx, ey+10, lx+ew, ey+4], fill=_R, width=5)
        d.line([rx2, ey+4, rx2+ew, ey+10], fill=_R, width=5)
    elif mood == "focused":
        d.rectangle([lx, ey+7, lx+ew, ey+15], fill=accent)
        d.rectangle([rx2, ey+7, rx2+ew, ey+15], fill=accent)
    else:
        d.rectangle([lx, ey, lx+ew, ey+eh], fill=accent)
        d.rectangle([rx2, ey, rx2+ew, ey+eh], fill=accent)
        d.ellipse([lx+4, ey+3, lx+9, ey+9], fill=SHINE)
        d.ellipse([rx2+4, ey+3, rx2+9, ey+9], fill=SHINE)

    my = ry + 60
    if mood in ("happy", "excited"):
        d.arc([rx+26, my-8, rx+74, my+14], start=0, end=180, fill=accent, width=3)
    elif mood == "worried":
        d.arc([rx+26, my, rx+74, my+18], start=180, end=360, fill=_R, width=3)
    else:
        d.line([rx+30, my+6, rx+70, my+6], fill=METAL, width=3)

    bx, by = rx+12, ry+94
    d.rounded_rectangle([bx, by, bx+76, by+66], radius=10, fill=BODY, outline=METAL, width=2)
    d.rounded_rectangle([bx+18, by+10, bx+58, by+44], radius=6, fill=accent)
    tx = bx + 28
    d.line([tx, by+16, tx+20, by+16], fill=(255,255,255), width=3)
    d.line([tx+10, by+16, tx+10, by+40], fill=(255,255,255), width=3)
    led = _G if mood in ("happy","excited") else _R if mood=="worried" else _A
    d.ellipse([bx+56, by+46, bx+66, by+56], fill=led)

    d.rounded_rectangle([bx-20, by+8, bx-5, by+48], radius=6, fill=METAL)
    d.rounded_rectangle([bx+81, by+8, bx+96, by+48], radius=6, fill=METAL)
    d.ellipse([bx-24, by+42, bx-6, by+60], fill=METAL)
    d.ellipse([bx+82, by+42, bx+100, by+60], fill=METAL)
    d.rounded_rectangle([bx+8,  by+70, bx+30, by+88], radius=6, fill=METAL)
    d.rounded_rectangle([bx+46, by+70, bx+68, by+88], radius=6, fill=METAL)
    d.rounded_rectangle([bx+4,  by+84, bx+34, by+96], radius=4, fill=(55,62,80))
    d.rounded_rectangle([bx+42, by+84, bx+72, by+96], radius=4, fill=(55,62,80))

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

# ── 애니메이션 이펙트 ─────────────────────────────────────────────────────────

def fx_fade_in(img, t, dur=0.30):
    if t >= dur:
        return img
    from PIL import Image
    a = int((1 - t / dur) * 230)
    ov = Image.new("RGBA", img.size, (0, 0, 0, a))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def fx_fade_out(img, t, total, dur=0.25):
    if t < total - dur:
        return img
    from PIL import Image
    a = int(((t - (total - dur)) / dur) * 230)
    ov = Image.new("RGBA", img.size, (0, 0, 0, min(a, 230)))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def fx_speed_lines(img, t, accent):
    """씬 시작 속도선 (만화 액션씬 느낌)."""
    if t >= 0.55:
        return img
    from PIL import Image, ImageDraw
    a  = int((0.55 - t) / 0.55 * 95)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d  = ImageDraw.Draw(ov)
    cx, cy = W // 2, H // 2
    for i in range(22):
        angle = (i / 22) * 2 * math.pi
        x1 = cx + int(math.cos(angle) * 85)
        y1 = cy + int(math.sin(angle) * 55)
        x2 = cx + int(math.cos(angle) * 950)
        y2 = cy + int(math.sin(angle) * 950)
        la = a if i % 3 != 1 else a // 3
        d.line([x1, y1, x2, y2], fill=(*accent, la), width=2)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def fx_scanline(img, t):
    """CRT 스캔라인 + 이동 글로우 라인."""
    from PIL import Image, ImageDraw
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d  = ImageDraw.Draw(ov)
    for y in range(0, H, 4):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, 14), width=1)
    sy = int((t * 110) % H)
    d.line([(0, sy), (W, sy)], fill=(255, 255, 255, 22), width=2)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def fx_pulse_glow(img, t, accent):
    """상단·하단 바 박동 글로우."""
    pulse = (math.sin(t * 4.5) + 1) / 2
    a     = int(18 + pulse * 52)
    from PIL import Image, ImageDraw
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d  = ImageDraw.Draw(ov)
    d.rectangle([0, 0, W, 9], fill=(*accent, a))
    d.rectangle([0, H-9, W, H], fill=(*accent, a // 2))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def fx_subtitle(img, lines, accent, font_path, t_local):
    """자막 슬라이드업 + 텍스트 그림자."""
    from PIL import Image, ImageDraw, ImageFont
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d  = ImageDraw.Draw(ov)

    def fnt(size):
        try:
            return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    slide = min(t_local / 0.22, 1.0)
    dy    = int((1 - slide) * 38)

    active = [l for l in lines if l.strip()][:2]
    y = H - 112 + dy
    for i, line in enumerate(active):
        size = 38 if i == 0 else 26
        col  = (*accent, 255) if i == 0 else (220, 225, 235, 255)
        f    = fnt(size)
        bbox = d.textbbox((0, 0), line, font=f)
        tw   = bbox[2] - bbox[0]
        x    = max(40, (W - tw) // 2)
        d.text((x+2, y+2), line, font=f, fill=(0, 0, 0, 200))
        d.text((x, y),     line, font=f, fill=col)
        y += (bbox[3] - bbox[1]) + 10

    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

# ── 애니메이션 프레임 합성 ────────────────────────────────────────────────────

def make_anime_frame(t, base_arr, accent, subtitle_lines, dur,
                     font_path, scene_idx):
    import numpy as np
    from PIL import Image
    img = Image.fromarray(base_arr).copy()

    img = fx_speed_lines(img, t, accent)
    img = fx_scanline(img, t)
    img = fx_pulse_glow(img, t, accent)

    # 로봇 바운싱 애니메이션
    mood     = SCENE_MOODS[scene_idx - 1]
    robot_dy = int(math.sin(t * 3.5) * 6)
    img = draw_robot_pil(img, W - 218, H - 310 + robot_dy, mood, accent)

    img = fx_fade_in(img, t, 0.28)
    img = fx_fade_out(img, t, dur, 0.22)

    # 자막 (청크 내 경과 시간 기준 슬라이드)
    img = fx_subtitle(img, subtitle_lines, accent, font_path, t)

    return np.array(img)

# ── 씬 처리 ───────────────────────────────────────────────────────────────────

async def process_scene(scene, report_dir, font_path):
    from moviepy import VideoClip, AudioFileClip
    import numpy as np
    from PIL import Image

    idx      = scene["index"]
    lines    = [l for l in scene.get("lines", []) if l.strip()]
    accent   = ACCENT_COLORS[idx - 1]
    title    = scene.get("title", f"씬 {idx}")
    img_path = report_dir / f"scene_{idx:02d}.png"

    # TTS
    tts_text   = clean_for_tts(lines) or title
    audio_path = report_dir / f"scene_{idx:02d}.mp3"
    print(f"   🎙 씬 {idx} [{title[:20]}] 나레이션 생성...")
    await gen_audio(tts_text, audio_path)

    audio = AudioFileClip(str(audio_path))
    dur   = max(audio.duration, MIN_SCENE_SEC)

    # 배경 이미지 로드
    if img_path.exists():
        base_arr = np.array(Image.open(img_path).convert("RGB"))
    else:
        base_arr = np.full((H, W, 3), (14, 17, 23), dtype=np.uint8)

    # 자막 청크
    chunks: list[list[str]] = []
    buf: list[str] = []
    for line in lines:
        if line.strip() == '':
            if buf:
                chunks.append(buf)
                buf = []
        else:
            buf.append(line)
            if len(buf) >= 3:
                chunks.append(buf)
                buf = []
    if buf:
        chunks.append(buf)
    if not chunks:
        chunks = [[title]]

    chunk_dur = dur / len(chunks)

    def make_frame(t):
        ci      = min(int(t / chunk_dur), len(chunks) - 1)
        t_local = t - ci * chunk_dur
        return make_anime_frame(t_local, base_arr, accent,
                                chunks[ci], chunk_dur, font_path, idx)

    video = VideoClip(make_frame, duration=dur).with_fps(FPS)
    video = video.with_audio(audio)

    print(f"   ✅ 씬 {idx} 완료 ({dur:.1f}초, 청크 {len(chunks)}개)")
    return video

# ── 영상 합성 ─────────────────────────────────────────────────────────────────

async def build_video_async(report_dir):
    from moviepy import concatenate_videoclips

    font_path = find_font()
    if not font_path:
        print("⚠ 한글 폰트 없음", file=sys.stderr)

    script = json.loads((report_dir / "script.json").read_text(encoding="utf-8"))
    scenes = script.get("scenes", [])
    title  = script.get("title", "TSLA 주간 분석")

    print(f"📽 {len(scenes)}개 씬 처리 (애니메이션 모드, 음성: {VOICE})")
    print(f"   제목: {title}")

    clips = []
    for scene in scenes:
        clip = await process_scene(scene, report_dir, font_path)
        clips.append(clip)

    print("\n🎬 최종 영상 합성 중...")
    final = concatenate_videoclips(clips, method="compose") if len(clips) > 1 else clips[0]
    final = final.with_fps(FPS)

    out_path = report_dir / "video.mp4"
    final.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=2,
        logger=None,
    )

    dur = final.duration
    print(f"\n✅ 영상 생성 완료!")
    print(f"   📁 {out_path}")
    print(f"   ⏱ 총 {dur:.1f}초 ({dur/60:.1f}분)")
    return out_path

# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    report_dir = find_latest_report()
    if not report_dir:
        print("⚠ script.json 없음 — weekly_video_prep.py 먼저 실행하세요", file=sys.stderr)
        sys.exit(1)

    print(f"📁 보고서: {report_dir.name}")
    asyncio.run(build_video_async(report_dir))


if __name__ == "__main__":
    main()
