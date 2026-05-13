# TSLA Dashboard — Claude Code 작업 기록

## 프로젝트 개요

GitHub Pages 기반 Tesla(TSLA) 주간 분석 대시보드.
매주 월요일 KST 09:00 GitHub Actions가 자동으로 영상 자료를 생성한다.

- **저장소**: `korlee88/tsla-dashboard`
- **기본 브랜치**: `master` (보호됨)
- **개발 브랜치**: `claude/fix-news-collection-errors-48epy`

---

## 아키텍처

```
tsla-dashboard/
├── .github/workflows/
│   └── weekly-video.yml       # 월요일 자동 실행 + workflow_dispatch
├── scripts/
│   ├── weekly_video_prep.py   # STEP 1: 대본 생성 + 씬 이미지
│   └── weekly_video_make.py   # STEP 2: TTS + 애니메이션 영상 합성
├── data/
│   ├── auto-sessions.json     # 최근 7일 TSLA 세션 데이터 (원본)
│   └── weekly-report/
│       └── YYYY-MM-DD/
│           ├── script.json    # 생성된 대본 (커밋됨)
│           ├── scene_01.png   # 씬 이미지 (커밋됨)
│           ├── scene_02.png
│           ├── scene_03.png
│           ├── scene_04.png
│           ├── scene_05.png
│           ├── *.mp3          # TTS 오디오 (커밋 제외)
│           └── video.mp4      # 최종 영상 (커밋 제외, artifact 업로드)
└── CLAUDE.md                  # 이 파일
```

---

## GitHub Secrets 필수 설정

| Secret | 용도 |
|--------|------|
| `ANTHROPIC_API_KEY` | Claude Opus 4 대본 생성 (1순위) |
| `GEMINI_API_KEY` | Gemini 1.5 Flash 폴백 (Opus 실패 시) |

> **보안 주의**: API 키는 절대 코드나 채팅에 공유하지 말 것.
> GitHub 저장소 Settings → Secrets and variables → Actions에서 직접 입력.

---

## 파이프라인 상세

### STEP 1: `weekly_video_prep.py`

**역할**: 대본 + 씬 이미지 5장 생성

**대본 생성 우선순위**:
1. Claude Opus 4 (`claude-opus-4-7`) — `ANTHROPIC_API_KEY` 필요
2. Gemini 1.5 Flash — `GEMINI_API_KEY` 필요
3. 둘 다 없으면 RuntimeError

**Gemini SDK**: `google-genai` (신규 SDK, NOT `google-generativeai`)
```python
from google import genai
client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
```

**씬 구성**:
| 씬 | 주제 | Wikipedia 배경 | 색상 |
|----|------|---------------|------|
| 1 | 이번 주 TSLA 요약 | Tesla, Inc. | Purple |
| 2 | 호재/뉴스 | Tesla Cybertruck | Green |
| 3 | 리스크/우려 | Elon Musk | Red |
| 4 | 기술/생산 전망 | Gigafactory Nevada | Amber |
| 5 | 결론/매매 시그널 | Tesla Model S | Cyan |

**이미지 레이어**:
- Wikipedia 무료 사진 (API 키 불필요) → 배경
- 195/255 어두운 오버레이
- 씬별 전용 UI (게이지/뉴스카드/예측박스/시그널)

### STEP 2: `weekly_video_make.py`

**역할**: TTS 오디오 생성 + 애니메이션 영상 합성

**TTS 설정**:
```python
VOICE = "ko-KR-HyunsuNeural"  # 캐주얼 남성
RATE  = "+50%"                 # 속도 (2배에 가깝게)
PITCH = "+12Hz"                # 톤업 (밝고 에너지 넘침)
```

**애니메이션 시스템** (moviepy 2.x `VideoClip`):
- `fx_speed_lines()` — 배경 속도감 효과
- `fx_scanline()` — CRT 스캔라인
- `fx_pulse_glow()` — 테두리 펄스 발광
- `fx_subtitle()` — 자막 슬라이드인
- `draw_robot_pil()` — 씬별 표정 변화하는 로봇 마스코트

**로봇 마스코트 표정**:
- `excited` → 웃는 눈, 오픈 마우스
- `happy` → 일반 웃음
- `worried` → 찡그린 눈
- `focused` → 눈 가늘게

**출력**: 1280×720 @ 24fps, ~1분

---

## 의존성

```bash
pip install anthropic google-genai Pillow edge-tts moviepy numpy
```

**시스템 패키지** (GitHub Actions ubuntu-latest):
```bash
sudo apt-get install -y fonts-nanum
```

### moviepy 2.x 주의사항

2.x에서 1.x API 완전 변경됨:

| 구 API (1.x) | 신 API (2.x) |
|-------------|-------------|
| `from moviepy.editor import` | `from moviepy import` |
| `clip.set_audio(a)` | `clip.with_audio(a)` |
| `clip.set_fps(f)` | `clip.with_fps(f)` |
| `clip.set_duration(d)` | `clip.with_duration(d)` |
| `write_videofile(temp_audiofile=...)` | 해당 파라미터 없음 |
| `ImageClip(arr)` (정적) | `VideoClip(make_frame, duration)` (애니메이션) |

**audio.with_duration() 주의**: `dur > audio.duration`이면 IOError 발생.
`video.with_audio(audio)` 만 사용하고 duration 강제 연장 금지.

---

## GitHub Actions 워크플로

**파일**: `.github/workflows/weekly-video.yml`

**트리거**:
- 자동: 매주 월요일 KST 09:00 (UTC 00:00, `cron: '0 0 * * 1'`)
- 수동: GitHub Actions 탭 → `workflow_dispatch`

**주요 단계**:
1. Python 3.11 설정
2. 한글 폰트 설치 (`fonts-nanum`)
3. 의존성 설치
4. `weekly_video_prep.py` (대본 + 이미지)
5. `weekly_video_make.py` (TTS + 영상)
6. 대본/이미지 커밋 (MP3/MP4 제외)
7. video.mp4 → artifact 업로드 (30일 보관)

---

## 알려진 이슈 및 해결책

### Gemini 모델 가용성
- `gemini-2.0-flash`: 신규 사용자 사용 불가 (404)
- `gemini-2.0-flash-lite`: 사용 불가 (404)
- `gemini-1.5-flash`: **현재 정상 동작** ✅

### Anthropic API 크레딧
Opus API 호출 실패 시 (`Your credit balance is too low`) 자동으로 Gemini로 폴백.
대본 생성은 `try/except` 구조로 보호됨.

### 대용량 파일
MP3/MP4는 git에 커밋하지 않음 (`git restore --staged` 로 unstage).
영상은 GitHub Actions artifact로 30일 보관 후 자동 삭제.

---

## 대본 스타일 가이드

대본은 유재석 스타일 MC 어투:
- 한 줄 20자 이내
- 씬당 4줄
- 감탄사 활용: "와!", "대박!", "여러분!"
- 밝고 에너지 넘치는 톤
- 핵심 수치는 반드시 포함

---

## 개발 히스토리 요약

| 날짜 | 변경 내용 |
|------|---------|
| 2026-05 | moviepy 2.x 호환성 수정 (`from moviepy import`, `with_*` API) |
| 2026-05 | Gemini 폴백 추가 (Anthropic 크레딧 부족 대응) |
| 2026-05 | `google-genai` SDK로 전환 (v1beta → v1 API) |
| 2026-05 | 뉴스 스타일 UI + 2배 빠른 나레이션 + 1분 영상 목표 |
| 2026-05 | Wikipedia 테슬라 공식 사진 배경 적용 |
| 2026-05 | 로봇 마스코트 캐릭터 추가 (씬별 표정 변화) |
| 2026-05 | 전체 애니메이션화 (`VideoClip` 기반 퍼-프레임 렌더링) |
| 2026-05 | 유재석 스타일 MC 목소리 설정 (`+50%` 속도, `+12Hz` 피치) |
| 2026-05 | `gemini-2.0-flash-lite` → `gemini-1.5-flash` 모델 변경 |
