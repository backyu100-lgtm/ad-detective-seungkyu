"""🕵️ 광고 탐정 승규 — 매일 실행: 수집 → 소재 저장 → AI 분석 → 대시보드 데이터 생성."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent / "src"))
import store  # noqa: E402
from scraper import scrape_competitor  # noqa: E402
from media import download, make_previews  # noqa: E402

JST = timezone(timedelta(hours=9))


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    today = datetime.now(JST).date().isoformat()
    month = today[:7]
    db = store.load()
    log = {"date": today, "brands": {}}

    drive = None
    if os.environ.get("GOOGLE_REFRESH_TOKEN"):
        from drive import Drive
        drive = Drive()
    else:
        print("⚠ 드라이브 키 없음 → 소재 업로드는 건너뜀")

    # 1) 수집
    for comp in cfg["competitors"]:
        name = comp["name"]
        print(f"🔎 {name} 수사 중...")
        try:
            ads = scrape_competitor(comp, cfg.get("country", "JP"),
                                    cfg["scrape"]["max_scrolls"], cfg["scrape"]["scroll_wait_sec"])
        except Exception:
            traceback.print_exc()
            ads = []
        new = store.merge(db, name, ads, today)
        log["brands"][name] = {"found": len(ads), "new": len(new)}
        print(f"   광고 {len(ads)}개 / 신규 {len(new)}개")
        if not ads:
            print("   ⚠ 0건 — 차단됐거나 page_id/keyword 확인 필요")

        # 2) 신규 소재는 링크가 만료되기 전에 바로 저장
        for rec in new:
            media = rec.pop("_media", [])
            with tempfile.TemporaryDirectory() as tmp:
                for i, m in enumerate(media[:5]):
                    ext = "mp4" if m["type"] == "video" else "jpg"
                    path = Path(tmp) / f"{rec['id']}_{i}.{ext}"
                    if not download(m["url"], path):
                        if m.get("preview") and download(m["preview"], path.with_suffix(".jpg")):
                            path, m = path.with_suffix(".jpg"), {"type": "image"}
                        else:
                            continue
                    if not rec.get("thumb"):
                        pv = make_previews(rec["id"], path, m["type"])
                        rec["thumb"], rec["frames"] = pv["thumb"], pv["frames"]
                        if pv.get("duration"):
                            rec["duration"] = pv["duration"]
                    if drive:
                        try:
                            fname = f"{rec['id']}_{rec.get('start_date') or today}_{i}.{path.suffix[1:]}"
                            fid = drive.upload(str(path), fname, name, month)
                            rec["files"].append({"id": fid, "type": m["type"]})
                        except Exception as e:
                            print(f"  ! 드라이브 업로드 실패: {e}")
            rec["media_type"] = media[0]["type"] if media else "none"
            rec["media_count"] = len(media)
        store.save(db)

    # 3) 장수 소재 AI 분석
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        from analyze import analyze
        client = anthropic.Anthropic()
        todo = [r for r in db.values()
                if not r.get("analysis") and store.run_days(r, today) >= cfg["analysis"]["min_run_days"]]
        todo.sort(key=lambda r: -store.run_days(r, today))
        for rec in todo[: cfg["analysis"]["max_per_run"]]:
            try:
                res = analyze(rec, store.run_days(rec, today), cfg, client)
                if res:
                    rec["analysis"] = res
                    rec["analyzed_on"] = today
                    print(f"🧠 분석 완료 {rec['brand']} {rec['id']} → {res.get('grade')}")
            except Exception as e:
                print(f"  ! 분석 실패 {rec['id']}: {e}")
        store.save(db)
    else:
        print("⚠ ANTHROPIC_API_KEY 없음 → AI 분석 건너뜀")

    # 4) 대시보드 데이터
    export(db, cfg, today, log)


def export(db: dict, cfg: dict, today: str, log: dict):
    win = cfg["report"]["winning_days"]
    rows = []
    for r in db.values():
        d = store.run_days(r, today)
        rows.append({k: r.get(k) for k in [
            "id", "brand", "page_name", "start_date", "end_date", "first_seen", "last_seen",
            "is_active", "partner", "collation_count", "body", "title", "cta", "ad_url",
            "thumb", "files", "media_type", "duration", "analysis", "platforms"]} | {"run_days": d})
    week_ago = (datetime.fromisoformat(today) - timedelta(days=7)).date().isoformat()
    summary = {
        "new_today": sum(1 for r in rows if r["first_seen"] == today),
        "winning": sum(1 for r in rows if r["is_active"] and r["run_days"] >= win),
        "ended_week": sum(1 for r in rows if not r["is_active"] and (r.get("end_date") or "") >= week_ago),
        "total": len(rows),
    }
    out = {"updated": today, "winning_days": win, "summary": summary, "log": log, "ads": rows}
    Path("docs/data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"📋 오늘의 수사 보고서: {summary}")


if __name__ == "__main__":
    main()
