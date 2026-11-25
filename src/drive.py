"""구글 드라이브 업로드 (승규님 계정 OAuth, drive.file 권한 = 이 앱이 만든 파일만 접근)."""
from __future__ import annotations

import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER = "application/vnd.google-apps.folder"
ROOT_NAME = "광고탐정승규_소재보관함"


class Drive:
    def __init__(self):
        env = {k: (os.environ.get(k) or "").strip() for k in
               ["GOOGLE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]}
        missing = [k for k, v in env.items() if not v]
        if missing:
            raise RuntimeError(f"GitHub Secrets 비어 있음: {', '.join(missing)}")
        creds = Credentials(
            None,
            refresh_token=env["GOOGLE_REFRESH_TOKEN"],
            client_id=env["GOOGLE_CLIENT_ID"],
            client_secret=env["GOOGLE_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._cache: dict[tuple, str] = {}
        self.root = self.folder(ROOT_NAME, None)

    def folder(self, name: str, parent: str | None) -> str:
        key = (name, parent)
        if key in self._cache:
            return self._cache[key]
        safe = name.replace("'", "\\'")
        q = f"name = '{safe}' and mimeType = '{FOLDER}' and trashed = false"
        q += f" and '{parent}' in parents" if parent else " and 'root' in parents"
        res = self.svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        if res:
            fid = res[0]["id"]
        else:
            meta = {"name": name, "mimeType": FOLDER}
            if parent:
                meta["parents"] = [parent]
            fid = self.svc.files().create(body=meta, fields="id").execute()["id"]
        self._cache[key] = fid
        return fid

    def upload(self, path: str, name: str, brand: str, month: str) -> str:
        parent = self.folder(month, self.folder(brand, self.root))
        media = MediaFileUpload(path, resumable=True)
        f = self.svc.files().create(body={"name": name, "parents": [parent]},
                                    media_body=media, fields="id").execute()
        return f["id"]

    def trash(self, file_id: str):
        self.svc.files().update(fileId=file_id, body={"trashed": True}).execute()
