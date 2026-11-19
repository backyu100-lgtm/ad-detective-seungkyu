"""수집 기록 저장소 (data/ads.json) — 처음 본 날 / 마지막 본 날을 쌓아서 게재 기간을 계산."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

PATH = Path("data/ads.json")
KEEP_FROM_SCRAPE = ["page_id", "page_name", "start_date", "end_date", "is_active", "platforms",
                    "collation_count", "collation_id", "body", "title", "cta", "link_url",
                    "partner", "display_format", "ad_url", "brand"]


def load() -> dict:
    if PATH.exists():
        return json.loads(PATH.read_text(encoding="utf-8"))
    return {}


def save(db: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def merge(db: dict, brand: str, ads: list[dict], today: str) -> list[dict]:
    """오늘 수집 결과를 합친다. 반환값 = 오늘 처음 발견한 광고 목록."""
    new = []
    seen_ids = set()
    for ad in ads:
        seen_ids.add(ad["id"])
        rec = db.get(ad["id"])
        if rec is None:
            rec = {"id": ad["id"], "first_seen": today, "files": [], "analysis": None}
            db[ad["id"]] = rec
            new.append(rec)
            rec["_media"] = ad["media"]          # 다운로드용(저장 전 제거)
        for k in KEEP_FROM_SCRAPE:
            if ad.get(k) not in (None, "", []):
                rec[k] = ad[k]
        rec["is_active"] = ad["is_active"]
        rec["last_seen"] = today

    # 수집이 정상(1건 이상)일 때만: 이 브랜드인데 오늘 안 보인 광고 → 종료 처리
    if ads:
        for rec in db.values():
            if rec.get("brand") == brand and rec["id"] not in seen_ids and rec.get("is_active"):
                rec["is_active"] = False
                rec["end_date"] = rec.get("end_date") or rec.get("last_seen")
    return new


def run_days(rec: dict, today: str) -> int:
    start = rec.get("start_date") or rec.get("first_seen")
    end = today if rec.get("is_active") else (rec.get("end_date") or rec.get("last_seen") or today)
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except Exception:
        return 0
