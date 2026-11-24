"""🕵️ 광고 탐정 승규 — 매일 실행: 수집 → 소재 저장 → AI(Gemini) 분석 → 대시보드 데이터 생성.

수집 대상은 두 가지:
  - watch  : 집중 감시 브랜드 → 신규 소재를 발견 즉시 전부 저장
  - sweeps : 키워드 발굴(일본 스킨케어 광고 전체) → 썸네일만 저장, 일정 일수 이상 살아남은 소재만 원본 저장
광고가 게재 중이면 매일 새 다운로드 링크가 들어오므로, '살아남은 뒤'에 받아도 놓치지 않습니다.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent / "src"))
import store  # noqa: E402
import vault  # noqa: E402
from scraper import scrape_competitor  # noqa: E402
from media import download, make_previews, save_thumb  # noqa: E402

JST = timezone(timedelta(hours=9))


def targets(cfg: dict):
    for c in cfg.get("competitors") or []:
        yield c, cfg["scrape"]["max_scrolls"]
    for kw in cfg.get("sweeps", {}).get("keywords") or []:
        yield {"name": f"🔎 {kw}", "keyword": kw, "sweep": True}, cfg["sweeps"].get("max_scrolls", 40)


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    today = datetime.now(JST).date().isoformat()
    month = today[:7]
    db = store.load()
    log = {"date": today, "brands": {}, "sweeps": {}}

    drive = None
    if os.environ.get("GOOGLE_REFRESH_TOKEN"):
        from drive import Drive
        try:
            drive = Drive()
            print("✅ 구글 드라이브 연결 성공")
        except Exception as e:
            print(f"❌ 구글 드라이브 연결 실패 → 원본 업로드 없이 계속 진행합니다: {e}")
    else:
        print("⚠ 드라이브 키 없음 → 원본 업로드는 건너뜀")

    # 1) 수집
    for comp, scrolls in targets(cfg):
        print(f"🔎 {comp['name']} 수사 중...")
        try:
            ads = scrape_competitor(comp, cfg.get("country", "JP"), scrolls, cfg["scrape"]["scroll_wait_sec"])
        except Exception:
            traceback.print_exc()
            ads = []
        new = store.merge(db, None if comp.get("sweep") else comp["name"], ads, today)
        pages = getattr(scrape_competitor, "pages_seen", {})
        entry = {"found": len(ads), "new": len(new), "pages_seen": pages}
        (log["sweeps"] if comp.get("sweep") else log["brands"])[comp["name"]] = entry
        print(f"   광고 {len(ads)}개 / 신규 {len(new)}개")
        if not ads:
            print("   ⚠ 0건 — 차단됐거나 검색어/페이지명 확인 필요")
        for rec in new:                      # 썸네일은 발견 즉시 (가벼움)
            rec["thumb"] = save_thumb(rec["id"], rec.get("_media") or [])
            media = rec.get("_media") or []
            rec["media_type"] = media[0]["type"] if media else "none"
            rec["media_count"] = len(media)
        time.sleep(3)
    store.expire_stale(db, today)

    # 2) 원본 소재 저장 (감시 브랜드 = 전부 / 키워드 발굴 = N일 이상 살아남은 것만)
    min_days = cfg.get("sweeps", {}).get("download_min_days", 14)
    cap = cfg.get("sweeps", {}).get("max_downloads_per_run", 300)
    queue = [r for r in db.values() if r.get("_media") and not r.get("files")
             and (r.get("source") == "watch" or store.run_days(r, today) >= min_days)]
    queue.sort(key=lambda r: (r.get("source") != "watch", -store.run_days(r, today)))
    print(f"💾 원본 저장 대상 {len(queue)}개 (이번 실행 최대 {cap}개)")
    for rec in queue[:cap]:
        save_media(rec, rec["_media"], drive, month, today)
    store.save_clean(db)

    # 3) 장수 소재 AI 분석
    provider = cfg["analysis"].get("provider", "gemini")
    key = "ANTHROPIC_API_KEY" if provider == "claude" else "GEMINI_API_KEY"
    if os.environ.get(key):
        from analyze import analyze
        todo = [r for r in db.values() if not r.get("analysis") and r.get("frames")
                and store.run_days(r, today) >= cfg["analysis"]["min_run_days"]]
        todo.sort(key=lambda r: (r.get("source") != "watch", -store.run_days(r, today)))
        for rec in todo[: cfg["analysis"]["max_per_run"]]:
            try:
                res = analyze(rec, store.run_days(rec, today), cfg)
                if res:
                    rec["analysis"] = res
                    rec["analyzed_on"] = today
                    print(f"🧠 분석 완료 {rec['brand']} {rec['id']} → {res.get('grade')}")
            except Exception as e:
                print(f"  ! 분석 실패 {rec['id']}: {e}")
            time.sleep(5)          # 무료 등급 속도 제한 여유
        store.save(db)
    else:
        print(f"⚠ {key} 없음 → AI 분석 건너뜀")

    # 3-2) Claude 심층 분석: 위닝 소재 상위 N개만 (Claude 토큰 절약)
    deep_n = cfg["analysis"].get("claude_deep_per_run", 10)
    if provider != "claude" and deep_n and os.environ.get("ANTHROPIC_API_KEY"):
        from analyze import analyze
        win = cfg["report"]["winning_days"]
        todo = [r for r in db.values() if not r.get("analysis_claude") and r.get("frames")
                and store.run_days(r, today) >= win]
        todo.sort(key=lambda r: (r.get("source") != "watch", -store.run_days(r, today)))
        for rec in todo[:deep_n]:
            try:
                res = analyze(rec, store.run_days(rec, today), cfg, provider="claude")
                if res:
                    rec["analysis_claude"] = res
                    print(f"🧠 Claude 심층 분석 {rec['brand']} {rec['id']} → {res.get('grade')}")
            except Exception as e:
                print(f"  ! Claude 분석 실패 {rec['id']}: {e}")
        store.save(db)

    # 4) 대시보드 데이터
    export(db, cfg, today, log)


def save_media(rec: dict, media: list[dict], drive, month: str, today: str):
    with tempfile.TemporaryDirectory() as tmp:
        for i, m in enumerate(media[:5]):
            ext = "mp4" if m["type"] == "video" else "jpg"
            path = Path(tmp) / f"{rec['id']}_{i}.{ext}"
            kind = m["type"]
            if not download(m["url"], path):
                if m.get("preview") and download(m["preview"], path.with_suffix(".jpg")):
                    path, kind = path.with_suffix(".jpg"), "image"
                else:
                    continue
            if not rec.get("frames"):
                pv = make_previews(rec["id"], path, kind)
                rec["frames"] = pv["frames"]
                rec["thumb"] = rec.get("thumb") or pv["thumb"]
                if pv.get("duration"):
                    rec["duration"] = pv["duration"]
            if drive:
                try:
                    folder = rec["brand"].replace("/", "_")[:60]
                    fname = f"{rec['id']}_{rec.get('start_date') or today}_{i}.{path.suffix[1:]}"
                    fid = drive.upload(str(path), fname, folder, month)
                    rec["files"].append({"id": fid, "type": kind})
                except Exception as e:
                    print(f"  ! 드라이브 업로드 실패: {e}")


def export(db: dict, cfg: dict, today: str, log: dict):
    win = cfg["report"]["winning_days"]
    rows = []
    for r in db.values():
        d = store.run_days(r, today)
        rows.append({k: r.get(k) for k in [
            "id", "brand", "source", "keywords", "page_name", "start_date", "end_date", "first_seen",
            "last_seen", "is_active", "partner", "collation_count", "body", "title", "cta", "ad_url",
            "thumb", "files", "media_type", "duration", "analysis", "analysis_claude", "platforms"]} | {"run_days": d})
    week_ago = (datetime.fromisoformat(today) - timedelta(days=7)).date().isoformat()
    summary = {
        "new_today": sum(1 for r in rows if r["first_seen"] == today),
        "winning": sum(1 for r in rows if r["is_active"] and r["run_days"] >= win),
        "ended_week": sum(1 for r in rows if not r["is_active"] and (r.get("end_date") or "") >= week_ago),
        "total": len(rows),
        "brands": len({r["brand"] for r in rows}),
    }
    out = {"updated": today, "winning_days": win, "summary": summary, "log": log, "ads": rows}
    pw = vault.password()
    if pw:   # 대시보드 데이터는 비밀번호로 암호화해서 공개
        Path("docs/data.enc.json").write_text(vault.encrypt(out, pw), encoding="utf-8")
        Path("docs/data.json").unlink(missing_ok=True)
    else:
        print("⚠ DASHBOARD_PASSWORD 없음 → 대시보드 데이터가 암호화되지 않습니다")
        Path("docs/data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"📋 오늘의 수사 보고서: {summary}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("❌ 수사 중 오류 — 위 로그를 확인하세요")
        sys.exit(1)
