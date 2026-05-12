"""
TSLA 주간 나레이션 영상 생성
weekly_video_prep.py 실행 후 사용.
script.json + scene_XX.png → edge-tts MP3 → moviepy MP4

필요 패키지:
  pip install edge-tts moviepy pillow numpy
  (ffmpeg은 시스템에 설치 필요 — GitHub Actions ubuntu-latest에 기본 포함)
"""

import os, json, sys, asyncio
from pathlib import Path

REPORT_BASE   = Path(__file__).parent.parent / "data" / "weekly-report"
VOICE         = "ko-KR-InJoonNeural"   # 남성 뉴스 톤 (변경 가능: ko-KR-SunHiNeural)
FPS           = 24
W, H          = 1280, 720
MIN_SCENE_SEC = 8.0

ACCENT_COLORS = [
    (167, 139, 250),  # scene1 purple
    (34,  197,  94),  # scene2 green
    (239,  68,  68),  # scene3 red
    (245, 158,  11),  # scene4 amber
    (6,  182, 212),   # scene5 cyan
]

# ── 유틸 ──────────────────────────────────────────────────────────────────────

def find_latest_report() -> Path | None:
    if not REPORT_BASE.exists():
        return None
    dirs = sorted(
        [d for d in REPORT_BASE.iterdir() if d.is_dir() and (d / "script.json").exists()],
        reverse=True,
    )
    return dirs[0] if dirs else None


def find_font() -> str | None:
    for p in [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(p):
            return p
    return None


def clean_for_tts(lines: list) -> str:
    """자막 lines → TTS 읽기용 텍스트 정제"""
    table = {
        '【': '', '】': '',
        '①': '첫째,', '②': '둘째,', '③': '셋째,', '④': '넷째,', '⑤': '다섯째,',
        '$': '달러 ', '%': '퍼센트,', '+': '플러스 ',
        '─': '', '▲': '', '▼': '', '🟢': '', '🔴': '', '📊': '', '📈': '',
        '✓': '', '⚡': '', '○': '',
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

async def gen_audio(text: str, path: Path):
    import edge_tts
    comm = edge_tts.Communicate(text, VOICE)
    await comm.save(str(path))

# ── 프레임 생성 ───────────────────────────────────────────────────────────────

def make_subtitle_frame(img_path: Path, subtitle_lines: list,
                        accent: tuple, font_path: str | None):
    """씬 배경 이미지 + 하단 자막 오버레이 → numpy 배열"""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    img = Image.open(img_path).convert("RGB")

    # 하단 자막 반투명 배경 (그라데이션 효과)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y_offset in range(220):
        alpha = int(y_offset / 220 * 190)
        ImageDraw.Draw(ov).line(
            [(0, H - 220 + y_offset), (W, H - 220 + y_offset)],
            fill=(0, 0, 0, alpha)
        )
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(img)

    def fnt(size):
        try:
            return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    # 액센트 구분선
    draw.rectangle([60, H - 205, W - 60, H - 202], fill=accent)

    y = H - 195
    for i, line in enumerate(subtitle_lines[:4]):
        if not line.strip():
            y += 6
            continue
        is_heading = (i == 0 and (line.startswith('①') or line.startswith('②') or
                                   line.startswith('③') or line.startswith('【') or
                                   line.startswith('▲') or len(subtitle_lines) == 1))
        size = 32 if (i == 0 or is_heading) else 25
        f    = fnt(size)
        col  = accent if (i == 0 or is_heading) else (210, 218, 228)

        bbox = draw.textbbox((0, 0), line, font=f)
        tw   = bbox[2] - bbox[0]
        x    = max(40, (W - tw) // 2)
        draw.text((x, y), line, font=f, fill=col)
        y += (bbox[3] - bbox[1]) + 10

    return np.array(img)


def make_fallback_image(accent: tuple, font_path: str | None, title: str) -> "np.ndarray":
    """씬 이미지가 없을 때 단색 배경 생성"""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    img  = Image.new("RGB", (W, H), (14, 17, 23))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 7], fill=accent)
    draw.rectangle([36, 36, W - 36, H - 36], fill=(28, 31, 38))
    try:
        f = ImageFont.truetype(font_path, 44) if font_path else ImageFont.load_default()
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((W - (bbox[2]-bbox[0])) // 2, H // 2 - 30), title, font=f, fill=(255, 255, 255))
    except Exception:
        pass
    return np.array(img)

# ── 씬 클립 생성 ──────────────────────────────────────────────────────────────

async def process_scene(scene: dict, report_dir: Path, font_path: str | None):
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
    import numpy as np

    idx     = scene["index"]
    lines   = [l for l in scene.get("lines", []) if l.strip()]
    accent  = ACCENT_COLORS[idx - 1]
    title   = scene.get("title", f"씬 {idx}")
    img_path = report_dir / f"scene_{idx:02d}.png"

    # 이미지 없으면 fallback
    base_frame = (make_subtitle_frame(img_path, [], accent, font_path)
                  if img_path.exists()
                  else make_fallback_image(accent, font_path, title))

    # ── TTS 생성 ──────────────────────────────────────────────────────────────
    tts_text   = clean_for_tts(lines) or title
    audio_path = report_dir / f"scene_{idx:02d}.mp3"
    print(f"   🎙 씬 {idx} [{title}] 나레이션 생성...")
    await gen_audio(tts_text, audio_path)

    audio = AudioFileClip(str(audio_path))
    dur   = max(audio.duration + 0.5, MIN_SCENE_SEC)

    # ── 자막 청크 분할 ────────────────────────────────────────────────────────
    # 빈 줄 기준으로 구분, 없으면 3줄씩
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
    sub_clips = []
    for chunk in chunks:
        frame = make_subtitle_frame(img_path if img_path.exists() else None,
                                    chunk, accent, font_path) if img_path.exists() \
                else make_subtitle_frame_from_array(base_frame, chunk, accent, font_path)
        sub_clips.append(ImageClip(frame, duration=chunk_dur))

    video = concatenate_videoclips(sub_clips, method="compose")
    video = video.set_audio(audio.set_duration(dur))
    print(f"   ✅ 씬 {idx} 완료 ({dur:.1f}초, 자막 {len(chunks)}구간)")
    return video


def make_subtitle_frame_from_array(base: "np.ndarray", subtitle_lines: list,
                                    accent: tuple, font_path: str | None):
    """numpy 배열 기반 프레임에 자막 추가"""
    from PIL import Image
    return make_subtitle_frame_pil(Image.fromarray(base), subtitle_lines, accent, font_path)


def make_subtitle_frame_pil(img: "Image.Image", subtitle_lines: list,
                              accent: tuple, font_path: str | None):
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y_offset in range(220):
        alpha = int(y_offset / 220 * 180)
        ImageDraw.Draw(ov).line(
            [(0, H - 220 + y_offset), (W, H - 220 + y_offset)],
            fill=(0, 0, 0, alpha)
        )
    img2 = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(img2)
    draw.rectangle([60, H - 205, W - 60, H - 202], fill=accent)
    y = H - 195
    for i, line in enumerate(subtitle_lines[:4]):
        if not line.strip():
            y += 6
            continue
        size = 32 if i == 0 else 25
        try:
            f = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        except Exception:
            f = ImageFont.load_default()
        col  = accent if i == 0 else (210, 218, 228)
        bbox = draw.textbbox((0, 0), line, font=f)
        draw.text((max(40, (W - (bbox[2]-bbox[0])) // 2), y), line, font=f, fill=col)
        y += (bbox[3] - bbox[1]) + 10
    return np.array(img2)

# ── 메인 ──────────────────────────────────────────────────────────────────────

async def build_video_async(report_dir: Path):
    font_path = find_font()
    if not font_path:
        print("⚠ 한글 폰트 없음 — 자막이 깨질 수 있습니다", file=sys.stderr)

    script = json.loads((report_dir / "script.json").read_text(encoding="utf-8"))
    scenes = script.get("scenes", [])
    title  = script.get("title", "TSLA 주간 분석")

    print(f"📽 {len(scenes)}개 씬 처리 시작 (음성: {VOICE})")
    print(f"   제목: {title}")

    clips = []
    for scene in scenes:
        clip = await process_scene(scene, report_dir, font_path)
        clips.append(clip)

    print("\n🎬 최종 영상 합성 중...")
    from moviepy.editor import concatenate_videoclips
    final = concatenate_videoclips(clips, method="compose").set_fps(FPS)

    out_path = report_dir / "video.mp4"
    final.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(report_dir / "temp_audio.m4a"),
        remove_temp=True,
        logger=None,
        preset="ultrafast",
        threads=2,
    )

    print(f"\n✅ 영상 생성 완료!")
    print(f"   📁 {out_path}")
    print(f"   ⏱ 총 {final.duration:.1f}초 ({final.duration/60:.1f}분)")
    return out_path


def main():
    report_dir = find_latest_report()
    if not report_dir:
        print("⚠ script.json 없음 — weekly_video_prep.py 먼저 실행하세요", file=sys.stderr)
        sys.exit(1)

    print(f"📁 보고서: {report_dir.name}")
    asyncio.run(build_video_async(report_dir))


if __name__ == "__main__":
    main()
