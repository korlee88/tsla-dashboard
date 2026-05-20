#!/usr/bin/env python3
"""TSLA 영상용 프레임 템플릿 이미지를 Nano Banana로 1회 생성.

용도:
  각 씬에 공통으로 깔리는 Tesla-themed 외곽 프레임/보더 디자인.
  중앙 영역은 투명하게 마스킹되어, 기존 씬 콘텐츠(헤더·사진·카드)가
  그대로 보이고 가장자리만 통일된 브랜드 룩으로 장식된다.

실행:
  python scripts/generate_frame.py                  # 새로 생성 (덮어쓰기)
  python scripts/generate_frame.py --keep-existing  # 이미 있으면 유지

환경변수: GEMINI_API_KEY 필수.
출력: data/frame-template.png (RGBA, 1080×1920)

※ 1회 생성 후 git 커밋해서 재사용. 새 디자인이 필요할 때만 다시 실행.
"""

import os
import sys
from pathlib import Path

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

OUT_PATH    = Path("data/frame-template.png")
W, H        = 1080, 1920
BORDER_PX   = 90    # 가장자리 보더 두께 (px)
CORNER_R    = 60    # 중앙 투명 영역의 모서리 라운드 반경

FRAME_PROMPT = """
A futuristic Tesla-inspired decorative frame border design, vertical 9:16, ultra-high resolution.
The image must show ONLY the outer border/frame decoration around the edges.
The CENTER 80% area should be a flat solid dark navy color (#0a0e1a) — completely empty, no content.

Border decoration features (only along the edges, ~90px wide):
- Top edge: glowing cyan neon line with subtle electric circuit traces, hint of a Tesla T-shape silhouette
- Bottom edge: futuristic dashboard accent bar with magenta-cyan gradient glow
- Left and right edges: thin vertical neon glow lines, subtle hexagonal tech pattern
- Four corners: small triangular tech accents with glowing edges
- Overall style: cyberpunk, electric vehicle aesthetic, neon cyan + magenta + electric purple highlights
- Background of border area: deep navy/black with subtle starfield or grid texture

Strict requirements:
- The inner 900×1700 area MUST be uniform solid dark color (no patterns, no objects, no light)
- No text, no letters, no numbers, no watermark, no logo
- High contrast between glowing border and dark empty center
"""

_NANO_BANANA_MODELS = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
]


def generate_with_nano_banana() -> bytes | None:
    if not GEMINI_API_KEY:
        print("⚠ GEMINI_API_KEY 환경변수 필요", file=sys.stderr)
        return None
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
    for model_id in _NANO_BANANA_MODELS:
        try:
            print(f"🎨 {model_id}로 프레임 생성 중...")
            response = client.models.generate_content(
                model=model_id,
                contents=FRAME_PROMPT,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="9:16"),
                ),
            )
            for part in response.parts:
                if part.inline_data:
                    return part.inline_data.data
        except Exception as e:
            print(f"   ⚠ {model_id} 실패: {e}", file=sys.stderr)
    return None


def punch_center_transparent(img_bytes: bytes) -> "Image.Image":
    """생성된 이미지의 중앙 영역을 강제로 투명화 (라운드 사각형 마스크)."""
    from io import BytesIO
    from PIL import Image, ImageDraw

    base = Image.open(BytesIO(img_bytes)).convert("RGBA")
    if base.size != (W, H):
        base = base.resize((W, H), Image.LANCZOS)

    # 알파 마스크 생성: 가장자리 BORDER_PX만 불투명, 중앙은 투명
    mask = Image.new("L", (W, H), 0)        # 0 = 투명
    md = ImageDraw.Draw(mask)
    md.rectangle([0, 0, W, H], fill=255)   # 전체 불투명
    md.rounded_rectangle(
        [BORDER_PX, BORDER_PX, W - BORDER_PX, H - BORDER_PX],
        radius=CORNER_R, fill=0,
    )                                       # 중앙 라운드 사각형 = 투명

    base.putalpha(mask)
    return base


def main():
    keep_existing = "--keep-existing" in sys.argv
    if keep_existing and OUT_PATH.exists():
        print(f"✅ 기존 프레임 유지: {OUT_PATH}")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    raw = generate_with_nano_banana()
    if not raw:
        print("❌ Nano Banana 이미지 생성 실패", file=sys.stderr)
        sys.exit(1)

    framed = punch_center_transparent(raw)
    framed.save(OUT_PATH, "PNG")
    print(f"✅ 프레임 저장 완료: {OUT_PATH} (1080×1920, RGBA)")
    print(f"   가장자리 보더 {BORDER_PX}px, 중앙 라운드 모서리 {CORNER_R}px 투명")
    print(f"   ※ git 커밋 후 모든 영상에 자동 적용됩니다.")


if __name__ == "__main__":
    main()
