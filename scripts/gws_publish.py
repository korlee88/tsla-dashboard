"""
GWS 게시 스크립트 — YouTube 업로드 + Sheets 기록 + Gmail 다이제스트

매주 GitHub Actions에서 weekly_video_make.py 이후 호출됨.
시크릿이 없는 통합은 조용히 건너뜀 — 기존 파이프라인에 영향 없음.

필요 환경변수 (선택):
  GWS_YOUTUBE_TOKEN  — YouTube OAuth2 token.json 내용 (JSON 문자열)
  GWS_SA_CREDENTIALS — Google Service Account JSON (Sheets 쓰기용)
  GOOGLE_SHEET_ID    — 기록할 스프레드시트 ID
  GMAIL_USER         — 발신 Gmail 주소
  GMAIL_APP_PASSWORD — Gmail 앱 비밀번호 (2FA 활성화 후 생성)
  GMAIL_TO           — 수신자 이메일 주소

필요 패키지:
  pip install google-api-python-client google-auth google-auth-httplib2 gspread
"""

import base64
import json
import os
import smtplib
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT_DIR           = Path(__file__).parent.parent
TICKER_CONFIG      = json.loads((ROOT_DIR / "config" / "ticker.json").read_text(encoding="utf-8"))
TICKER             = TICKER_CONFIG["ticker"]
COMPANY_KO         = TICKER_CONFIG["company_ko"]
BRAND_LABEL        = TICKER_CONFIG["brand_label"]
REPO               = TICKER_CONFIG["repo"]
VIDEO_TAGS         = TICKER_CONFIG.get("video_tags", [TICKER, "주식", "Shorts"])

REPORT_BASE        = ROOT_DIR / "data" / "weekly-report"

GWS_YOUTUBE_TOKEN  = os.environ.get("GWS_YOUTUBE_TOKEN", "")
GWS_SA_CREDENTIALS = os.environ.get("GWS_SA_CREDENTIALS", "")
GOOGLE_SHEET_ID    = os.environ.get("GOOGLE_SHEET_ID", "")
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_TO           = os.environ.get("GMAIL_TO", "")


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def find_latest_report() -> Path | None:
    """data/weekly-report/ 에서 meta.json이 있는 가장 최근 디렉토리 반환."""
    if not REPORT_BASE.exists():
        return None
    dirs = sorted(
        (d for d in REPORT_BASE.iterdir() if d.is_dir() and (d / "meta.json").exists()),
        reverse=True,
    )
    return dirs[0] if dirs else None


def load_meta(report_dir: Path) -> dict:
    return json.loads((report_dir / "meta.json").read_text(encoding="utf-8"))


def get_signal_label(avg_buy_index: int | None) -> str:
    if avg_buy_index is None:
        return "정보없음"
    if avg_buy_index >= 65:
        return "긍정"
    if avg_buy_index >= 45:
        return "중립"
    return "신중"


def get_youtube_credentials():
    """GWS_YOUTUBE_TOKEN JSON → google.oauth2.credentials.Credentials (자동 갱신)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_data = json.loads(GWS_YOUTUBE_TOKEN)
    creds = Credentials.from_authorized_user_info(token_data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def get_sheets_credentials():
    """GWS_SA_CREDENTIALS JSON → google.oauth2.service_account.Credentials."""
    from google.oauth2.service_account import Credentials

    sa_data = json.loads(GWS_SA_CREDENTIALS)
    return Credentials.from_service_account_info(
        sa_data,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


# ── YouTube 업로드 ─────────────────────────────────────────────────────────────

def upload_to_youtube(report_dir: Path, meta: dict, script_txt: str) -> str | None:
    """video.mp4 를 YouTube Shorts (비공개) 로 업로드. 성공 시 youtu.be URL 반환."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    video_path = report_dir / "video.mp4"
    if not video_path.exists():
        print("   [SKIP] video.mp4 없음 — YouTube 업로드 건너뜀", file=sys.stderr)
        return None

    creds   = get_youtube_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    date   = meta.get("generated_at", "")
    bi     = meta.get("avg_buy_index") or 0
    price  = meta.get("latest_price")
    signal = get_signal_label(bi)

    try:
        price_str = f"${float(price):,.0f}" if price else ""
    except (TypeError, ValueError):
        price_str = ""

    title = f"{TICKER} 주간 분석 {date} | 참고지수 {bi}점 {signal}"
    if price_str:
        title += f" · {price_str}"
    title = (title + " #Shorts")[:100]

    description = (script_txt or f"{TICKER} 주간 분석 자동 생성 영상")[:5000]

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": VIDEO_TAGS,
            "categoryId": "25",
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": "unlisted", # 업로드 후 직접 공개 전환 가능
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True),
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"   YouTube 업로드 진행: {pct}%")

    video_id = response.get("id", "")
    return f"https://youtu.be/{video_id}" if video_id else None


# ── Google Sheets 기록 ────────────────────────────────────────────────────────

SHEET_HEADER = ["날짜", "매수지수", "주가($)", "매수신호", "세션수", "YouTube링크"]


def log_to_sheets(meta: dict, youtube_url: str | None) -> bool:
    """Sheets에 주간 분석 결과 1행 추가. 첫 실행 시 헤더 자동 생성."""
    import gspread
    from google.auth.transport.requests import Request

    creds = get_sheets_credentials()

    gc   = gspread.authorize(creds)
    sh   = gc.open_by_key(GOOGLE_SHEET_ID)
    ws   = sh.sheet1

    # 헤더 없으면 첫 행에 자동 추가
    try:
        first_cell = ws.cell(1, 1).value
    except Exception:
        first_cell = None
    if not first_cell:
        ws.append_row(SHEET_HEADER, value_input_option="USER_ENTERED")

    bi     = meta.get("avg_buy_index")
    price  = meta.get("latest_price")
    signal = get_signal_label(bi)

    row = [
        meta.get("generated_at", ""),
        bi if bi is not None else "",
        float(price) if price else "",
        signal,
        meta.get("session_count", ""),
        youtube_url or "",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return True


# ── Gmail 다이제스트 ───────────────────────────────────────────────────────────

def _build_html(meta: dict, youtube_url: str | None, scene_count: int) -> str:
    bi     = meta.get("avg_buy_index") or 0
    price  = meta.get("latest_price")
    date   = meta.get("generated_at", "")
    signal = get_signal_label(bi)

    try:
        price_str = f"${float(price):,.2f}" if price else "N/A"
    except (TypeError, ValueError):
        price_str = "N/A"

    signal_color = {"매수": "#22c55e", "관망": "#f59e0b", "매도": "#ef4444"}.get(signal, "#6b7280")

    yt_section = ""
    if youtube_url:
        yt_section = f"""
        <p style="text-align:center;margin:24px 0;">
          <a href="{youtube_url}"
             style="background:#ef4444;color:#fff;padding:12px 32px;border-radius:8px;
                    text-decoration:none;font-weight:bold;font-size:16px;">
            ▶ YouTube에서 시청
          </a>
        </p>"""

    scene_imgs = ""
    scene_labels = ["충격 인트로", "주간 브리핑", "호재 뉴스", "리스크 뉴스", "시장 반응", "다음주 예고"]
    for i in range(0, scene_count):
        label = scene_labels[i] if i < len(scene_labels) else f"씬 {i}"
        scene_imgs += f"""
        <div style="margin:20px 0;">
          <p style="color:#9ca3af;font-size:13px;margin:0 0 6px;">씬 {i} — {label}</p>
          <img src="cid:scene_{i:02d}" style="width:100%;max-width:480px;border-radius:12px;display:block;">
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<body style="margin:0;padding:0;background:#0e1117;font-family:'Apple SD Gothic Neo',sans-serif;color:#f9fafb;">
  <div style="max-width:600px;margin:0 auto;padding:24px;">
    <div style="background:#0f2046;border-radius:16px;padding:24px;margin-bottom:20px;">
      <p style="color:#87dcff;font-size:13px;margin:0 0 8px;letter-spacing:2px;">{BRAND_LABEL}</p>
      <h1 style="color:#fff;font-size:24px;margin:0 0 4px;">{date} 주간 분석</h1>
    </div>

    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
      <tr style="background:#1c1f26;">
        <td style="padding:16px;border-radius:10px 0 0 10px;">
          <p style="color:#9ca3af;font-size:12px;margin:0 0 4px;">참고지수</p>
          <p style="color:{signal_color};font-size:28px;font-weight:bold;margin:0;">{bi}점</p>
        </td>
        <td style="padding:16px;background:#141720;">
          <p style="color:#9ca3af;font-size:12px;margin:0 0 4px;">현재가</p>
          <p style="color:#ffd700;font-size:28px;font-weight:bold;margin:0;">{price_str}</p>
        </td>
        <td style="padding:16px;background:#1c1f26;border-radius:0 10px 10px 0;">
          <p style="color:#9ca3af;font-size:12px;margin:0 0 4px;">시그널</p>
          <p style="color:{signal_color};font-size:28px;font-weight:bold;margin:0;">{signal}</p>
        </td>
      </tr>
    </table>

    {yt_section}

    <div style="margin-top:28px;">
      <h2 style="color:#87dcff;font-size:16px;margin:0 0 16px;">씬 이미지</h2>
      {scene_imgs}
    </div>

    <p style="color:#374151;font-size:12px;text-align:center;margin-top:32px;">
      자동 생성 — {TICKER} Dashboard · {REPO}
    </p>
  </div>
</body>
</html>"""


def send_gmail_digest(report_dir: Path, meta: dict, youtube_url: str | None) -> bool:
    """씬 4장 인라인 첨부 HTML 이메일을 Gmail SMTP로 발송."""
    date   = meta.get("generated_at", "이번 주")
    bi     = meta.get("avg_buy_index") or 0
    signal = get_signal_label(bi)

    subject = f"{TICKER} 주간 브리핑 {date} | 참고지수 {bi}점 ({signal})"

    # 씬 이미지 수집 (0~5: 인트로 + 본편 4 + 클로징)
    scene_paths = []
    for i in range(0, 6):
        p = report_dir / f"scene_{i:02d}.png"
        if p.exists():
            scene_paths.append((i, p))

    html_body = _build_html(meta, youtube_url, len(scene_paths))

    # 메시지 조립
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = GMAIL_TO

    alt = MIMEMultipart("alternative")
    plain = f"{TICKER} 주간 분석 {date}\n참고지수: {bi}점 ({signal})\n{youtube_url or ''}"
    alt.attach(MIMEText(plain, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    # 씬 이미지 인라인 첨부
    for i, path in scene_paths:
        with open(path, "rb") as f:
            img = MIMEImage(f.read(), _subtype="png")
        img.add_header("Content-ID", f"<scene_{i:02d}>")
        img.add_header("Content-Disposition", "inline", filename=path.name)
        msg.attach(img)

    # SMTP 발송
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)

    return True


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    report_dir = find_latest_report()
    if not report_dir:
        print("⚠ weekly-report 디렉토리 없음", file=sys.stderr)
        sys.exit(0)

    meta       = load_meta(report_dir)
    script_txt = ""
    script_file = report_dir / "script.txt"
    if script_file.exists():
        script_txt = script_file.read_text(encoding="utf-8")

    print(f"\n📤 GWS 게시 시작 — {meta.get('generated_at', '?')}")

    youtube_url = None

    # ── 1. YouTube 업로드 ────────────────────────────────────────────────────
    if GWS_YOUTUBE_TOKEN:
        try:
            print("  🎬 YouTube 업로드 중...")
            youtube_url = upload_to_youtube(report_dir, meta, script_txt)
            if youtube_url:
                print(f"  ✅ YouTube: {youtube_url}")
            else:
                print("  ⚠ YouTube 업로드 완료됐으나 ID 없음", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ YouTube 실패: {e}", file=sys.stderr)
    else:
        print("  [SKIP] YouTube: GWS_YOUTUBE_TOKEN 없음")

    # ── 2. Google Sheets 기록 ────────────────────────────────────────────────
    if GWS_SA_CREDENTIALS and GOOGLE_SHEET_ID:
        try:
            print("  📊 Sheets 기록 중...")
            log_to_sheets(meta, youtube_url)
            print("  ✅ Sheets 기록 완료")
        except Exception as e:
            print(f"  ⚠ Sheets 실패: {e}", file=sys.stderr)
    else:
        missing = []
        if not GWS_SA_CREDENTIALS:
            missing.append("GWS_SA_CREDENTIALS")
        if not GOOGLE_SHEET_ID:
            missing.append("GOOGLE_SHEET_ID")
        print(f"  [SKIP] Sheets: {', '.join(missing)} 없음")

    # ── 3. Gmail 다이제스트 ──────────────────────────────────────────────────
    if GMAIL_USER and GMAIL_APP_PASSWORD and GMAIL_TO:
        try:
            print(f"  📧 Gmail 발송 중 → {GMAIL_TO}")
            send_gmail_digest(report_dir, meta, youtube_url)
            print(f"  ✅ Gmail 발송 완료")
        except Exception as e:
            print(f"  ⚠ Gmail 실패: {e}", file=sys.stderr)
    else:
        missing = [s for s, v in [
            ("GMAIL_USER", GMAIL_USER),
            ("GMAIL_APP_PASSWORD", GMAIL_APP_PASSWORD),
            ("GMAIL_TO", GMAIL_TO),
        ] if not v]
        print(f"  [SKIP] Gmail: {', '.join(missing)} 없음")

    print("\n✅ GWS 게시 완료\n")


if __name__ == "__main__":
    main()
