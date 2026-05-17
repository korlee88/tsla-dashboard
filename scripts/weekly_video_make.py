"""
주간 나레이션 영상 생성 (moviepy 2.x + 애니메이션)
weekly_video_prep.py 실행 후 사용.
script.json + scene_XX.png → edge-tts MP3 → 애니메이션 MP4
출력: 1080×1920 (YouTube Shorts 세로 포맷)

종목 설정: config/ticker.json
필요 패키지: pip install -r requirements.txt
"""

import json, sys, asyncio, math
from pathlib import Path

ROOT_DIR      = Path(__file__).parent.parent
TICKER_CONFIG = json.loads((ROOT_DIR / "config" / "ticker.json").read_text(encoding="utf-8"))
TICKER        = TICKER_CONFIG["ticker"]

REPORT_BASE   = ROOT_DIR / "data" / "weekly-report"
VOICE         = "ko-KR-SunHiNeural"    # 한국 여성 TTS
RATE          = "+15%"                  # 명확한 발음을 위해 속도 낮춤
PITCH         = "+0Hz"                  # 피치 변경 없음 (자연스러운 목소리)
FPS           = 24
W, H          = 1080, 1920
PHOTO_Y       = 500                     # 헤더 아래 사진 시작 Y (prep.py의 HEADER_H와 동일)
PHOTO_H       = 500                     # 사진 영역 높이 (prep.py의 PHOTO_H와 동일)
MIN_SCENE_SEC = 5.0

ACCENT_COLORS = [
    (167, 139, 250),  # scene1 purple  - 브리핑
    (34,  197,  94),  # scene2 green   - 호재 뉴스
    (239,  68,  68),  # scene3 red     - 리스크 뉴스
    (245, 158,  11),  # scene4 amber   - 시장 동향
]
SCENE_MOODS = ["excited", "happy", "worried", "focused"]

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
        if '|' in line:
            line = line.split('|')[0].strip()
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


def fx_ken_burns(img, t: float, dur: float, scene_idx: int):
    """배경 이미지 느린 줌 + 패닝 (Ken Burns 효과). 씬마다 방향이 다름."""
    from PIL import Image
    progress = t / max(dur, 0.001)

    # 씬별 줌/패닝 패턴 — 1.00~1.07 범위 (7% 줌, 자연스러운 움직임)
    CONFIGS = [
        # (zoom_start, zoom_end, pan_x_start, pan_x_end, pan_y_start, pan_y_end)
        (1.00, 1.07,  0.00,  0.03,  0.00,  0.02),  # scene 0: 줌인 + 우하
        (1.07, 1.00,  0.03,  0.00,  0.02,  0.00),  # scene 1: 줌아웃 + 좌상
        (1.00, 1.07,  0.00, -0.03,  0.00,  0.02),  # scene 2: 줌인 + 좌하
        (1.07, 1.00, -0.03,  0.00,  0.02,  0.00),  # scene 3: 줌아웃 + 우상
    ]
    zoom_s, zoom_e, px_s, px_e, py_s, py_e = CONFIGS[scene_idx % len(CONFIGS)]

    zoom  = zoom_s + (zoom_e - zoom_s) * progress
    pan_x = px_s  + (px_e  - px_s)   * progress
    pan_y = py_s  + (py_e  - py_s)   * progress

    ow, oh = img.size  # 1080, 1920
    nw = max(int(ow * zoom), ow)
    nh = max(int(oh * zoom), oh)
    zoomed = img.resize((nw, nh), Image.LANCZOS)

    # 중앙 기준으로 패닝 오프셋 적용 후 경계 클램핑
    cx = (nw - ow) // 2 + int(pan_x * ow)
    cy = (nh - oh) // 2 + int(pan_y * oh)
    cx = max(0, min(cx, nw - ow))
    cy = max(0, min(cy, nh - oh))

    return zoomed.crop((cx, cy, cx + ow, cy + oh))

# ── 애니메이션 프레임 합성 ────────────────────────────────────────────────────

def make_anime_frame(t, base_arr, accent, dur, scene_idx):
    import numpy as np
    from PIL import Image
    img = Image.fromarray(base_arr).copy()

    # Ken Burns: 전체 프레임이 아닌 사진 스트립(y=500~1000)에만 적용
    photo = img.crop((0, PHOTO_Y, W, PHOTO_Y + PHOTO_H))
    photo = fx_ken_burns(photo, t, dur, scene_idx - 1)
    img.paste(photo, (0, PHOTO_Y))

    img = fx_speed_lines(img, t, accent)
    img = fx_scanline(img, t)
    img = fx_pulse_glow(img, t, accent)

    mood     = SCENE_MOODS[scene_idx - 1]
    robot_dy = int(math.sin(t * 3.5) * 4)
    img = draw_robot_pil(img, W - 130, 40 + robot_dy, mood, accent)

    img = fx_fade_in(img, t, 0.28)
    img = fx_fade_out(img, t, dur, 0.22)

    # 90% 축소 — 핸드폰 화면 여백 확보
    cw = int(W * 0.90)
    ch = int(H * 0.90)
    scaled = img.resize((cw, ch), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(scaled, ((W - cw) // 2, (H - ch) // 2))

    return np.array(canvas)

# ── 씬 처리 ───────────────────────────────────────────────────────────────────

async def process_scene(scene, report_dir):
    from moviepy import VideoClip, AudioFileClip
    import numpy as np
    from PIL import Image

    idx      = scene["index"]
    lines    = [l for l in scene.get("lines", []) if l.strip()]
    accent   = ACCENT_COLORS[idx - 1]
    title    = scene.get("title", f"씬 {idx}")
    img_path = report_dir / f"scene_{idx:02d}.png"

    tts_lines  = lines[:2]                              # 상위 2줄만 나레이션 (1분 이내)
    tts_text   = clean_for_tts(tts_lines) or title
    audio_path = report_dir / f"scene_{idx:02d}.mp3"
    print(f"   🎙 씬 {idx} [{title[:20]}] 나레이션 생성...")
    await gen_audio(tts_text, audio_path)

    audio = AudioFileClip(str(audio_path))
    dur   = max(audio.duration, MIN_SCENE_SEC)

    if img_path.exists():
        base_arr = np.array(Image.open(img_path).convert("RGB"))
    else:
        base_arr = np.full((H, W, 3), (14, 17, 23), dtype=np.uint8)

    def make_frame(t):
        return make_anime_frame(t, base_arr, accent, dur, idx)

    video = VideoClip(make_frame, duration=dur).with_fps(FPS)
    video = video.with_audio(audio)

    print(f"   ✅ 씬 {idx} 완료 ({dur:.1f}초)")
    return video

# ── 영상 합성 ─────────────────────────────────────────────────────────────────

async def build_video_async(report_dir):
    from moviepy import concatenate_videoclips

    script = json.loads((report_dir / "script.json").read_text(encoding="utf-8"))
    scenes = script.get("scenes", [])
    title  = script.get("title", f"{TICKER} 주간 분석")

    print(f"📽 {len(scenes)}개 씬 처리 (애니메이션 모드, 음성: {VOICE})")
    print(f"   제목: {title}")

    clips = []
    for scene in scenes:
        clip = await process_scene(scene, report_dir)
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
    final.close()
    for c in clips:
        c.close()

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
