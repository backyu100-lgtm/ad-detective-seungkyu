"""🕵️ 광고 탐정 승규 — 수집 → 대시보드 먼저 갱신 → 원본 저장 → AI 분석 → 대시보드 최종 갱신.

실행 방법
  python main.py collect --shard 0 --shards 4   # 수집만 (GitHub에서 여러 대가 나눠서 동시에)
  python main.py process                        # 나눠 모은 결과를 합쳐 저장·분석·대시보드
  python main.py                                # 한 대에서 전부 (로컬 테스트용)

수집 대상
  ⭐ watch  : 집중 감시 브랜드 → 신규 소재 원본 즉시 저장
  📋 brand  : 일반 수집 브랜드 → 원본은 N일 이상 살아남은 소재만
  🔎 sweep  : 키워드 발굴     → 원본은 N일 이상 살아남은 소재만
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent / "src"))
import store  # noqa: E402
import vault  # noqa: E402
from media import download, make_previews, save_thumb  # noqa: E402

JST = timezone(timedelta(hours=9))
OUT = Path("out")


def load_cfg() -> dict:
    return yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))


def load_settings() -> dict:
    p = Path("docs/settings.json")
    s = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for k in ["watch", "brands", "keywords", "blocked_pages", "hidden"]:
        s.setdefault(k, [])
    s.setdefault("aliases", {})
    return s


def get_mode() -> str:
    return (os.environ.get("MODE") or "full").strip()


def targets(cfg: dict, st: dict, mode: str) -> list[tuple[dict, int]]:
    out = []
    for c in st["watch"]:
        c = {"page_id": "", "keyword": c.get("name"), "page_names": [c.get("name", "").lower()], **c, "tier": "watch"}
        out.append((c, cfg["scrape"]["max_scrolls"]))
    if mode == "watch":          # 빠른 수사: 집중 감시 브랜드만
        return out
    for c in st["brands"]:       # 📋 일반 수집 브랜드
        c = {"page_id": "", "keyword": c.get("name"), "page_names": [c.get("name", "").lower()], **c, "tier": "brand"}
        out.append((c, cfg["scrape"]["max_scrolls"]))
    for kw in st["keywords"]:
        out.append(({"name": f"🔎 {kw}", "keyword": kw, "sweep": True}, cfg["sweeps"].get("max_scrolls", 40)))
    return out


# ---------------------------------------------------------------- 1) 수집
def collect(shard: int = 0, shards: int = 1) -> list[dict]:
    """담당 몫의 대상을 수집해 out/shard_N.json 으로 저장 (DB 없이 동작)."""
    from scraper import Browser, scrape_competitor, DEBUG_PARTNER
    cfg, st, mode = load_cfg(), load_settings(), get_mode()
    mine = [t for i, t in enumerate(targets(cfg, st, mode)) if i % shards == shard]
    print(f"🕵️ 수집 담당 {shard + 1}/{shards}: {len(mine)}개 대상 ({'⚡ 빠른 수사' if mode == 'watch' else '전체 수사'})")
    results = []
    t0 = time.time()
    with Browser() as browser:
        for comp, scrolls in mine:
            t1 = time.time()
            try:
                ads = scrape_competitor(comp, cfg.get("country", "JP"), scrolls, cfg["scrape"]["scroll_wait_sec"],
                                        cfg.get("ad_language", "ja") or None, cfg.get("japanese_only", True), browser)
            except Exception:
                traceback.print_exc()
                ads = []
            pages = getattr(scrape_competitor, "pages_seen", {})
            print(f"🔎 {comp['name']}: 광고 {len(ads)}개 ({time.time() - t1:.0f}초)" + ("  ⚠ 0건" if not ads else ""))
            results.append({"comp": comp, "ads": ads, "pages": pages})
    print(f"⏱ 수집 {time.time() - t0:.0f}초")
    OUT.mkdir(exist_ok=True)
    (OUT / f"shard_{shard}.json").write_text(json.dumps({"results": results, "debug": DEBUG_PARTNER}, ensure_ascii=False),
                                             encoding="utf-8")
    return results


# ---------------------------------------------------------------- 정리 도구
def apply_blocks(db: dict, st: dict, drive, ja_only: bool = True):
    """🚫 차단한 광고주 + 일본어가 아닌 광고: 수집 기록·썸네일·프레임·드라이브 파일까지 삭제."""
    blocked = {b.lower() for b in st["blocked_pages"]}
    kana = re.compile(r"[぀-ヿ]")

    def not_ja(r):
        text = (r.get("body") or "") + (r.get("title") or "")
        return ja_only and r.get("source") != "watch" and text.strip() and not kana.search(text)

    gone = [r for r in db.values() if (r.get("page_name") or "").lower() in blocked or not_ja(r)]
    for rec in gone:
        for f in rec.get("files") or []:
            if drive:
                try:
                    drive.trash(f["id"])
                except Exception as e:
                    print(f"  ! 드라이브 삭제 실패 {f['id']}: {e}")
        for fr in rec.get("frames") or []:
            Path(fr).unlink(missing_ok=True)
        if rec.get("thumb"):
            (Path("docs/thumbs") / rec["thumb"]).unlink(missing_ok=True)
        del db[rec["id"]]
    if gone:
        print(f"🚫 차단 광고주·비일본어 소재 {len(gone)}개 삭제 (드라이브 휴지통으로 이동)")


def prune_frames(db: dict):
    """분석이 끝났고 이미 종료된 소재의 분석용 프레임은 지워서 저장소 용량을 아낀다."""
    n = 0
    for rec in db.values():
        if rec.get("analysis") and not rec.get("is_active") and rec.get("frames"):
            for fr in rec["frames"]:
                Path(fr).unlink(missing_ok=True)
            rec["frames"] = []
            n += 1
    if n:
        print(f"🧹 종료된 소재 프레임 정리 {n}개")


def publish(msg: str):
    """GitHub에서 실행 중이면 지금까지의 결과를 바로 올려 대시보드를 먼저 갱신."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    run = lambda *a: subprocess.run(list(a), capture_output=True, text=True)
    run("git", "config", "user.name", "ad-detective-bot")
    run("git", "config", "user.email", "actions@users.noreply.github.com")
    run("git", "add", "-A", "data", "docs")
    if run("git", "commit", "-m", msg).returncode != 0:
        return
    for _ in range(3):
        if run("git", "pull", "--rebase", "-X", "theirs", "origin", "main").returncode == 0 \
                and run("git", "push").returncode == 0:
            print(f"📤 {msg} — 대시보드 반영")
            return
        time.sleep(5)
    print("  ! 중간 업로드 실패 (마지막에 다시 시도)")


# ---------------------------------------------------------------- 2) 합치기·저장·분석
def process(results: list[dict] | None = None, debug: list | None = None):
    cfg, st, mode = load_cfg(), load_settings(), get_mode()
    today = datetime.now(JST).date().isoformat()
    month = today[:7]
    t0 = time.time()

    if results is None:      # 나눠서 모은 수집 결과 불러오기
        results, debug = [], []
        for f in sorted(OUT.glob("shard_*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            results += d["results"]
            debug += d.get("debug") or []
        print(f"📥 수집 결과 {len(results)}개 대상 불러옴")
    if not results:
        print("⚠ 수집 결과가 없어요 (수집 단계 확인 필요)")

    db = store.load()
    log = {"date": today, "brands": {}, "sweeps": {}, "keyword_hits": {}}
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

    ja_only = cfg.get("japanese_only", True)
    apply_blocks(db, st, drive, ja_only)

    # 합치기
    blocked = {b.lower() for b in st["blocked_pages"]}
    new_all = []
    for res in results:
        comp, ads = res["comp"], [a for a in res["ads"] if (a.get("page_name") or "").lower() not in blocked]
        new = store.merge(db, None if comp.get("sweep") else comp["name"], ads, today)
        new_all += new
        if comp.get("sweep"):
            log["keyword_hits"][comp["keyword"]] = len(ads)
        (log["sweeps"] if comp.get("sweep") else log["brands"])[comp["name"]] = \
            {"found": len(ads), "new": len(new), "pages_seen": res.get("pages") or {}}
    if mode != "watch" and results:
        store.expire_stale(db, today)
    if debug:
        Path("data/debug_partnership.json").write_text(json.dumps(debug[:30], ensure_ascii=False, indent=1), encoding="utf-8")

    # 오늘 받은 다운로드 링크는 따로 보관 (저장 파일엔 넣지 않음)
    media_map = {rid: rec.pop("_media") for rid, rec in db.items() if rec.get("_media")}
    for rec in new_all:
        m = media_map.get(rec["id"]) or []
        rec["media_type"] = m[0]["type"] if m else "none"
        rec["media_count"] = len(m)

    # 신규 썸네일 (동시에 8개씩)
    with ThreadPoolExecutor(8) as ex:
        thumbs = list(ex.map(lambda r: save_thumb(r["id"], media_map.get(r["id"]) or []), new_all))
    for rec, th in zip(new_all, thumbs):
        rec["thumb"] = th
    print(f"🖼 신규 {len(new_all)}개 썸네일 저장")

    from enrich import enrich
    enrich(db)
    store.save(db)
    export(db, cfg, today, log)
    publish(f"🕵️ 수사 보고서 {datetime.now(JST).strftime('%F %H:%M')} (수집)")
    print(f"⏱ 대시보드 갱신까지 {time.time() - t0:.0f}초")

    # 원본 저장 (집중 감시 = 전부 / 나머지 = N일 이상 살아남은 것만) — 동시에 4개씩
    min_days = cfg.get("sweeps", {}).get("download_min_days", 14)
    cap = cfg.get("sweeps", {}).get("max_downloads_per_run", 300)
    queue = [r for r in db.values() if r["id"] in media_map and not r.get("files")
             and (r.get("source") == "watch" or store.run_days(r, today) >= min_days)]
    queue.sort(key=lambda r: (r.get("source") != "watch", -store.run_days(r, today)))
    print(f"💾 원본 저장 대상 {len(queue)}개 (이번 실행 최대 {cap}개)")
    lock = threading.Lock()
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda r: save_media(r, media_map[r["id"]], drive, month, today, lock), queue[:cap]))
    enrich(db)
    store.save(db)

    analyze_all(db, cfg, today)
    prune_frames(db)
    enrich(db)
    store.save(db)
    export(db, cfg, today, log)
    print(f"⏱ 전체 처리 {time.time() - t0:.0f}초")


def analyze_all(db: dict, cfg: dict, today: str):
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
            time.sleep(2)          # 무료 등급 속도 제한 여유 (429면 analyze 안에서 재시도)
        store.save(db)
    else:
        print(f"⚠ {key} 없음 → AI 분석 건너뜀")

    # Claude 심층 분석: 위닝 소재 상위 N개만 (Claude 토큰 절약)
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


def save_media(rec: dict, media: list[dict], drive, month: str, today: str, lock: threading.Lock | None = None):
    lock = lock or threading.Lock()
    try:
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
                        with lock:          # 드라이브 업로드는 한 번에 하나씩
                            fid = drive.upload(str(path), fname, folder, month)
                        rec.setdefault("files", []).append({"id": fid, "type": kind})
                    except Exception as e:
                        print(f"  ! 드라이브 업로드 실패: {e}")
    except Exception as e:
        print(f"  ! 원본 저장 실패 {rec.get('id')}: {e}")


def export(db: dict, cfg: dict, today: str, log: dict):
    from enrich import guess_brands
    win = cfg["report"]["winning_days"]
    rows = []
    for r in db.values():
        if r.get("partner") and (r["partner"] or "").lower() == (r.get("page_name") or "").lower():
            r["partner"] = None          # 자기 자신이 파트너로 잡힌 예전 기록 정리
        d = store.run_days(r, today)
        rows.append({k: r.get(k) for k in [
            "id", "brand", "source", "keywords", "page_name", "start_date", "end_date", "first_seen",
            "last_seen", "is_active", "partner", "collation_count", "body", "title", "cta", "ad_url",
            "thumb", "files", "media_type", "media_count", "display_format", "duration", "accounts",
            "link_url", "link_caption", "channel", "kw", "cats", "dhash", "analysis", "analysis_claude", "platforms"]} | {"run_days": d})
    week_ago = (datetime.fromisoformat(today) - timedelta(days=7)).date().isoformat()
    summary = {
        "new_today": sum(1 for r in rows if r["first_seen"] == today),
        "winning": sum(1 for r in rows if r["is_active"] and r["run_days"] >= win),
        "ended_week": sum(1 for r in rows if not r["is_active"] and (r.get("end_date") or "") >= week_ago),
        "total": len(rows),
        "brands": len({r["brand"] for r in rows}),
    }
    out = {"updated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "today": today, "brand_guess": guess_brands(db),
           "winning_days": win, "summary": summary, "log": log, "ads": rows}
    pw = vault.password()
    if pw:   # 대시보드 데이터는 비밀번호로 암호화해서 공개
        Path("docs/data.enc.json").write_text(vault.encrypt(out, pw), encoding="utf-8")
        Path("docs/data.json").unlink(missing_ok=True)
    else:
        print("⚠ DASHBOARD_PASSWORD 없음 → 대시보드 데이터가 암호화되지 않습니다")
        Path("docs/data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"📋 오늘의 수사 보고서: {summary}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", nargs="?", default="all", choices=["all", "collect", "process"])
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    a = ap.parse_args()
    if a.step == "collect":
        collect(a.shard, a.shards)
    elif a.step == "process":
        process()
    else:
        from scraper import DEBUG_PARTNER
        res = collect(0, 1)
        process(res, DEBUG_PARTNER)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("❌ 수사 중 오류 — 위 로그를 확인하세요")
        sys.exit(1)
