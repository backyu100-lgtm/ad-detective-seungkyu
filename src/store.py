"""수집 기록 저장소 (data/ads.json) — 처음 본 날 / 마지막 본 날을 쌓아서 게재 기간을 계산."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import vault

PATH = Path("data/ads.json")          # 비밀번호 미설정 시
ENC_PATH = Path("data/ads.enc.json")   # 비밀번호 설정 시 (암호화)
KEEP_FROM_SCRAPE = ["page_id", "page_name", "start_date", "end_date", "is_active", "platforms",
                    "collation_count", "collation_id", "body", "title", "cta", "link_url",
                    "display_format", "ad_url", "link_caption"]
RANK = {"watch": 3, "brand": 2, "sweep": 1}
STALE_DAYS = 3   # 키워드 발굴 광고가 며칠 안 보이면 종료로 추정


def load() -> dict:
    pw = vault.password()
    if pw and ENC_PATH.exists():
        return vault.decrypt(ENC_PATH.read_text(encoding="utf-8"), pw)
    if PATH.exists():
        return json.loads(PATH.read_text(encoding="utf-8"))
    return {}


def save(db: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    pw = vault.password()
    if pw:
        ENC_PATH.write_text(vault.encrypt(db, pw), encoding="utf-8")
        PATH.unlink(missing_ok=True)       # 평문 기록은 지움
    else:
        PATH.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def merge(db: dict, brand: str, ads: list[dict], today: str) -> list[dict]:
    """오늘 수집 결과를 합친다. 반환값 = 오늘 처음 발견한 광고 목록."""
    new = []
    seen_ids = set()
    for ad in ads:
        seen_ids.add(ad["id"])
        rec = db.get(ad["id"])
        if rec is None:
            rec = {"id": ad["id"], "first_seen": today, "files": [], "analysis": None,
                   "keywords": [], "brand": ad["brand"], "source": ad["source"]}
            db[ad["id"]] = rec
            new.append(rec)
        # 감시 브랜드(watch)로 잡힌 적 있으면 그 이름이 우선
        if RANK.get(ad["source"], 0) >= RANK.get(rec.get("source"), 0):
            rec["brand"], rec["source"] = ad["brand"], ad["source"]
        rec["partner"], rec["accounts"] = ad.get("partner"), ad.get("accounts") or []
        rec["is_ja"], rec["has_text"] = ad.get("is_ja"), ad.get("has_text")
        if ad.get("keyword") and ad["keyword"] not in rec.setdefault("keywords", []):
            rec["keywords"].append(ad["keyword"])
        rec["_media"] = ad["media"]              # 오늘 받은 새 링크(만료 전), 저장 전 제거
        for k in KEEP_FROM_SCRAPE:
            if ad.get(k) not in (None, "", []):
                rec[k] = ad[k]
        rec["is_active"] = ad["is_active"]
        rec["last_seen"] = today

    # 감시 브랜드: 수집이 정상(1건 이상)일 때, 오늘 안 보인 광고 → 종료 처리
    if ads and brand is not None:
        for rec in db.values():
            if rec.get("source") in ("watch", "brand") and rec.get("brand") == brand \
                    and rec["id"] not in seen_ids and rec.get("is_active"):
                rec["is_active"] = False
                rec["end_date"] = rec.get("end_date") or rec.get("last_seen")
    return new


def expire_stale(db: dict, today: str):
    """키워드 발굴 광고는 검색 순위에서 밀려 안 보일 수 있으므로 며칠 연속 안 보이면 종료로 추정."""
    for rec in db.values():
        if rec.get("source") == "sweep" and rec.get("is_active") and rec.get("last_seen"):
            if (date.fromisoformat(today) - date.fromisoformat(rec["last_seen"])).days >= STALE_DAYS:
                rec["is_active"] = False
                rec["end_date"] = rec["last_seen"]


def save_clean(db: dict):
    for rec in db.values():
        rec.pop("_media", None)
    save(db)


def run_days(rec: dict, today: str) -> int:
    start = rec.get("start_date") or rec.get("first_seen")
    end = today if rec.get("is_active") else (rec.get("end_date") or rec.get("last_seen") or today)
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except Exception:
        return 0
