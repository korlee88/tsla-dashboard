# TSLA Dashboard — Claude Code 작업 기록

## 작업 원칙 (중요)

**Claude가 직접 할 수 있는 작업은 모두 자율적으로 진행한다.**
- PR 생성 → 머지까지 직접 수행
- 커밋 & 푸시 직접 수행
- 수동 개입이 반드시 필요한 경우(브라우저 로그인, 시크릿 입력 등)에만 사용자에게 알린다

## 프로젝트 개요

GitHub Pages 기반 Tesla(TSLA) 주간 분석 대시보드.
매일 KST 09:00 GitHub Actions가 자동으로 영상 자료를 생성한다.

- **저장소**: `korlee88/tsla-dashboard`
- **기본 브랜치**: `master` (보호됨)
- **개발 브랜치**: `claude/fix-news-collection-errors-48epy`

---

## 다른 종목으로 포크하기

이 저장소는 멀티 종목 지원을 위해 설정 분리되어 있다. 다른 종목용 대시보드를 만들려면:

### 1. 저장소 복제
```bash
gh repo create korlee88/nvda-dashboard --template korlee88/tsla-dashboard
git clone https://github.com/korlee88/nvda-dashboard
```

### 2. `config/ticker.json` 수정

| 필드 | TSLA 예시 | NVDA 예시 |
|------|---------|----------|
| `ticker` | `"TSLA"` | `"NVDA"` |
| `company_en` | `"Tesla"` | `"Nvidia"` |
| `company_ko` | `"테슬라"` | `"엔비디아"` |
| `industry_ko` | `"전기차·미래기술"` | `"AI 반도체"` |
| `brand_label` | `"TSLA WEEKLY"` | `"NVDA WEEKLY"` |
| `repo` | `"korlee88/tsla-dashboard"` | `"korlee88/nvda-dashboard"` |
| `beta_coefficient` | `2.5` | `1.7` |
| `scene_wiki_articles` | Tesla 관련 4씬 | Nvidia/H100/Jensen Huang/HBM 등 |
| `scene_static_bg_files` | Tesla 배경 | Nvidia 배경 (새로 준비 필요) |
| `youtube_search_queries` | `["Tesla TSLA stock", ...]` | `["Nvidia NVDA stock", ...]` |
| `video_tags` | `["테슬라", "TSLA", ...]` | `["엔비디아", "NVDA", ...]` |

### 3. 씬 배경 이미지 교체
`data/scene-backgrounds/bg_scene_02.jpg`, `bg_scene_03.jpg`, `bg_scene_04.jpg`를 새 종목에 맞게 교체.

### 4. GitHub Secrets 재설정
새 저장소에 `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `YOUTUBE_API_KEY` 등 동일하게 설정.

### Phase 2 작업 예정 (현재 미적용)
- JS 스크립트 (`auto-analysis.js`, `backtest-run.js`, `calendar-update.js`)도 설정 사용으로 변경
- `index.html` 대시보드 — 종목 라벨, fetch URL 등 설정 사용
- 데이터 모델 키 `latestTslaPrice` → `latestPrice` (호환성 마이그레이션 필요)
- 한국 주식 지원 시 Yahoo Finance → KRX 데이터 소스 추상화

---

## 아키텍처

```
tsla-dashboard/
├── .github/workflows/
│   ├── weekly-video.yml       # 매일 자동 실행 + workflow_dispatch
│   ├── auto-analysis.yml      # 하루 4회 자동 분석
│   ├── backtest-run.yml       # 백테스트 (매일 자동 + 수동)
│   └── calendar-update.yml    # 매주 일정 갱신
├── config/
│   └── ticker.json            # 종목 설정 (TSLA/NVDA/AAPL 등 분기점)
├── scripts/
│   ├── weekly_video_prep.py   # STEP 1: 대본 + 씬 이미지 4장
│   ├── weekly_video_make.py   # STEP 2: TTS + 애니메이션 영상
│   ├── gws_publish.py         # STEP 5: YouTube/Sheets/Gmail 게시
│   ├── setup_gws_auth.py      # OAuth2 토큰 생성 헬퍼 (로컬 1회)
│   └── youtube_sentiment.py   # YouTube 검색·관심도 수집
├── data/
│   ├── auto-sessions.json     # 최근 7일 세션 데이터 (원본)
│   ├── backtest-results-2025.json  # 2025 백테스트 (완료)
│   ├── backtest-results-2026.json  # 2026 백테스트 (매일 증분 업데이트)
│   ├── scene-backgrounds/     # 씬 2~4 고정 배경 이미지 (jpg)
│   └── weekly-report/
│       └── YYYY-MM-DD/
│           ├── script.json    # 생성된 대본 + image_prompts (커밋됨)
│           ├── script.txt     # 대본 원문
│           ├── image_prompts.txt  # Imagen 프롬프트 (Imagen 복붙용)
│           ├── meta.json      # 요약 데이터 (gws_publish가 사용)
│           ├── scene_01.png   # 씬 이미지 4장 (커밋됨)
│           ├── scene_02.png
│           ├── scene_03.png
│           ├── scene_04.png
│           ├── *.mp3          # TTS 오디오 (커밋 제외)
│           └── video.mp4      # 최종 영상 (커밋 제외, artifact 업로드)
├── requirements.txt           # Python 의존성 (pip 캐시용)
├── index.html                 # 대시보드 (단일 파일 React)
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

## GWS 통합 시크릿 (선택)

각 통합은 독립적으로 동작. 해당 시크릿이 없으면 해당 단계만 건너뜀. 기존 파이프라인에 영향 없음.

| Secret | 용도 | 담당 기능 |
|--------|------|---------|
| `GWS_YOUTUBE_TOKEN` | YouTube OAuth2 token.json 내용 | YouTube 자동 업로드 |
| `GWS_SA_CREDENTIALS` | Google Service Account JSON 전체 | Sheets 기록 |
| `GOOGLE_SHEET_ID` | Sheets 문서 ID (URL `/d/` 뒤 문자열) | Sheets 기록 |
| `GMAIL_USER` | 발신 Gmail 주소 | Gmail 다이제스트 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (16자리) | Gmail 다이제스트 |
| `GMAIL_TO` | 수신자 이메일 | Gmail 다이제스트 |

### GWS 최초 설정 순서

**YouTube 업로드 설정** (`GWS_YOUTUBE_TOKEN`):
1. [console.cloud.google.com](https://console.cloud.google.com) → 프로젝트 생성
2. API 라이브러리 → **YouTube Data API v3** 활성화
3. OAuth 동의 화면 → 외부 → 테스트 사용자에 본인 계정 추가
4. 사용자 인증 정보 → OAuth 2.0 클라이언트 ID → **데스크톱 앱** → `credentials.json` 다운로드
5. 로컬에서 실행:
   ```bash
   pip install google-auth-oauthlib
   python scripts/setup_gws_auth.py credentials.json
   ```
6. 생성된 `token.json` 내용 → GitHub Secret **`GWS_YOUTUBE_TOKEN`** 등록

**Sheets 기록 설정** (`GWS_SA_CREDENTIALS`, `GOOGLE_SHEET_ID`):
1. 같은 Google Cloud 프로젝트 → **Google Sheets API** 활성화
2. 사용자 인증 정보 → 서비스 계정 → 새 서비스 계정 생성 → JSON 키 다운로드
3. JSON 파일 전체 내용 → GitHub Secret **`GWS_SA_CREDENTIALS`** 등록
4. Google Sheets 새 문서 생성 → 서비스 계정 이메일로 **편집자 공유**
5. Sheets URL의 `/d/` 뒤 ID → GitHub Secret **`GOOGLE_SHEET_ID`** 등록

**Gmail 다이제스트 설정** (`GMAIL_USER`, `GMAIL_APP_PASSWORD`, `GMAIL_TO`):
1. Gmail → Google 계정 → 보안 → **2단계 인증** 활성화
2. 앱 비밀번호 생성 (앱: 메일, 기기: 기타) → 16자리 비밀번호 생성
3. GitHub Secrets 등록:
   - `GMAIL_USER`: Gmail 주소 (예: yourname@gmail.com)
   - `GMAIL_APP_PASSWORD`: 생성된 16자리 앱 비밀번호
   - `GMAIL_TO`: 수신자 이메일

### GWS 파이프라인 위치

```
STEP 1: weekly_video_prep.py (대본 + 이미지)
STEP 2: weekly_video_make.py (TTS + 영상)
STEP 3: git commit & push
STEP 4: GitHub Artifact 업로드 (video.mp4, 30일)
STEP 5: gws_publish.py ← 신규 (YouTube · Sheets · Gmail)
```

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

**씬 구성 (4씬 — YouTube Shorts 세로 포맷)**:
| 씬 | 주제 | 배경 | 색상 | 로봇 무드 |
|----|------|------|------|--------|
| 1 | 주간 브리핑 | Wikipedia(Tesla Model 3 등) — 매주 동적 다운로드 | Purple | excited |
| 2 | 호재 뉴스 | `bg_scene_02.jpg` (Cybertruck 고정) | Green | happy |
| 3 | 리스크 뉴스 | `bg_scene_03.jpg` (Elon Musk 고정) | Red | worried |
| 4 | 시장 동향 | `bg_scene_04.jpg` (Gigafactory 고정) | Amber | focused |

> 씬 1은 매주 Wikipedia에서 새 사진 다운로드, 세로형 이미지(로고)는 자동 skip + fallback 후보 시도.
> 씬 2~4는 `data/scene-backgrounds/`의 고정 jpg를 사용해 품질·일관성 확보.

**레이아웃 (MBC 뉴스 쇼츠 스타일, 1080×1920)**:
- 헤더 (y=0~500): 네이비 그라데이션 + 브랜드 라벨 + 두 줄 헤드라인
- 사진 (y=500~1000): 배경 사진 contain-fit + 블러 cover
- 본문 (y=1040~1680): 씬별 카드 (간격 40px)
- 매수지수 범례 (y=1700~1870): 현재 점수 + 3단계 범례 + 면책 문구

**참고지수 시그널** (YouTube 정책 준수):
- 65점 이상 → 긍정 (초록)
- 45~64점 → 중립 (앰버)
- 44점 이하 → 신중 (빨강)
- "매수/매도/관망" 같은 직접적 표현은 사용 안 함

### STEP 2: `weekly_video_make.py`

**역할**: TTS 오디오 생성 + 애니메이션 영상 합성

**TTS 설정**:
```python
VOICE = "ko-KR-SunHiNeural"  # 젊은 한국 여성 (밝고 에너지 넘치는 톤)
RATE  = "+35%"                # 여성 목소리 특성상 남성보다 소폭 낮게
PITCH = "+8Hz"                # 약간 밝게 올림
```

**애니메이션 시스템** (moviepy 2.x `VideoClip`):
- `fx_ken_burns()` — 배경 이미지 줌인/줌아웃 + 패닝 (씬별 다른 방향, 7% 줌)
- `fx_speed_lines()` — 씬 시작 속도선 (액션감)
- `fx_scanline()` — CRT 스캔라인 + 이동 글로우
- `fx_pulse_glow()` — 상하 바 박동 글로우
- `fx_fade_in()` / `fx_fade_out()` — 씬 시작/끝 페이드
- `draw_robot_pil()` — 씬별 표정 변화하는 로봇 마스코트 (헤더 우측)

**로봇 마스코트 표정**:
- `excited` → 동그란 눈, 오픈 마우스 (씬 1)
- `happy` → 웃는 호 모양 눈 (씬 2)
- `worried` → 찡그린 눈, 빨간 입 (씬 3)
- `focused` → 가늘게 뜬 눈 (씬 4)

**출력**: 1080×1920 @ 24fps (YouTube Shorts 세로), 약 1~2분
**자원 관리**: `audio.close()`, `final.close()` 명시 호출로 파일 핸들 누수 방지

### STEP 5: `gws_publish.py` (선택, 시크릿 없으면 건너뜀)

**역할**: 생성된 video.mp4를 YouTube/Sheets/Gmail로 배포

- **YouTube**: OAuth2로 비공개 업로드(`unlisted`) → 직접 공개 전환 가능
- **Sheets**: Service Account로 주간 행 추가 (날짜·참고지수·주가·시그널·세션수·YouTube URL)
- **Gmail**: SMTP 587/STARTTLS, HTML 본문 + 씬 이미지 4장 CID 인라인

---

## 의존성

```bash
pip install -r requirements.txt
```

`requirements.txt`에 명시된 패키지:
- `anthropic` — Claude Opus 4 (1순위 대본)
- `google-genai` — Gemini 1.5 Flash (폴백)
- `google-api-python-client`, `google-auth`, `google-auth-httplib2` — YouTube/Sheets API
- `gspread` — Sheets 쉬운 인터페이스
- `Pillow`, `edge-tts`, `moviepy`, `numpy` — 이미지/오디오/영상

**GitHub Actions pip 캐시**: `actions/setup-python@v5`에 `cache: 'pip'` 설정 + `requirements.txt`로 매 실행 ~30-60초 단축.

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
- 자동: 매일 KST 09:00 (UTC 00:00, `cron: '0 0 * * *'`)
- 수동: GitHub Actions 탭 → `workflow_dispatch`

**주요 단계**:
1. Python 3.11 + pip 캐시 설정
2. 한글 폰트 설치 (`fonts-nanum`)
3. `pip install -r requirements.txt`
4. STEP 1: `weekly_video_prep.py` (대본 + 씬 이미지 4장)
5. STEP 2: `weekly_video_make.py` (TTS + 영상)
6. STEP 3: 대본/이미지 커밋 (MP3/MP4 제외)
7. STEP 4: video.mp4 → artifact 업로드 (30일 보관)
8. STEP 5: `gws_publish.py` — YouTube/Sheets/Gmail 게시 (시크릿 있을 때만, `continue-on-error: true`)

> **주의**: workflow_dispatch 수동 실행 시 `Use workflow from` 드롭다운에서 브랜치 확인 필수.
> 기본은 `master`라서 개발 브랜치의 새 코드를 테스트하려면 명시적 선택 필요.

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

## 앱 버전 히스토리

| 버전 | 날짜 | 주요 변경 |
|------|------|---------|
| **v2.2.0** | 2026-05-17 19:00 KST | 충격 인트로(씬0) + 다음주 예고(씬5) + 자극적 멘트 + Google Trends |
| v2.1.1 | 2026-05-17 18:00 KST | 영상 5가지 수정 · Ken Burns 사진 영역만 · TTS 톤 · 2줄 대본 · 90% 스케일 |
| v2.1.0 | 2026-05-17 15:00 KST | 영상 매일 자동 생성 · 대시보드 실행/다운로드 버튼 · 설정 버전 카드 |
| v2.0.0 | 2026-05-10 | 멀티 종목 Phase 1 · Ken Burns · 로봇 마스코트 · 백테스트 연도 분리 |
| v1.5.0 | 2026-04-20 | YouTube Shorts 세로 포맷 · GWS 통합 (YouTube/Sheets/Gmail) |
| v1.0.0 | 2026-03-01 | 초기 릴리즈 · AI 자동 분석 · 백테스트 · 캘린더 |

> 버전 업데이트 시 `index.html`의 `APP_VERSION` 상수와 이 표를 함께 수정할 것.

---

## 개발 히스토리 요약

### 2026-05 (주요 변경 묶음)

**파이프라인 기반 구축**
- moviepy 2.x 호환성 수정 (`from moviepy import`, `with_*` API)
- Gemini 폴백 추가 (Anthropic 크레딧 부족 대응)
- `google-genai` SDK로 전환 (v1beta → v1 API)
- `gemini-2.0-flash-lite` → `gemini-1.5-flash` 모델 변경

**영상 콘텐츠**
- 뉴스 스타일 UI + 2배 빠른 나레이션 + 1분 영상 목표
- Wikipedia 공식 사진 배경 적용 (씬 1은 매주 새 사진, 씬 2-4는 고정)
- 로봇 마스코트 캐릭터 추가 (씬별 표정 변화: excited/happy/worried/focused)
- 전체 애니메이션화 (`VideoClip` 기반 퍼-프레임 렌더링)
- 4씬 구조 재설계 (씬 5/6 결론·예측 제거, 뉴스 중심으로 단순화)

**YouTube Shorts 세로 포맷 전환**
- 1280×720 가로 → 1080×1920 세로 포맷 전환
- MBC 뉴스 쇼츠 스타일 레이아웃 (네이비 헤더 + 사진 + 본문 카드)
- 본문 프레임 상단 40px 여백 (사진과의 간격 확보)

**나레이션 / UI 다듬기**
- 남성 캐주얼 톤(`HyunsuNeural`, +50%) → 젊은 한국 여성 톤(`SunHiNeural`, +35%, +8Hz)
- 영상 하단 자막 오버레이 제거 (텍스트가 잘림 + 콘텐츠와 중복)
- 매수지수 범례 프레임 추가 (씬 하단, y=1700~1870)
- Ken Burns 효과 (배경 이미지 줌인/아웃 + 패닝, 씬별 다른 방향)

**YouTube 정책 준수**
- 매수/매도/관망 → 참고지수/긍정/중립/신중 (투자 권유 아닌 참고 표현)
- 면책 문구: "개인 분석 참고용 · 투자 판단은 본인 책임"

**Google Workspace 통합** (STEP 5)
- YouTube 자동 업로드 (OAuth2, `unlisted` 상태)
- Google Sheets 주간 히스토리 기록 (Service Account)
- Gmail 다이제스트 (SMTP, 씬 이미지 4장 CID 인라인)
- 시크릿 없으면 단계 건너뜀, 기존 파이프라인 무영향

**대시보드 UX**
- 각본 페이지에 Gemini Imagen 프롬프트 드롭다운 추가
- 씬별 이미지 프롬프트가 `script.json`의 `image_prompts` 필드로 자동 생성

### 2026-05 (코드 정리 + 멀티 종목 Phase 1)

**백테스트 매일 자동 + 연도 분리**
- `backtest-run.js` 일반화: `BACKTEST_YEAR` 환경변수 + `getCompletedWeeksForYear(year)` (이미 완료된 주만)
- 데이터 파일 분리: `data/backtest-results-2025.json`, `data/backtest-results-2026.json`
- 워크플로우: 매월 1일 → 매일 KST 03:00 (cron `0 18 * * *`). 이미 분석된 주는 skip
- `index.html` BacktestPage: 연도 탭(2025/2026) 추가, `getWeeksForYear(year, range)`로 동적 주 생성
- localStorage 캐시 키도 연도별 분리 (`tsla_backtest_v3_2025`, `tsla_backtest_v3_2026`)

**코드 정리 (-169줄)**
- 미사용 함수 삭제: `fx_subtitle()`, `find_font()` (make.py), `draw_robot()` (prep.py)
- 미사용 상수 삭제: `CARD`, `BORDER`, `SCENE_MOODS` (prep.py 중복분)
- 미사용 import 삭제: `textwrap`, `os` (make.py)
- 파라미터 체인 정리: `subtitle_lines`, `font_path` 제거 (자막 제거 후 더 이상 불필요)
- 청크 분할 로직 제거 (자막용이었으므로)
- `AudioFileClip` / `VideoClip` `.close()` 명시 (자원 누수 방지)
- `requirements.txt` 신규 + GitHub Actions `cache: 'pip'` (실행 ~30-60초 단축)

**멀티 종목 지원 Phase 1**
- `config/ticker.json` 신규 — 종목 설정 한 곳에 집중
- Python 스크립트 4개 적용 (`weekly_video_prep.py`, `weekly_video_make.py`, `gws_publish.py`, `youtube_sentiment.py`)
- 다른 종목 포크 시 `config/ticker.json`과 씬 배경 이미지 3장만 교체하면 동작
- Phase 2 (다음 단계): JS 스크립트, `index.html`, 데이터 모델 키 마이그레이션

---

## 이번 세션 주요 결정 사항

1. **GitHub Actions 브랜치 주의**: `workflow_dispatch`는 기본적으로 `master` 브랜치를 사용. 새 코드를 테스트하려면 드롭다운에서 명시적으로 dev 브랜치 선택, 또는 PR을 머지해야 함.

2. **포크 모델 선택**: 한 인스턴스가 멀티 종목을 동시 처리하는 게 아니라, **종목별 별도 저장소 포크** (tsla-dashboard → nvda-dashboard, aapl-dashboard 등). 따라서 모든 종목 관련 설정은 단일 설정 파일에서 분기.

3. **단계적 마이그레이션**: 멀티 종목 작업은 Phase 1 (Python만) → Phase 2 (JS/HTML) → Phase 3 (데이터 키)로 단계적 진행. 한 번에 다 바꾸면 위험.

4. **자원 누수 방지**: moviepy 클립 사용 후 명시적 `.close()` 호출. GitHub Actions 환경에서 파일 핸들 누수 시 후속 단계 실패 가능.

5. **YouTube 콘텐츠 정책**: 투자 권유로 해석될 표현(매수/매도/관망)을 사용하지 않음. 참고지수·긍정·중립·신중 + 면책 문구로 대체.
