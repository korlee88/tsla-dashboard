# GOOGL Dashboard — Fork Setup Guide

Alphabet(GOOGL) 전용 대시보드. `tsla-dashboard`의 일반화된 코드베이스를 그대로 사용하며, 이 디렉터리의 설정 파일만 교체하면 됩니다.

---

## 새 저장소 생성 절차

### 1. 저장소 생성 및 클론

```bash
# GitHub에서 korlee88/tsla-dashboard를 템플릿으로 새 저장소 생성
# (GitHub UI: Use this template 버튼 또는 gh CLI)
gh repo create korlee88/googl-dashboard --template korlee88/tsla-dashboard --public
git clone https://github.com/korlee88/googl-dashboard
cd googl-dashboard
```

### 2. 설정 파일 교체

이 `forks/googl/` 디렉터리의 파일을 새 저장소 루트의 `config/`로 복사:

```bash
cp forks/googl/config/ticker.json config/ticker.json
cp forks/googl/config/rules.json  config/rules.json
```

### 3. 씬 배경 이미지 교체

`data/scene-backgrounds/` 에 알파벳/구글 관련 배경 이미지를 준비:
- `bg_scene_02.jpg` — Googleplex 또는 구글 로고 배경
- `bg_scene_03.jpg` — Google DeepMind / Gemini AI 배경 (선택)
- `bg_scene_04.jpg` — Google Cloud / Waymo 배경 (선택)

이미지 규격: 1280×720 JPG (최대 500KB 권장)

### 4. GitHub Secrets 설정

새 저장소 Settings → Secrets and variables → Actions 에서 동일한 시크릿 등록:

| Secret | 용도 | 필수 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Claude 대본 생성 | ✅ |
| `GEMINI_API_KEY` | Gemini 분석/폴백 | ✅ |
| `YOUTUBE_API_KEY` | YouTube 관심도 수집 | 선택 |
| `GWS_YOUTUBE_TOKEN` | YouTube 자동 업로드 | 선택 |
| `GWS_SA_CREDENTIALS` | Google Sheets 기록 | 선택 |
| `GOOGLE_SHEET_ID` | Sheets 문서 ID | 선택 |
| `GMAIL_USER` | Gmail 발신 | 선택 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 | 선택 |
| `GMAIL_TO` | Gmail 수신 | 선택 |

> **보안 주의**: API 키는 코드나 채팅에 절대 공유하지 말 것. GitHub Secrets에만 입력.

### 5. GitHub Pages 활성화

저장소 Settings → Pages → Source: Deploy from a branch → `master` / `/ (root)`

### 6. 첫 실행 확인

1. Actions 탭 → `백테스트 실행` 워크플로 수동 실행 (`workflow_dispatch`)
2. `data/backtest-results-2025.json` 생성 확인
3. 분석 결과에 Alphabet/Google 뉴스가 포함되어 있는지 확인
4. `macroCtx.asset` 필드에 GOOGL 가격 데이터 확인

---

## GOOGL 룰셋 요약 (R01~R24)

| 룰 | 분류 | 방향 | 비고 |
|----|------|------|------|
| R01 | EPS 미스 | 하락 | 기본 실적 |
| R02 | 광고 매출 부진 | 하락 | 핵심 수익 |
| R03 | GCP 성장 둔화 | 하락 | 클라우드 |
| R04 | 검색 점유율 하락 | 하락 | 모아트 |
| R05 | DOJ 반독점 패소 | 하락 | 최대 규제 위험 |
| R06 | AI 검색 경쟁 위협 | 하락 | ChatGPT/Perplexity |
| R07 | 가이던스 하향 | 하락 | |
| R08 | GDPR/EU 제재 | 하락 | |
| R09 | 광고 경기 침체 | 하락 | 매크로 |
| R10 | YouTube 규제 | 하락 | |
| R11 | 구조조정/감원 | 혼합 | 단기 하락↔장기 비용절감 |
| R12 | EPS 비트 | 상승 | |
| R13 | 광고 매출 서프라이즈 | 상승 | |
| R14 | GCP 성장 가속 | 상승 | |
| R15 | Gemini AI 마일스톤 | 상승 | MAX +4 |
| R16 | 자사주 매입/배당 | 상승 | |
| R17 | 목표가 상향 | 상승 | MAX ±2 |
| R18 | 금리 인하 신호 | 상승 | MAX ±1 |
| R19 | Apple 기본검색 유지 | 상승 | **핵심 이벤트 MAX +4** |
| R20 | Waymo 상업화 | 상승 | MAX +3~+4 |
| R21 | 소송 승리 | 상승 | |
| R22 | 공매도 보고서 | 하락 | MAX ±2 |
| R23 | 경기침체 우려 | 하락 | MAX -1 |
| R24 | Apple 기본검색 상실 | **하락** | **핵심 위험 MAX -4** |

> R19(Apple 기본검색 유지)와 R24(상실)는 TSLA의 R25(Optimus 상업화)에 해당하는 단일 대형 이벤트.
> Apple은 구글 검색 매출의 약 15~20%를 차지하므로 계약 변경은 구조적 충격.
