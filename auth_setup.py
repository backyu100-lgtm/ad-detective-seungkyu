"""최초 1회만: 승규님 PC에서 실행해 구글 드라이브 승인 토큰을 받는 스크립트.

1) 구글 클라우드 콘솔에서 받은 OAuth 클라이언트 JSON을 이 폴더에 client_secret.json 으로 저장
2) pip install google-auth-oauthlib
3) python auth_setup.py  → 브라우저가 열리면 승규님 계정으로 승인
4) 화면에 나온 세 값을 GitHub Secrets에 등록 (README 참고)
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\n=== 아래 세 값을 GitHub Secrets에 등록하세요 ===")
print("GOOGLE_CLIENT_ID     =", creds.client_id)
print("GOOGLE_CLIENT_SECRET =", creds.client_secret)
print("GOOGLE_REFRESH_TOKEN =", creds.refresh_token)
