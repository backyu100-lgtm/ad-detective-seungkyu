"""소재 부가정보: 카피 키워드 · 카테고리 · 이미지 지문(유사 광고) · 실제 브랜드 추측.

모두 AI 없이 계산 (무료·빠름). AI 분석 결과에 brand_guess 가 있으면 추측에 가산점.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from janome.tokenizer import Tokenizer

_TK = None
STOP = set("""こと もの ため よう 今 方 これ それ あれ 私 人 肌 時 日 中 方法 場合 感 的 さ 化 用 様 毎日 全て すべて
コレ ココ 本当 本 個 回 分 円 年 月 位 位置 ここ そこ どこ 自分 みんな 皆 何 なに 今回 今日 ご 商品 方々 部分 お客様 必要 おすすめ
www com jp http https html the and for with you your this that from are our not but all new""".split())
CATS = {
    "클렌징": ["クレンジング", "洗顔", "クレンザー", "フォーム", "cleansing", "cleanser"],
    "토너·패드": ["化粧水", "トナー", "ローション", "パッド", "toner", "pad"],
    "세럼·앰플": ["美容液", "セラム", "アンプル", "エッセンス", "serum", "ampoule", "essence", "スキンブースター"],
    "크림": ["クリーム", "cream", "バーム", "ジェル"],
    "마스크팩": ["パック", "マスク", "シートマスク", "mask"],
    "선케어": ["日焼け止め", "UV", "サンスクリーン", "SPF", "日焼け", "sun"],
    "메이크업": ["ファンデ", "クッション", "リップ", "ティント", "コンシーラー", "アイシャドウ", "マスカラ", "下地", "チーク", "パウダー", "メイク"],
    "디바이스": ["美顔器", "デバイス", "EMS", "ドライヤー", "美容機器", "device"],
    "바디·헤어": ["ボディ", "シャンプー", "ヘア", "トリートメント", "ハンド", "body", "hair"],
    "이너뷰티": ["サプリ", "コラーゲンドリンク", "飲む", "ドリンク", "supplement"],
}
GENERIC_TAGS = set("""pr ad ads sponsored skincare kbeauty k beauty cosme cosmetics qoo10 megawari メガ割 韓国コスメ スキンケア
beauty makeup japan instagood follow like 美容 コスメ 美肌 化粧品 kcosme koreancosmetics""".split())
GENERIC_BRACKET = set("""セール キャンペーン クーポン プレゼント ポイント 公式 限定 送料無料 新発売 先行販売 予約 特典 PR 期間限定
NEW SALE BEST SET 必見 速報 再入荷 数量限定 楽天 Qoo10 QOO10 メガ割 Amazon""".split())
NOT_BRAND_HOSTS = ("lin.ee", "line.me", "linktr.ee", "bit.ly", "instagram.com", "facebook.com", "fb.me", "tiktok.com",
                   "youtube.com", "youtu.be", "note.com", "ameblo.jp", "amzn.to", "amazon.co.jp", "t.co", "x.com",
                   "lit.link", "apps.apple.com", "play.google.com", "forms.gle", "google.com")


def tokenizer():
    global _TK
    if _TK is None:
        _TK = Tokenizer()
    return _TK


def keywords(text: str, limit: int = 25) -> list[str]:
    """카피에서 의미 있는 단어(명사·가타카나·영단어)만 뽑는다."""
    text = re.sub(r"https?://\S+", " ", text or "")[:1500]
    out = []
    # 영문·숫자 브랜드명(23YEARSOLD, PDRN, VT)과 자주 쓰는 합성어는 형태소 분석 전에 통째로 뽑는다
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9&'\-.]*[A-Za-z][A-Za-z0-9&'\-.]*", text):
        w = w.strip(".-'")
        if len(w) >= 2 and w.lower() not in STOP:
            out.append(w.upper())     # 영문은 대문자로 통일 (Anua / ANUA 중복 방지)
    for w in ("メガ割", "メガ割り", "福袋", "先行販売", "送料無料", "限定セット", "美容液", "化粧水", "日焼け止め", "美顔器"):
        if w in text:
            out.append(w)
            text = text.replace(w, " ")
    text = re.sub(r"[A-Za-z0-9][A-Za-z0-9&'\-.]*[A-Za-z][A-Za-z0-9&'\-.]*", " ", text)
    for t in tokenizer().tokenize(text):
        pos = t.part_of_speech.split(",")
        w = t.surface.strip()
        if pos[0] != "名詞" or pos[1] in ("数", "非自立", "代名詞", "接尾", "副詞可能"):
            continue
        if len(w) < 2 or w.lower() in STOP or re.fullmatch(r"[\W_\d]+", w):
            continue
        out.append(w)
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w); uniq.append(w)
    return uniq[:limit]


def categories(text: str) -> list[str]:
    low = (text or "").lower()
    return [c for c, words in CATS.items() if any(w.lower() in low for w in words)]


def channel(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    if not h:
        return ""
    if "qoo10" in h:
        return "Qoo10"
    if "rakuten" in h:
        return "楽天"
    if "amazon" in h or "amzn" in h:
        return "Amazon"
    if "yahoo" in h:
        return "Yahoo"
    if "lin.ee" in h or "line.me" in h:
        return "LINE"
    if "instagram" in h or "tiktok" in h or "youtube" in h:
        return "SNS"
    return "자사몰·기타"


def real_url(url: str) -> str:
    """페이스북 리디렉트(l.facebook.com/l.php?u=...) 풀기."""
    try:
        p = urlparse(url)
        if "facebook.com" in p.netloc and p.path.startswith("/l.php"):
            return unquote(parse_qs(p.query).get("u", [url])[0])
    except Exception:
        pass
    return url or ""


def dhash(path: Path) -> str | None:
    try:
        from PIL import Image
        im = Image.open(path).convert("L").resize((9, 8))
        px = list(im.getdata())
        bits = "".join("1" if px[r * 9 + c] > px[r * 9 + c + 1] else "0" for r in range(8) for c in range(8))
        return f"{int(bits, 2):016x}"
    except Exception:
        return None


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def _url_brand(url: str) -> str | None:
    url = real_url(url)
    p = urlparse(url)
    h, path = p.netloc.lower(), p.path
    if not h or any(x in h for x in NOT_BRAND_HOSTS):
        return None
    m = re.search(r"/shop/([^/?#]+)", path) if "qoo10" in h else None
    if m:
        return unquote(m.group(1))
    if "rakuten" in h:
        seg = [x for x in path.split("/") if x]
        return seg[0] if seg and seg[0] not in ("gold", "item", "search") else (seg[1] if len(seg) > 1 else None)
    if "qoo10" in h or "yahoo" in h:
        return None
    parts = h.replace("www.", "").split(".")
    return parts[0] if parts and len(parts[0]) > 2 else None


def guess_brands(db: dict) -> dict:
    """계정(page_name)별 실제 브랜드 추측. 계정명 자체가 브랜드면 추측하지 않음."""
    score: dict[str, Counter] = defaultdict(Counter)
    for r in db.values():
        page = r.get("page_name") or ""
        if not page:
            continue
        text = (r.get("body") or "") + " " + (r.get("title") or "")
        for b in re.findall(r"[【\[]([A-Za-z0-9][A-Za-z0-9 .&'\-]{1,28}|[ァ-ヶー・]{3,20})[】\]]", text):
            b = b.strip()
            if b and b not in GENERIC_BRACKET and b.upper() not in GENERIC_BRACKET:
                score[page][b] += 3
        for t in re.findall(r"[#＃]([A-Za-z0-9_]{3,30})", text):
            if t.lower() not in GENERIC_TAGS:
                score[page][t] += 2
        u = _url_brand(r.get("link_url") or "")
        if u:
            score[page][u] += 3
        ai = (r.get("analysis") or {}).get("brand_guess") or (r.get("analysis_claude") or {}).get("brand_guess")
        if ai and ai not in ("-", "불명", "없음", "unknown"):
            score[page][ai] += 4
    out = {}
    for page, c in score.items():
        if not c:
            continue
        # 대소문자만 다른 후보 합치기
        merged: Counter = Counter()
        label = {}
        for k, v in c.items():
            nk = _norm(k)
            if not nk:
                continue
            merged[nk] += v
            label.setdefault(nk, k)
        if not merged:
            continue
        best, pts = merged.most_common(1)[0]
        if pts < 4:
            continue
        if best in _norm(page) or _norm(page) in best:
            continue        # 계정명이 이미 브랜드명
        out[page] = label[best]
    return out


def enrich(db: dict, thumbs_dir: Path = Path("docs/thumbs")):
    """수집 기록에 kw / cats / dhash / channel 을 채운다 (이미 있으면 건너뜀)."""
    n = 0
    for r in db.values():
        text = " ".join([r.get("body") or "", r.get("title") or ""])
        if "kw" not in r:
            r["kw"] = keywords(text)
            n += 1
        an = r.get("analysis") or {}
        cats = categories(text)
        if an.get("category") and an["category"] not in cats and an["category"] != "기타":
            cats.append(an["category"])
        r["cats"] = cats
        if r.get("link_url"):
            r["link_url"] = real_url(r["link_url"])
            r["channel"] = channel(r["link_url"])
        if "dhash" not in r and r.get("thumb") and (thumbs_dir / r["thumb"]).exists():
            r["dhash"] = dhash(thumbs_dir / r["thumb"])
    return n
