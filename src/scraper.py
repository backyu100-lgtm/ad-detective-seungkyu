"""메타 광고 라이브러리 수집기.

광고 라이브러리 화면을 Playwright로 열고, 화면이 내부적으로 받아오는
GraphQL 응답 + 페이지에 박혀 있는 초기 JSON 데이터에서 광고를 뽑아냅니다.
화면 구조(HTML)가 아니라 데이터(JSON) 키를 보기 때문에 디자인이 바뀌어도 비교적 덜 깨집니다.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

AD_LIB = "https://www.facebook.com/ads/library/"
EXCLUDE = ["celoraby", "セロラバイ", "셀로라바이"]
JST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


KANA = re.compile(r"[\u3040-\u30ff]")      # 히라가나·가타카나
DEBUG_PARTNER: list = []                    # 협력 광고 원본 필드 샘플 (data/debug_partnership.json)


def build_url(comp: dict, country: str, lang: str | None = "ja") -> str:
    params = {"active_status": "all", "ad_type": "all",
              "country": country, "media_type": "all"}
    if lang:
        params["content_languages[0]"] = lang    # 광고 라이브러리 '언어' 필터
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
    body = body if isinstance(body, str) else _text(body)
    title = title if isinstance(title, str) else _text(title)
    all_text = " ".join([body, title] + [str(c.get("body") or "") + str(c.get("title") or "") for c in cards])

    # 협력 광고: 두 계정 이름이 여러 항목에 나뉘어 들어올 수 있어 전부 모은다
    page = raw.get("page_name") or snap.get("page_name") or snap.get("current_page_name") or ""
    branded = snap.get("branded_content") if isinstance(snap.get("branded_content"), dict) else {}
    names = [raw.get("page_name"), snap.get("page_name"), snap.get("current_page_name"),
             branded.get("page_name"), branded.get("current_page_name")]
    accounts = []
    for n in names:
        if n and n.strip() and n.strip().lower() not in [a.lower() for a in accounts]:
            accounts.append(n.strip())
    partner = next((a for a in accounts if a.lower() != page.strip().lower()), None)
    if branded and len(DEBUG_PARTNER) < 30:
        DEBUG_PARTNER.append({"id": str(raw.get("ad_archive_id")), "raw_page_name": raw.get("page_name"),
                              "snap_page_name": snap.get("page_name"),
                              "snap_current_page_name": snap.get("current_page_name"),
                              "byline": snap.get("byline"), "branded_content": branded,
                              "accounts": accounts, "partner": partner})
    link = snap.get("link_url") or next((c.get("link_url") for c in cards if c.get("link_url")), "") or ""

    ad_id = str(raw.get("ad_archive_id"))
    return {
        "id": ad_id,
        "page_id": str(raw.get("page_id") or snap.get("page_id") or ""),
        "page_name": page,
        "start_date": _date(raw.get("start_date")),
        "end_date": _date(raw.get("end_date")),
        "is_active": bool(raw.get("is_active")),
        "platforms": raw.get("publisher_platform") or [],
        "collation_count": raw.get("collation_count") or 1,
        "collation_id": str(raw.get("collation_id") or ""),
        "body": body,
        "title": title,
        "cta": snap.get("cta_text") or "",
        "link_url": link,
        "link_caption": snap.get("caption") or "",
        "partner": partner,                       # 협력(파트너십) 광고의 상대 계정
        "accounts": accounts,
        "has_text": bool(all_text.strip()),
        "is_ja": bool(KANA.search(all_text)),
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


class Browser:
    """여러 대상을 수집할 때 브라우저를 한 번만 띄워 재사용."""
    def __enter__(self):
        self._p = sync_playwright().start()
        self.browser = self._p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        return self

    def __exit__(self, *a):
        try:
            self.browser.close()
        finally:
            self._p.stop()


def scrape_competitor(comp: dict, country: str, max_scrolls=30, wait=2.5,
                      lang: str | None = "ja", ja_only: bool = True, browser: "Browser | None" = None) -> list[dict]:
    if browser is None:
        with Browser() as b:
            return scrape_competitor(comp, country, max_scrolls, wait, lang, ja_only, b)
    raws: list = []

    def on_response(resp):
        try:
            if "/api/graphql" in resp.url and resp.status == 200:
                for j in parse_fb_json(resp.text()):
                    find_ads(j, raws)
        except Exception:
            pass

    def count():
        return len({r.get("ad_archive_id") for r in raws})

    url = build_url(comp, country, lang)
    ctx = browser.browser.new_context(user_agent=UA, locale="ja-JP", timezone_id="Asia/Tokyo",
                                      viewport={"width": 1366, "height": 900})
    try:
        page = ctx.new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
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

        # 스크롤: 새 광고가 들어오면 바로 다음 스크롤 (고정 대기 대신 최대 wait 초까지만 기다림)
        stale, last = 0, count()
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 6000)
            waited = 0.0
            while waited < wait:
                page.wait_for_timeout(300)        # 이 동안 응답 이벤트가 처리됨
                waited += 0.3
                if count() > last:
                    page.wait_for_timeout(400)    # 같은 묶음이 마저 들어오도록 잠깐
                    break
            n = count()
            stale = stale + 1 if n == last else 0
            last = n
            if stale >= 3:                        # 3번 연속 새 광고 없음 = 끝까지 봄
                break
    finally:
        ctx.close()

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
        # 일본어 광고만 (문구가 아예 없는 이미지·영상 광고는 예외로 수집)
        if ja_only and ad["has_text"] and not ad["is_ja"]:
            continue
        # 키워드 검색일 땐 다른 브랜드/리셀러 광고가 섞이므로 페이지명으로 거름
        if keyword_mode and names:
            # 광고 계정 또는 협력 상대 계정 중 하나라도 브랜드명과 맞으면 수집
            if not any(hit(a) for a in ad["accounts"] or [ad["page_name"]]):
                continue
        if any(x in (ad["page_name"] + " " + (ad["partner"] or "")).lower() for x in EXCLUDE):
            continue          # 우리 브랜드(셀로라바이)는 제외
        # 키워드 발굴(sweep)은 광고주 페이지 이름 자체를 브랜드로 사용
        ad["brand"] = (ad["page_name"] or "(이름없음)") if comp.get("sweep") else comp["name"]
        ad["source"] = comp.get("tier") or ("sweep" if comp.get("sweep") else "watch")
        ad["keyword"] = comp.get("keyword") if comp.get("sweep") else None
        ads.append(ad)
    scrape_competitor.pages_seen = dict(sorted(pages_seen.items(), key=lambda x: -x[1])[:15])
    return ads
