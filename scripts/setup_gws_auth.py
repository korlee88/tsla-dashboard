"""
GWS OAuth2 초기 인증 설정 스크립트 (로컬 1회 실행 전용)

사전 준비:
  1. console.cloud.google.com → 프로젝트 선택 (또는 새로 생성)
  2. API 및 서비스 → 라이브러리에서 아래 API 활성화:
       - YouTube Data API v3
       - Google Sheets API  ← 서비스 계정으로 별도 처리
       - Gmail API           ← SMTP App Password로 별도 처리 (이 스크립트 불필요)
  3. 사용자 인증 정보 → OAuth 동의 화면 → 외부 → 테스트 사용자에 본인 계정 추가
     (앱을 '프로덕션' 으로 게시하지 않으면 7일 후 토큰 만료 — 테스트 사용자로 유지)
  4. 사용자 인증 정보 → OAuth 2.0 클라이언트 ID → 유형: 데스크톱 앱
     → credentials.json 다운로드 후 이 스크립트와 같은 폴더에 저장

  [Sheets 별도 설정]
  5. 사용자 인증 정보 → 서비스 계정 → 새 서비스 계정 생성
     → JSON 키 다운로드 → 내용 전체를 GitHub Secret GWS_SA_CREDENTIALS 에 붙여넣기
  6. Google Sheets 문서를 열고, 위 서비스 계정 이메일(xxx@xxx.iam.gserviceaccount.com)로
     공유 (편집자 권한)
  7. Sheets URL에서 /d/ 뒤 ID 복사 → GitHub Secret GOOGLE_SHEET_ID 에 붙여넣기

  [Gmail 별도 설정]
  8. Gmail → Google 계정 보안 → 2단계 인증 활성화
  9. 앱 비밀번호 생성 (앱: 메일, 기기: 기타) → 16자리 비밀번호
  10. GitHub Secret GMAIL_USER(이메일), GMAIL_APP_PASSWORD(비밀번호), GMAIL_TO(수신자) 등록

실행:
  pip install google-auth-oauthlib
  python scripts/setup_gws_auth.py              # credentials.json이 현재 폴더에 있을 때
  python scripts/setup_gws_auth.py path/to/credentials.json  # 경로 지정

결과:
  token.json 파일 생성 → 파일 내용 전체를 GitHub Secret GWS_YOUTUBE_TOKEN 에 붙여넣기
"""

import json
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]


def main():
    credentials_path = sys.argv[1] if len(sys.argv) > 1 else "credentials.json"

    if not Path(credentials_path).exists():
        print(f"❌ {credentials_path} 파일이 없습니다.")
        print("   Google Cloud Console에서 OAuth 2.0 클라이언트 ID를 생성하고")
        print("   credentials.json을 다운로드하세요.")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ google-auth-oauthlib 패키지 필요:")
        print("   pip install google-auth-oauthlib")
        sys.exit(1)

    print("🔐 YouTube OAuth2 인증 플로우 시작...")
    print("   브라우저가 열리면 Google 계정으로 로그인 후 권한을 허용하세요.\n")

    flow  = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri":     "https://oauth2.googleapis.com/token",
        "scopes":        list(creds.scopes),
    }

    token_path = Path("token.json")
    token_path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")

    print(f"\n✅ token.json 생성 완료!")
    print("\n📋 다음 단계:")
    print("   1. 아래 내용을 복사하세요 (또는 token.json 파일 전체 내용):")
    print("-" * 60)
    print(json.dumps(token_data, indent=2, ensure_ascii=False))
    print("-" * 60)
    print("   2. GitHub 저장소 → Settings → Secrets → Actions")
    print("      → New repository secret")
    print("      이름: GWS_YOUTUBE_TOKEN")
    print("      값: 위 JSON 전체 붙여넣기")
    print("\n⚠️  token.json은 민감 정보입니다. git에 커밋하지 마세요!")
    print("   (이미 .gitignore에 token.json이 있는지 확인하세요)")


if __name__ == "__main__":
    main()
