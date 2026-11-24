# 🕵️ 광고 탐정 승규 (広告探偵スンギュ)

일본 경쟁사의 메타 광고를 매일 자동으로 수사하는 툴입니다.

- 메타 광고 라이브러리(JP)에서 광고를 매일 수집하고, 게재 기간을 추적합니다.
  - ⭐ **집중 감시 브랜드**(`competitors`): 신규 소재를 발견하는 즉시 원본을 저장합니다.
  - 🔎 **키워드 발굴**(`sweeps`): 美容液·毛穴·PDRN 같은 검색어로 일본에서 광고하는 **모든 광고주(수백 개 브랜드)**를 자동으로 수집합니다. 썸네일은 전부 저장하고, 원본은 14일 이상 살아남은 소재만 저장합니다. 효율 없는 소재까지 쌓이지 않게 하기 위해서입니다.
- 원본 소재(이미지·영상)는 **승규님 구글 드라이브**에 저장됩니다.
- 오래 게재된 소재는 **AI(기본 Gemini)가 분석**합니다: 포맷, 첫 3초 훅, 소구점, A/B/C 등급, 셀로라바이 적용안, 약기법 리스크.
- 대시보드(GitHub Pages)에서 필터링하고, 영상을 바로 재생할 수 있습니다.

## 처음 한 번만 하는 설정

### 1. 경쟁사·키워드 등록
`config.yaml`의 `competitors`(집중 감시)와 `sweeps.keywords`(발굴 검색어)를 수정하고, `celoraby.products`에 제품과 소구점을 입력합니다.

### 2. 구글 드라이브 연결 (승규님 계정, 브라우저만으로 가능)
1. [Google Cloud Console](https://console.cloud.google.com/)에서 새 프로젝트 `ad-detective`를 만듭니다.
2. **API 및 서비스 → 라이브러리**에서 "Google Drive API"를 검색해 **사용**을 누릅니다.
3. **Google 인증 플랫폼(OAuth 동의 화면) → 시작하기**로 들어가 앱 이름(광고 탐정 승규)과 이메일을 입력하고, 대상은 **외부**를 고릅니다. 만든 뒤 **대상(Audience) → 앱 게시**로 프로덕션 상태로 바꿉니다. 테스트 상태로 두면 7일마다 승인이 풀립니다.
4. **클라이언트 → 클라이언트 만들기**에서 유형을 **웹 애플리케이션**으로 고르고, 승인된 리디렉션 URI에 `https://developers.google.com/oauthplayground`를 추가한 뒤 만듭니다. **클라이언트 ID와 보안 비밀번호**를 복사해둡니다.
5. [OAuth Playground](https://developers.google.com/oauthplayground)를 엽니다.
   - 오른쪽 위 ⚙️에서 **Use your own OAuth credentials**를 체크하고 4번의 ID와 비밀번호를 입력합니다.
   - 왼쪽 아래 입력칸에 `https://www.googleapis.com/auth/drive.file`를 입력하고 **Authorize APIs**를 누릅니다. 승규님 계정으로 승인하세요. "확인되지 않은 앱" 경고가 나오면 고급 → 이동을 누르면 됩니다.
   - **Exchange authorization code for tokens**를 누르면 나오는 **Refresh token**을 복사합니다.

> 드라이브 폴더 `광고탐정승규_소재보관함`은 첫 실행 때 자동으로 생성됩니다. 생성된 뒤 팀원에게 이 폴더를 공유하면 팀원도 대시보드에서 영상을 재생할 수 있습니다.
> (PC에 파이썬이 있으면 `auth_setup.py`로도 토큰을 받을 수 있습니다. 이 경우 4번의 유형은 "데스크톱 앱"으로 만듭니다.)

### 3. GitHub Secrets 등록
저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 등록합니다. 키 값은 채팅에 붙여넣지 말고 여기에만 입력하세요.

| 이름 | 값 |
|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey)에서 발급한 키 (무료 등급 있음) |
| `GOOGLE_CLIENT_ID` | 4번의 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 4번의 보안 비밀번호 |
| `GOOGLE_REFRESH_TOKEN` | 5번의 Refresh token |
| `ANTHROPIC_API_KEY` | (선택) Claude로 분석할 때만. `config.yaml`의 `provider: claude` |

### 4. 대시보드 켜기
**Settings → Pages**에서 Source를 "Deploy from a branch"로, Branch를 `main`, 폴더를 `/docs`로 지정합니다.

### 5. 첫 실행
**Actions → 광고 탐정 승규 - 매일 수사 → Run workflow**를 누릅니다. 그 뒤로는 매일 오전 8시 37분(한국 시간)에 자동으로 실행됩니다.

## 참고
- 수집 결과가 0건이면 Actions 로그에 ⚠가 표시됩니다. 메타가 차단했거나 page_id/keyword가 틀렸을 수 있습니다.
- AI 분석은 `analysis.min_run_days`(기본 14일) 이상 게재된 소재만, 하루 최대 30개까지 합니다. 비용을 줄이기 위해서입니다.
- 내려받은 경쟁사 소재는 사내 레퍼런스로만 쓰고, 그대로 재사용하지 마세요.
