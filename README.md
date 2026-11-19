# 🕵️ 광고 탐정 승규 (広告探偵スンギュ)

일본 경쟁사의 메타 광고를 매일 자동으로 수사하는 툴입니다.

- 메타 광고 라이브러리(JP)에서 경쟁사 광고를 매일 수집하고, 게재 기간을 추적합니다.
- 신규로 발견한 소재(이미지·영상)는 바로 **승규님 구글 드라이브**에 저장합니다.
- 오래 게재된 소재는 **Claude가 분석**합니다: 포맷, 첫 3초 훅, 소구점, A/B/C 등급, 셀로라바이 적용안, 약기법 리스크.
- 대시보드(GitHub Pages)에서 필터링하고, 영상을 바로 재생할 수 있습니다.

## 처음 한 번만 하는 설정

### 1. 경쟁사 등록
`config.yaml`의 `competitors`에 브랜드를 추가하고, `celoraby.products`에 제품과 소구점을 입력합니다.

### 2. 구글 드라이브 연결 (승규님 계정)
1. [Google Cloud Console](https://console.cloud.google.com/)에서 새 프로젝트를 만듭니다.
2. **API 및 서비스 → 라이브러리**에서 "Google Drive API"를 사용 설정합니다.
3. **OAuth 동의 화면**에서 외부 유형을 선택하고 앱 이름을 "광고 탐정 승규"로 만듭니다. 그다음 **게시 상태를 "프로덕션"으로 변경**합니다. 테스트 상태로 두면 7일마다 승인이 풀립니다.
4. **사용자 인증 정보 → OAuth 클라이언트 ID**에서 유형을 "데스크톱 앱"으로 만들고 JSON을 다운로드합니다. 파일 이름을 `client_secret.json`으로 바꿉니다.
5. PC에서 아래를 실행합니다. 브라우저가 열리면 승인하세요. "확인되지 않은 앱" 경고가 나오면 고급 → 이동을 누르면 됩니다.
   ```
   pip install google-auth-oauthlib
   python auth_setup.py
   ```
6. 화면에 나온 3개 값을 다음 단계의 Secrets에 등록합니다.

> 드라이브 폴더 `광고탐정승규_소재보관함`은 첫 실행 때 자동으로 생성됩니다. 생성된 뒤 팀원에게 이 폴더를 공유하면 팀원도 대시보드에서 영상을 재생할 수 있습니다.

### 3. GitHub Secrets 등록
저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 등록합니다.

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | [Claude Console](https://console.anthropic.com/)에서 발급한 API 키 |
| `GOOGLE_CLIENT_ID` | auth_setup.py 결과 |
| `GOOGLE_CLIENT_SECRET` | auth_setup.py 결과 |
| `GOOGLE_REFRESH_TOKEN` | auth_setup.py 결과 |

### 4. 대시보드 켜기
**Settings → Pages**에서 Source를 "Deploy from a branch"로, Branch를 `main`, 폴더를 `/docs`로 지정합니다.

### 5. 첫 실행
**Actions → 광고 탐정 승규 - 매일 수사 → Run workflow**를 누릅니다. 그 뒤로는 매일 오전 8시 37분(한국 시간)에 자동으로 실행됩니다.

## 참고
- 수집 결과가 0건이면 Actions 로그에 ⚠가 표시됩니다. 메타가 차단했거나 page_id/keyword가 틀렸을 수 있습니다.
- AI 분석은 `analysis.min_run_days`(기본 14일) 이상 게재된 소재만, 하루 최대 30개까지 합니다. 비용을 줄이기 위해서입니다.
- 내려받은 경쟁사 소재는 사내 레퍼런스로만 쓰고, 그대로 재사용하지 마세요.
