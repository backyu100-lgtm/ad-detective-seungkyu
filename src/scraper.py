"""메타 광고 라이브러리 수집기.

광고 라이브러리 화면을 Playwright로 열고, 화면이 내부적으로 받아오는
GraphQL 응답 + 페이지에 박혀 있는 초기 JSON 데이터에서 광고를 뽑아냅니다.
화면 구조(HTML)가 아니라 데이터(JSON) 키를 보기 때문에 디자인이 바뀌어도 비교적 덜 깨집니다.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

AD_LIB = "https://www.facebook.com/ads/library/"
EXCLUDE = ["celoraby", "セロラバイ", "셀로라바이"]
JST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def build_url(comp: dict, country: str) -> str:
    params = {"active_status": "all", "ad_type": "all",
              "country": country, "media_type": "all"}
    if str(comp.get("page_id") or "").strip():
        params.update(search_type="page", view_all_page_id=str(comp["page_id"]).strip())
    else:
        params.update(search_type="keyword_unordered", q=comp.get("keyword") or comp["name"])
    return AD_LIB + "?" + urllib.parse.urlencode(params)


# ---------- JSON 파싱 ----------
def parse_fb_json(text: str) -> list:
    """페이스북 응답은 'for (;;);' 접두어나 여러 줄 JSON일 수 있음."""
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[9:]
    out = []
    for line in text.splitlines() or [text]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def find_ads(obj, out: list):
    """JSON 트리 어디에 있든 ad_archive_id + snapshot 을 가진 객체를 찾는다."""
    if isinstance(obj, dict):
        if "ad_archive_id" in obj and isinstance(obj.get("snapshot"), dict):
            out.append(obj)
            return
        for v in obj.values():
            find_ads(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_ads(v, out)


def _date(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), JST).date().isoformat()
    except Exception:
        return None


def _text(v):
    if isinstance(v, dict):
        return v.get("text") or ""
    return v or ""


def normalize(raw: dict) -> dict:
    snap = raw.get("snapshot") or {}
    cards = snap.get("cards") or []
    media = []

    def add_img(d):
        url = d.get("original_image_url") or d.get("resized_image_url")
        if url:
            media.append({"type": "image", "url": url})

    def add_vid(d):
        url = d.get("video_hd_url") or d.get("video_sd_url")
        if url:
            media.append({"type": "video", "url": url,
                          "preview": d.get("video_preview_image_url")})

    for v in snap.get("videos") or []:
        add_vid(v)
    for i in snap.get("images") or []:
        add_img(i)
    for c in cards:
        if c.get("video_hd_url") or c.get("video_sd_url"):
            add_vid(c)
        else:
            add_img(c)

    body = _text(snap.get("body")) or (cards[0].get("body") if cards else "") or ""
    title = snap.get("title") or (cards[0].get("title") if cards else "") or ""
    branded = snap.get("branded_content") or {}
    partner = branded.get("page_name") if isinstance(branded, dict) else None

    ad_id = str(raw.get("ad_archive_id"))
    return {
        "id": ad_id,
        "page_id": str(raw.get("page_id") or snap.get("page_id") or ""),
        "page_name": raw.get("page_name") or snap.get("page_name") or "",
        "start_date": _date(raw.get("start_date")),
        "end_date": _date(raw.get("end_date")),
        "is_active": bool(raw.get("is_active")),
        "platforms": raw.get("publisher_platform") or [],
        "collation_count": raw.get("collation_count") or 1,
        "collation_id": str(raw.get("collation_id") or ""),
        "body": body if isinstance(body, str) else _text(body),
        "title": title if isinstance(title, str) else _text(title),
        "cta": snap.get("cta_text") or "",
        "link_url": snap.get("link_url") or "",
        "partner": partner,                       # 협력(파트너십) 광고 크리에이터
        "display_format": snap.get("display_format") or "",
        "media": media,
        "ad_url": f"https://www.facebook.com/ads/library/?id={ad_id}",
    }


# ---------- 수집 ----------
def _dismiss_cookies(page):
    for label in ["すべてのCookieを許可", "Allow all cookies", "모든 쿠키 허용",
                  "オプションのCookieを拒否する", "Decline optional cookies"]:
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count():
                btn.first.click(timeout=2000)
                return
        except Exception:
            pass


def scrape_competitor(comp: dict, country: str, max_scrolls=30, wait=2.5) -> list[dict]:
    raws: list = []

    def on_response(resp):
        try:
            if "/api/graphql" in resp.url and resp.status == 200:
                for j in parse_fb_json(resp.text()):
                    find_ads(j, raws)
        except Exception:
            pass

    url = build_url(comp, country)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="ja-JP", timezone_id="Asia/Tokyo",
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(4)
        _dismiss_cookies(page)

        # 페이지에 박혀 있는 첫 묶음 데이터
        try:
            scripts = page.eval_on_selector_all(
                'script[type="application/json"]', "els => els.map(e => e.textContent)")
            for s in scripts:
                if "ad_archive_id" in (s or ""):
                    for j in parse_fb_json(s):
                        find_ads(j, raws)
        except Exception:
            pass

        stale, last = 0, -1
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 6000)
            time.sleep(wait)
            n = len({r.get("ad_archive_id") for r in raws})
            stale = stale + 1 if n == last else 0
            last = n
            if stale >= 3:
                break
        browser.close()

    ads, seen, pages_seen = [], set(), {}
    names = [n.lower() for n in comp.get("page_names") or []]
    keyword_mode = not str(comp.get("page_id") or "").strip()
    hit = lambda s: any(n in (s or "").lower() for n in names)
    for r in raws:
        ad = normalize(r)
        if ad["id"] in seen:
            continue
        seen.add(ad["id"])
        pages_seen[ad["page_name"]] = pages_seen.get(ad["page_name"], 0) + 1
        # 키워드 검색일 땐 다른 브랜드/리셀러 광고가 섞이므로 페이지명으로 거름
        if keyword_mode and names:
            if hit(ad["page_name"]):
                pass
            elif ad["partner"] and hit(ad["partner"]):
                # 크리에이터 페이지로 올라간 협력 광고 → 크리에이터를 partner 로
                ad["page_name"], ad["partner"] = ad["partner"], ad["page_name"]
            else:
                continue
        if any(x in (ad["page_name"] + " " + (ad["partner"] or "")).lower() for x in EXCLUDE):
            continue          # 우리 브랜드(셀로라바이)는 제외
        # 키워드 발굴(sweep)은 광고주 페이지 이름 자체를 브랜드로 사용
        ad["brand"] = (ad["page_name"] or "(이름없음)") if comp.get("sweep") else comp["name"]
        ad["source"] = "sweep" if comp.get("sweep") else "watch"
        ad["keyword"] = comp.get("keyword") if comp.get("sweep") else None
        ads.append(ad)
    scrape_competitor.pages_seen = dict(sorted(pages_seen.items(), key=lambda x: -x[1])[:15])
    return ads
