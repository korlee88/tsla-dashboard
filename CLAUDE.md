# TSLA Dashboard — Claude Code 작업 기록

## 작업 원칙 (중요)

**Claude가 직접 할 수 있는 작업은 모두 자율적으로 진행한다.**
- PR 생성 → 머지까지 직접 수행
- 커밋 & 푸시 직접 수행
- 수동 개입이 반드시 필요한 경우(브라우저 로그인, 시크릿 입력 등)에만 사용자에게 알린다

## 프로젝트 개요

GitHub Pages 기반 Tesla(TSLA) 주간 분석 대시보드.
격일(월·수·금) KST 새벽 GitHub Actions가 자동으로 영상 자료를 생성한다 (최근 동향 정리 + 앞으로 전망). 영상마다 오프닝 훅·분석 관점·색상 테마를 바꿔 양산형 느낌을 줄인다.

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
| `image_future_tech_en` | `"FSD robotaxi..., Optimus..., 4680..., megapack..., Dojo..."` | `"H100/Blackwell GPU, CUDA AI platform, ..."` |
| `brand_label` | `"TSLA WEEKLY"` | `"NVDA WEEKLY"` |
| `repo` | `"korlee88/tsla-dashboard"` | `"korlee88/nvda-dashboard"` |
| `beta_coefficient` | `2.5` | `1.7` |
| `scene_wiki_articles` | Tesla 관련 4씬 | Nvidia/H100/Jensen Huang/HBM 등 |
| `scene_static_bg_files` | Tesla 배경 | Nvidia 배경 (새로 준비 필요) |
| `youtube_search_queries` | `["Tesla TSLA stock", ...]` | `["Nvidia NVDA stock", ...]` |
| `video_tags` | `["테슬라", "TSLA", ...]` | `["엔비디아", "NVDA", ...]` |

### 3. 씬 배경 이미지 교체
`data/scene-backgrounds/bg_scene_02.jpg`를 새 종목에 맞게 교체 (`config/ticker.json`의 `scene_static_bg_files`가 참조하는 유일한 정적 배경 — 나머지 씬은 Wikipedia/AI 생성 배경을 사용해 교체 불필요).

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
│   ├── weekly-video.yml       # 격일(월·수·금) 자동 실행 + workflow_dispatch
│   ├── auto-analysis.yml      # 1일 1회 자동 분석 (KST 08:00)
│   ├── backtest-run.yml       # 백테스트 (매일 자동 + 수동)
│   └── calendar-update.yml    # 매주 일정 갱신
├── config/
│   └── ticker.json            # 종목 설정 (TSLA/NVDA/AAPL 등 분기점)
├── scripts/
│   ├── weekly_video_prep.py   # STEP 1: 대본 + 씬 이미지 3장
│   ├── weekly_video_make.py   # STEP 2: TTS + 애니메이션 영상
│   ├── gws_publish.py         # STEP 5: YouTube/Sheets/Gmail 게시
│   ├── setup_gws_auth.py      # OAuth2 토큰 생성 헬퍼 (로컬 1회)
│   ├── make_bgm.py            # 원본 BGM(data/bgm.mp3) 합성기 (재생성용)
│   └── youtube_sentiment.py   # YouTube 검색·관심도 수집
├── data/
│   ├── auto-sessions.json     # 최근 7일 세션 데이터 (원본)
│   ├── backtest-results-2025.json  # 2025 백테스트 (완료)
│   ├── backtest-results-2026.json  # 2026 백테스트 (매일 증분 업데이트)
│   ├── bgm.mp3                # 영상 배경음악 (원본 합성·커밋, 빌드 네트워크 0)
│   ├── scene-backgrounds/     # 씬 2~4 고정 배경 이미지 (jpg)
│   └── weekly-report/
│       └── YYYY-MM-DD/
│           ├── script.json    # 생성된 대본 + image_prompts (커밋됨)
│           ├── script.txt     # 대본 원문
│           ├── image_prompts.txt  # Imagen 프롬프트 (Imagen 복붙용)
│           ├── meta.json      # 요약 데이터 (gws_publish가 사용)
│           ├── scene_00.png   # 씬 이미지 3장 (커밋됨, 0-based)
│           ├── scene_01.png
│           ├── scene_02.png
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

**역할**: 대본 + 씬 이미지 3장 생성

**대본 생성 우선순위**:
1. Claude Opus 4 (`claude-opus-4-7`) — `ANTHROPIC_API_KEY` 필요
2. Gemini 1.5 Flash — `GEMINI_API_KEY` 필요
3. 둘 다 없으면 RuntimeError

**대본 2단계 생성** (v2.8.2): 1차 생성(`generate_script`) → 재검수(`review_script`) 2단계로 진행. 재검수 단계는 반복 표현·어색한 문구를 다듬고, 미래 기술·사업방향(`{future_tech}`) 전달력이 막연하면 더 구체적으로 보강하도록 같은 LLM(Opus→Gemini 폴백, `_call_llm` 공용 헬퍼)에 한 번 더 요청한다. 검수 결과가 `SCENE_*`/`IMAGE_PROMPT_*` 마커 형식을 깨거나 호출 자체가 실패하면 1차 초안을 그대로 사용(파이프라인 보호) — `script.txt`/`script.json`에 기록되는 텍스트는 항상 이 2단계를 거친 최종본이다.

**호재/악재 BEST 선정** (v2.8.3): `summarize()`가 `top_bullish`/`top_bearish`를 정렬할 때 `RECENT_NEWS_DAYS`(2일) 이내 뉴스를 점수와 무관하게 최우선하는 `(is_recent, score)` 키를 사용 — 그 외엔 기존처럼 점수 순. 한 번 크게 터진 과거 뉴스(또는 날짜 메타데이터 오류)가 몇 주씩 BEST 자리를 고착하는 현상 방지. 최근 뉴스가 전혀 없는 주는 점수 순으로 자연 폴백해 빈 씬을 막는다.

**Gemini SDK**: `google-genai` (신규 SDK, NOT `google-generativeai`)
```python
from google import genai
client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
```

**씬 구성 (3씬 — YouTube Shorts 세로 포맷, idx 0-based)**:
| idx | 주제 | 배경 비율 | 색상 | 로봇 무드 |
|-----|------|----------|------|--------|
| 0 | 동향 브리핑 (1주 변동률·원인·호재·리스크) | 16:9 strip | Purple | focused |
| 1 | 호재 심층 1건 (BEST, 라운드 폰트) | 16:9 strip | Green | happy |
| 2 | 앞으로 전망 (클로징, 6줄: 일정·시나리오·가격예측·흐름·변수·마무리, `dailyForecasts` 예측 활용) | 9:16 full | Magenta | celebrating |

> 인트로(충격속보)·리스크·시장반응 씬은 제거됨. 미국장 휴장일에도 무리 없도록 호재 위주 3씬으로 단순화.
> 마지막 씬(idx 2) 최하단에 AI 생성 고지 밴드 표시 — "AI 분석 툴로 뉴스 자료를 분석해 요약한 영상물" 문구. 화면 표기 전용으로 `prep.py`에 하드코딩되어 있어 TTS가 읽지 않음.
> 배경은 Nano Banana AI 이미지가 1순위, 실패 시 Wikipedia 폴백.
> 이미지 프롬프트에는 `config/ticker.json`의 `image_future_tech_en`(미래 기술·사업계획 영문 키워드)을 `{future_tech}`로 주입 — `weekly_video_prep.py`의 `FUTURE_TECH_EN` 상수.
> **배경 비주얼 월드 로테이션** (v2.8.4): 배경의 장소·구도·무드는 생성일 시드로 `SCENE_VISUAL_WORLDS`(8종)에서 `pick_visual_world()`가 결정적으로 회전 선택해 `IMAGE_PROMPT_0~2` 템플릿의 `{visual_0/1/2}`로 주입된다. 한 월드가 3씬의 세계관을 공유(예: 사막 기가팩토리·해안 절벽·네온 도시·오로라…)하되 씬 의미(씬0 분석/씬1 초록 호재/씬2 미래비전 세로)는 유지. 회전 키는 `date.toordinal() % 8`이라 격일(간격 2~3일) 생성 시 인접 영상 배경이 반복되지 않는다(이전엔 템플릿이 서울 한강·남산타워 등으로 고정돼 매 영상 같은 배경처럼 보였음). 같은 날 재시도는 같은 월드 유지.
> **배경 콘텐츠 신호 반영** (v2.8.4): 비주얼 월드만으로는 장소만 바뀔 뿐 "이번 회차" 내용과 무관할 수 있어, `_build_prompt()`가 씬별 실제 데이터를 "이번 회차 신호"로 프롬프트에 추가 주입한다 — 씬0=`movement_reason_str`(이번 주 주가 변동 원인), 씬1=`best_bullish_str`(`summary["top_bullish"][0]`, 이번 회차 선정 BEST 호재), 씬2=`next_events_str`(예정 일정·후순위 스케줄). LLM이 이 신호를 글자·숫자 없이 상징적 시각 요소(사물·행동·분위기)로 녹여 `IMAGE_PROMPT_0~2`를 작성하도록 지시 — 배경이 장소만 다양해지는 게 아니라 그 주 실제 분석 내용(+ `{future_tech}` 로드맵)을 반영하게 됨. 호재 없는 주는 "특별한 호재 없음 — 전반적 안정세"로 자연 폴백.
> 점수(+N점)는 내부 지표이므로 대본·화면에 노출하지 않는다("호재"/"리스크"로만 표현).
> 호재 심층 씬(idx 1)은 `NanumSquareRound`(둥근 폰트)로 부드러운 톤 — CI는 `fonts-nanum-extra` 필요. 본문 머리기호는 초록 ✓ 체크(`draw_check`, 줄 첫 행에만 표시), 본문 폰트는 `sf_ct` 46px.
> **헤더 라벨·배지 자동 축소** (v2.8.4): `draw_bullish_hero_card()`의 "BEST" 배지(고정 110px)·카테고리/출처 헤더 라벨·하단 출처 바는 신규 `fit_label_width(draw, text, font, max_w)` 헬퍼로 폭을 측정해 넘치면 `font_variant()`로 폰트를 단계적으로 줄이고, 최소 크기에서도 넘치면 말줄임표(…)로 정리한다 — 본문처럼 줄바꿈하면 어색한 한 줄짜리 라벨용. "BEST"는 콘텐츠 길이와 무관하게 전달되는 폰트 크기(48px) 자체가 배지 폭보다 넓어 항상 잘릴 수 있던 버그였고, 카테고리·출처는 기존엔 `[:14]`/`[:50]` 글자수로만 잘라 실제 폭을 보장하지 못했다(영문 다중 태그 카테고리나 긴 출처명에서 위험). 배지 위치를 먼저 계산한 뒤 카테고리 라벨의 가용폭을 배지 기준으로 정하도록 그리는 순서도 변경.
> **프레임 템플릿 안전 영역 자동 맞춤** (v2.8.4): 모든 씬 위에 깔리는 통일 브랜드 프레임(`data/frame-template.png`, `generate_frame.py`가 Nano Banana로 1회 생성·`generate-frame.yml`이 자동 커밋)은 **사방 `BORDER_PX=90`px가 불투명 보더이고 중앙 900×1700만 투명**하다. 그런데 씬 콘텐츠는 `PAD=40`px 기준(텍스트 x≈60)으로 그려져, 프레임 적용 시 가장자리 텍스트(카드 라벨·본문 첫 글자)가 보더에 가려 잘렸다(실제 6/24 영상: "최근"→"근", "사이버캡"→"이버캡", "250억"→"50억"; 가운데 정렬 헤더만 안 잘림). 프레임은 콘텐츠 위에 합성될 뿐 좌표를 모르므로 레이아웃이 안전 영역을 침범한 게 원인. → `_apply_frame_overlay()`가 콘텐츠 전체를 **프레임의 투명 안전 영역 크기에 맞게 비율 유지 축소(레터박스)한 뒤 합성**하도록 변경. 안전 영역은 `_frame_safe_box()`가 프레임 **알파 채널의 투명 bbox**에서 자동 계산(보더 두께가 바뀌어도 적응, 하드코딩 아님), 레터박스 여백은 씬 배경색 `BG`로 채워 가장자리와 자연스럽게 섞임. 프레임 파일이 없으면(`_load_frame_overlay()` None) 기존 full-bleed 렌더 그대로 — 프레임 도입 전 브랜치/환경 무영향. `make_*.py`는 합성 완료된 `scene_XX.png`만 소비하므로 변경 없음.

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
VOICE         = "ko-KR-SunHiNeural"  # 밝은 여성 — 친근 튜닝
RATE          = "+8%"                 # 대화하듯 자연스러운 속도
PITCH         = "+6Hz"                # 살짝 올려 밝고 친근한 톤
LINE_PAUSE_MS = 600                   # 줄 사이 휴지 (ms)
TRIM_DB       = -42.0                 # 세그먼트 가장자리 무음 판정 임계 (dBFS)
TRIM_KEEP_MS  = 60                    # 트리밍 후 가장자리에 남길 무음 (ms)
SCENE_LEAD_MS = 500                   # 씬 시작~첫 나레이션 사이 여유 무음 (씬 전환 딜레이)
SCENE_TAIL_MS = 300                   # 씬 끝 여유 무음 (ms)
```
> 나레이션은 옆에서 다정하게 이야기해 주는 친근한 구어체 톤. `build_scene_tts_segments()`의 브리지 문장도 구어체("같이 볼까요?", "자세히 들여다볼게요").
> 줄 단위로 edge-tts MP3를 따로 만들고 `pydub`으로 줄 사이 무음을 끼워 합쳐서 자연스러운 호흡을 만든다 — 너무 빨리 다음 줄로 넘어가지 않도록.
> **줄 간격 보정**: edge-tts가 각 세그먼트 꼬리에 ~0.5초+ 자체 무음을 붙여서, 1000ms 삽입 무음과 겹치면 체감 간격이 1.5초+로 늘어난다. `_trim_edge_silence()`가 `pydub.silence.detect_leading_silence`로 앞·뒤(`piece.reverse()`) 무음을 측정해 `TRIM_KEEP_MS`만 남기고 잘라낸다(전체 무음 판정 시 원본 유지하는 과도 트리밍 가드 포함). 트리밍 + `LINE_PAUSE_MS=600`으로 체감 간격을 ~720ms로 일정하게 맞춘다.
> **씬 전환 딜레이**: `gen_audio()`가 합성한 씬 오디오 앞에 `SCENE_LEAD_MS`(0.5초), 뒤에 `SCENE_TAIL_MS`(0.3초) 무음을 더한다 — 씬 전환(크로스페이드) 직후 나레이션이 곧바로 시작되지 않고 한 박자 쉬어 간다. **단일 세그먼트 씬도 동일 적용**(이전엔 단일 줄 씬이 lead 무음 없이 바로 시작됐다).

**BGM** (배경음악):
```python
BGM_VOLUME = 0.10                      # 나레이션 아래 배경음 (10%)
BGM_CACHE  = data/bgm.mp3              # 저장소에 커밋된 음원
```
> 배경음악은 **저장소에 커밋된 `data/bgm.mp3`** 만 사용한다 → 빌드 시 네트워크 의존 0. `download_bgm()`은 이 파일을 반환만 하며 외부 다운로드(yt-dlp 등)는 하지 않는다.
> 음원은 `scripts/make_bgm.py`가 합성한 **원본 앰비언트 패드**(C–Am–F–G maj7 + 아르페지오 + 약한 잔향, 이음매 없는 ~63초 루프, 스테레오)라 저작권·출처 표기 의무가 없다. 외부 CC0 사이트는 빌드 환경에서 불안정(FreePD=JS 렌더링, archive.org=CC0 검색 비고, yt-dlp+YouTube=러너 IP 봇 차단)해서 직접 합성·커밋으로 확정했다.
> **밋밋함 개선** (v2.8.2): 기존 버전은 완전 모노 + 4회 반복 사이클이 전부 동일한 아르페지오·다이내믹스라 ~63초 루프 전체를 들어도 변화가 없었다. 좌우 채널을 몇 센트 디튠한 코러스 패드(`grain_stereo`)로 스테레오 폭을 만들고, 사이클별로 다른 아르페지오 편성(`ARP_PATTERNS` — 사이클0 패드만(도입)→1 절반 밀도(빌드업)→2 원곡 풀 패턴→3 변형 패턴(클라이맥스))과 결정론적(seed=42) 하이엔드 스파클(`SPARKLE_COUNTS`, 사이클마다 0→2→3→5개로 증가)을 더해 빌드업/클라이맥스 아크를 만들었다. 아르페지오는 핑퐁 패닝(`PAN_STEPS`)으로 움직이고, 기존 진폭 트레몰로(~8.3초 주기)와는 별개로 ~22초 주기의 스테레오 폭 "숨쉬기" 변조(mid/side 블렌드)를 추가했다. 루프 크로스페이드가 실제 파형을 블렌딩하므로 사이클3(클라이맥스)→사이클0(도입) 밀도 차이도 자연스러운 릴리즈처럼 이어진다.
> 재생성: `pip install numpy lameenc && python scripts/make_bgm.py` (결정론적 합성 — 출력 동일). 교체하려면 `data/bgm.mp3`만 원하는 트랙으로 바꿔 커밋.
> 믹싱은 루프 횟수만큼 **새 `AudioFileClip` 인스턴스를 만들어** `concatenate_audioclips`로 이어 붙인다(같은 인스턴스 재사용 시 리더 start가 공유돼 루프가 깨짐). `write_videofile` **전에 BGM 클립을 close하지 않는다**(리더 끊김 방지) — 프로세스 종료 시 정리.

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
- **Sheets**: Service Account로 행 추가 (날짜·참고지수·주가·시그널·세션수·YouTube URL)
- **Gmail**: SMTP 587/STARTTLS, HTML 본문 + 씬 이미지 3장 CID 인라인

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
- 자동: 격일(월·수·금) KST 05:15 (1차) / 07:15 (2차 재시도). UTC 기준 일·화·목 cron `'15 20 * * 0,2,4'`, `'15 22 * * 0,2,4'`. 같은 날 이미 생성됐으면 자동 skip
- 수동: GitHub Actions 탭 → `workflow_dispatch`

> **양산형 탈피** (v2.8.0): 격일 생성으로 영상이 잦아진 만큼 매 영상이 비슷해 보이지 않도록 생성일(KST 날짜) 시드로 변형한다.
> - **오프닝 훅 8종**(`HOOK_STYLES`/`pick_hook`, prep.py): 질문·충격수치·역발상·결론선공개·스토리·비교·호기심·임팩트 — `_build_prompt`가 `week_end` 시드로 골라 `{hook_style}`로 프롬프트에 주입. "오늘의 뉴스"·"N건 분석" 식 고정 오프닝 금지.
> - **차별화 관점 1줄**(프롬프트 "오프닝 훅 & 차별화" 블록): 시장 컨센서스·통념과 다른 분석가만의 시각 1줄 의무(단순 요약·낭독 금지), 씬1 향후전망 또는 씬2에 배치.
> - **색상 테마 3종**(`ACCENT_THEMES`/`_theme_idx`, prep.py·make.py **양쪽 동일**): 보라·시안·인디고 계열 로테이션. 씬1(호재)은 의미상 항상 초록 유지. 두 파일이 같은 `_theme_idx(date_str)`로 계산해 정적 이미지(prep)와 애니메이션(make) 색상이 동기화된다 — prep는 `main()`에서 `SCENE_ACCENTS`를 today로, make는 `build_video_async`에서 `ACCENT_COLORS`를 `report_dir.name`(날짜)으로 재할당.
> - **배경 비주얼 월드 8종**(`SCENE_VISUAL_WORLDS`/`pick_visual_world`, prep.py, v2.8.4): 배경 장소·시간대·구도·무드를 회전(서울 야경·사막 기가팩토리·해안 절벽·네온 도시·알프스·항구·시험주행장·오로라). `_build_prompt`가 `week_end`의 `date.toordinal() % 8`로 골라 `{visual_0/1/2}`로 주입. 색상 테마(`_theme_idx`, mod 3)와 **다른 키**라 색·배경이 독립 변형. 이전엔 이미지 프롬프트가 서울 한강·남산타워 등으로 고정돼 영상마다 같은 배경처럼 보이던 문제를 해결.
> - **배경 콘텐츠 신호**(`best_bullish_str`/`movement_reason_str`/`next_events_str`, prep.py, v2.8.4): 비주얼 월드(장소)와는 별개로, 씬별 실제 이번 회차 데이터(씬0 변동원인·씬1 BEST호재·씬2 예정일정)를 상징적 시각 요소로 녹이도록 LLM에 지시 — 장소만 바뀌는 게 아니라 그 주 실제 분석 내용을 반영한 배경이 되도록 함.

**주요 단계**:
1. Python 3.11 + pip 캐시 설정
2. 한글 폰트 설치 (`fonts-nanum`)
3. `pip install -r requirements.txt`
4. STEP 1: `weekly_video_prep.py` (대본 + 씬 이미지 3장)
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

### ffmpeg/ffprobe 누락 (2026-06-12)
`weekly_video_make.py`의 `gen_audio()`가 `pydub.AudioSegment.from_file()`로 TTS MP3를 합치는데,
`ubuntu-latest` 러너 이미지에 `ffmpeg`(`ffprobe` 포함)가 더 이상 기본 설치되어 있지 않아
`FileNotFoundError: ffprobe`로 STEP 2가 실패할 수 있음 (STEP 1은 정상 완료, STEP 3~5는 skip됨).
→ 워크플로우의 "한글 폰트 설치" 단계에서 `ffmpeg`도 함께 `apt-get install`하여 해결.

---

## 대본 스타일 가이드

대본은 **친근한 사람이 옆에서 다정하게 말해 주는 구어체 톤**:
- 한 줄 30자 이내, 씬당 4~6줄
- 친근한 구어체 어미: "~예요", "~네요", "~거든요", "~죠", "~봐요"
- 다정하게 말 걸기: "여러분", "같이 볼까요?", "흥미롭죠?"
- 과한 클릭베이트 추임새(충격!·헐!·대박!)는 지양, 부드러운 반응은 환영
- 핵심 수치는 반드시 포함
- **핵심 강조 마커**: 가장 중요한 수치·키워드를 `*별표*`로 감싸면 화면에서 골드(KEY)로 강조 표시됨. 한 줄당 최대 1~2개.
  - 렌더: `split_runs()`/`wrap_runs()`/`draw_rich_line()` (prep.py) — 마커 기준 색상 분할
  - TTS: `clean_for_tts`/`_clean_line`에서 `*` 제거(읽지 않음)

---

## 앱 버전 히스토리

| 버전 | 날짜 | 주요 변경 |
|------|------|---------|
| **v2.8.4** | 2026-06-24 KST | 씬 배경 이미지 반복 문제 수정(`weekly_video_prep.py`). 원인: `SCRIPT_PROMPT_TEMPLATE`의 `IMAGE_PROMPT_0~2` 예시가 "서울 한강 야경·남산타워(씬0) / 반포대교 초록(씬1) / 광화문 마젠타(씬2)"로 **하드코딩**돼 있어 LLM이 매번 같은 장소·구도·색을 그대로 베꼈고, Nano Banana가 매번 새 픽셀을 생성해도(파일 md5는 달라도) 영상마다 사실상 **동일한 배경**처럼 보였음. 오프닝 훅(`HOOK_STYLES`/`pick_hook`)·색상 테마(`ACCENT_THEMES`/`_theme_idx`)는 생성일 시드로 로테이션되는데 **배경만 그 로테이션에서 빠져 있던 누락**이 핵심. → 생성일 시드 기반 **8종 비주얼 월드 로테이션**(`SCENE_VISUAL_WORLDS`/`pick_visual_world`) 신규: ①서울 K-테크 야경(기존 룩) ②미국 사막 기가팩토리 ③태평양 해안 절벽 ④네온 사이버펑크 ⑤알프스 산악 ⑥미래형 항구 ⑦자동차 시험 주행장 ⑧오로라 북방. 한 월드가 3씬의 '세계관'을 공유하되 씬 의미(씬0 분석 브리핑/씬1 초록 호재/씬2 미래비전 세로)·비율(16:9/9:16)은 유지하고, `{future_tech}`(FSD·옵티머스·4680·메가팩·도조)는 템플릿 꼬리에서 별도 주입돼 모든 월드에 테슬라 로드맵 요소가 함께 반영됨. 선택은 `random.choice`(인접 날짜에 우연히 같은 월드가 겹쳐 반복이 재발할 수 있음)가 아니라 **날짜 ordinal 기반 결정적 회전**(`datetime.toordinal() % 8`)이라 격일(월·수·금, 간격 2~3일) 생성 시 인접 영상이 같은 월드로 반복되지 않음(검증: 14회 연속 인접 반복 0건·8종 전부 사용). 같은 날 재시도(05:15→07:15)는 같은 날짜라 같은 월드 유지, 날짜 파싱 실패 시 `sum(ord)` 폴백. 템플릿의 `{industry_ko}` 미사용 플레이스홀더 정리. `make_*.py`는 합성 완료된 `scene_XX.png`만 소비하므로 변경 없음. 추가로 호재 심층 씬(idx 1) 텍스트가 프레임을 벗어나는 문제 수정 — ①`draw_bullish_hero_card()`의 "BEST" 배지가 고정 110px 폭인데 실제 전달되는 폰트 크기(48px)에선 텍스트 폭이 ~118px로 배지보다 넓어 "T"가 잘려 보이는 버그(콘텐츠 길이와 무관하게 항상 발생, 실측으로 재현 확인) ②카테고리·출처 라벨이 `[:14]`/`[:50]` **글자수** 기준으로만 잘렸을 뿐 실제 픽셀 폭은 측정하지 않아, 영문 다중 태그 카테고리(예: `Earnings|Product|Competition|Market`)나 긴 출처명(실 데이터 최장 82자)이 배지와 겹치거나 카드 밖으로 밀려날 수 있던 구조적 위험 → 신규 `fit_label_width()`(폭 초과 시 `font_variant()`로 단계적 축소 후 그래도 넘치면 말줄임표) 도입, 배지·라벨·출처 3곳 모두 적용. 배지를 라벨보다 먼저 배치해 라벨의 가용폭을 배지 위치 기준으로 계산하도록 순서 변경. **추가로 영상 프레임 템플릿(`data/frame-template.png`) 적용 후 모든 씬의 가장자리 텍스트가 잘리던 문제 수정** — 프레임은 사방 90px(`BORDER_PX`)가 불투명 보더이고 중앙 900×1700만 투명한데, 씬 콘텐츠가 `PAD=40`px(텍스트 x≈60) 기준으로 그려져 가장자리 글자가 보더에 가려졌음(실제 6/24 영상에서 "최근"→"근", "사이버캡"→"이버캡", "250억"→"50억", 가운데 정렬 헤더만 무사). 프레임은 6/24 첫 자동 생성·커밋(`fee5099`)됐고 코드(`_apply_frame_overlay`)는 이미 있었으나 콘텐츠 레이아웃이 안전 영역에 맞춰지지 않은 게 핵심. → `_apply_frame_overlay()`가 콘텐츠 전체를 프레임 투명 안전 영역에 맞게 비율 유지 축소(레터박스)한 뒤 합성하도록 변경, 안전 영역은 `_frame_safe_box()`가 알파 bbox에서 자동 계산(보더 두께 변경에 적응), 여백은 `BG`로 채움. 프레임 없으면 기존 full-bleed 유지(폴백). 6/24 실제 데이터(같은 대본·배경)로 3씬 재렌더링해 전 텍스트가 프레임 안에 들어옴을 시각 확인 |
| v2.8.3 | 2026-06-22 KST | 호재/악재 BEST 선정 고착 버그 수정(`weekly_video_prep.py`의 `summarize()` — 기존엔 recency가 점수에 소폭(bullish만 최대 +0.5, bearish는 가중치 자체가 없음) 가산되는 방식이라, 한 번 크게 터진 과거(또는 날짜 메타데이터가 잘못된) 뉴스가 몇 주씩 BEST 자리를 그대로 차지하는 고착 현상이 있었음 → `RECENT_NEWS_DAYS`(2일) 이내 뉴스는 점수와 무관하게 최우선하는 `(is_recent, score)` 튜플 정렬로 변경, 최근 뉴스가 전혀 없는 주는 기존처럼 점수 순으로 자연 폴백(빈 씬 방지). 실제 영향 사례: 과거 `data/weekly-report/*/script.json`에서 날짜가 `2024-04-02`/`2025-04-02`로 잘못 찍힌 "1분기 인도량 하회" 악재가 2026-05-20~05-30(9회), 변형된 형태로 06-05~06-13까지 악재 BEST를 지속 점유한 사례를 확인 — 과거 데이터 자체는 임의로 수정하지 않고 그대로 보존함) |
| v2.8.2 | 2026-06-20 KST | 마지막 씬(idx 2) 캘린더 일정 카드 날짜·제목 텍스트 겹침 수정(`next_events` 슬림 카드 — 같은 줄에 고정 30자 절단하던 방식 → `wrap_text()` 기반 폭 계산으로 제목을 날짜 아래 별도 줄에 배치, 카드 높이 동적 계산) · BGM "밋밋함" 근본 수정(`make_bgm.py` — 기존엔 완전 모노+사이클 4회 전부 동일한 아르페지오/다이내믹스라 반복재생 체감이 평평했음 → 좌우 채널 디튠 코러스 패드, 사이클별 빌드업·클라이맥스 편성(`ARP_PATTERNS`: 패드만→절반 밀도→풀 텍스처→변형+스파클), 아르페지오 핑퐁 패닝, 결정론적 하이엔드 스파클(`SPARKLE_COUNTS`), 진폭 트레몰로와 별개 주기(~22초)의 스테레오 폭 "숨쉬기" 변조 추가, MP3 stereo 출력 전환·`data/bgm.mp3` 재생성) · 대본 생성 파이프라인에 재검수 단계 신규 추가(`weekly_video_prep.py` — 1차 생성 직후 `review_script()`가 반복 표현·어색한 문구를 다듬고 미래 기술·사업방향(`{future_tech}`) 전달력을 보강하도록 2차 LLM 호출, 기존 Opus→Gemini 폴백 로직은 `_call_llm()` 공용 헬퍼로 추출해 1차 생성·재검수 양쪽에서 재사용, 검수 결과가 형식(SCENE/IMAGE_PROMPT 마커)을 깨거나 호출 자체가 실패하면 1차 초안을 그대로 사용해 파이프라인 보호) |
| v2.8.1 | 2026-06-19 KST | 격일(월·수·금) 전환 후 남아있던 "주간"/"매일" 표기 정리(워크플로 이름·각본 페이지·TTS 나레이션·이메일 제목/본문·코드 주석, `weekly_video_prep.py`/`weekly_video_make.py`/`gws_publish.py`/`ticker.json`/`index.html`) · `rules.json` R24 설명 갱신(SpaceX는 2026-06-13경 상장돼 더 이상 "비상장 벤처"가 아님 — "X/DOGE" 스필오버와 분리해 독립 평가하도록 수정) · Gmail 다이제스트 시그널 색상이 항상 회색으로만 표시되던 버그 수정(`signal_color` 딕셔너리 키가 실제 반환값과 불일치) · Gmail 씬 캡션이 구버전 6씬 라벨(충격인트로 등)을 쓰던 버그 수정(현재 3씬에 맞게 교체) · 각본 페이지 이미지 프롬프트 드롭다운 버그 수정(씬0 프롬프트 미표시·씬1-2 오라벨링·씬3-4 무효 항목, 0-based 3씬에 맞게 수정) |
| v2.8.0 | 2026-06-18 KST | 영상 격일 생성(주1회 → 월·수·금 KST, cron `'15 20 * * 0,2,4'`/`'15 22 * * 0,2,4'`) · 양산형 탈피: 오프닝 훅 8종 로테이션(`HOOK_STYLES`/`pick_hook`, 고정 오프닝 제거) · 차별화 관점 1줄 의무 · 색상 테마 3종 로테이션(`ACCENT_THEMES`/`_theme_idx`, prep·make 동기화, 씬1 호재는 초록 유지) |
| v2.7.0 | 2026-06-17 KST | 뉴스 출처 국적·신뢰도 태그(`SOURCE_INFO`/`CRED_TIER`/`sourceMeta()`/`SourceTag`, 메인·모바일 카드+세션 상세에 표시) · 이미지 프롬프트에 미래 기술·사업계획 반영(`image_future_tech_en`/`FUTURE_TECH_EN`/`{future_tech}`) · 호재 씬 ↑화살표 → ✓체크 머리기호(`draw_check`) + 본문 폰트 축소(50→46) |
| v2.6.4 | 2026-06-14 KST | 영상 BGM 복구·풍성화(원본 합성 `data/bgm.mp3` 커밋·`make_bgm.py`, yt-dlp 외부 다운로드 제거) · BGM 루프 믹싱 버그 수정(루프마다 새 클립·write 전 close 금지) · 씬 전환 0.5초 딜레이(`SCENE_LEAD_MS`/`SCENE_TAIL_MS`, 단일 세그먼트 씬 포함) |
| v2.6.3 | 2026-06-12 KST | TTS 줄 간격 보정 — edge-tts 세그먼트 가장자리 무음 트리밍(`_trim_edge_silence`) + `LINE_PAUSE_MS` 1000→600ms (체감 간격 ~720ms 균일화) |
| v2.6.2 | 2026-06-12 KST | 자동 분석 스케줄 하루 4회 → 1일 1회(KST 08:00)로 전환 · API 사용량 추정치 갱신 |
| v2.6.1 | 2026-06-11 KST | 보안 강화 — CDN 버전 고정+SRI(react/react-dom/babel 프로덕션 전환, tailwind 고정) · YouTube HttpError 로그 키 노출 차단 · Gmail 수신자 로그 제거 |
| v2.6.0 | 2026-06-02 KST | scoring.js v5.0 — 중립밴드 · 증폭재조정(×1.35→×1.15) · 편향보정(beta 2.5→2.0) · **추세필터[18]** (3주 가격추세, 뉴스독립) · backtest 2025: 57%→65%, 2026: 40%→50% (회귀 0건) |
| v2.5.0 | 2026-05-29 KST | 영상 생성 주 1회 금요일로 전환(매일→주간) · 씬2 "다음주 전망" 개편 · AI 가격 예측(dailyForecasts) 활용 · Phase 1 종료 |
| v2.4.0 | 2026-05-27 KST | 종합 매매 신호 가중 합성(매수지수 60% + AI전망 40%) |
| v2.3.0 | 2026-05-25 KST | 인트로 씬 제거 → 3씬(브리핑·호재·미래) · 주간 변동률 표시 · 점수 라벨 제거 · 호재 씬 라운드 폰트(NanumSquareRound) |
| v2.2.0 | 2026-05-17 19:00 KST | 충격 인트로(씬0) + 다음주 예고(씬5) + 자극적 멘트 + Google Trends |
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
