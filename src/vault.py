"""비밀번호 암호화 (공개 저장소에 올라가는 데이터를 승규님만 열 수 있게).

AES-256-GCM + PBKDF2-SHA256 — 브라우저 WebCrypto 로 그대로 복호화 가능한 형식.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 250_000
b64 = lambda b: base64.b64encode(b).decode()


def _key(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode())


def encrypt(obj, password: str) -> str:
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(password, salt)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    return json.dumps({"v": 1, "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)})


def decrypt(text: str, password: str):
    d = json.loads(text)
    pt = AESGCM(_key(password, base64.b64decode(d["salt"]))).decrypt(
        base64.b64decode(d["iv"]), base64.b64decode(d["ct"]), None)
    return json.loads(pt)


def password() -> str | None:
    return os.environ.get("DASHBOARD_PASSWORD") or None
