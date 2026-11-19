"""Claude로 장수 소재 분석: 포맷 / 첫 3초 훅 / 소구점 / 따라하기 등급 / 셀로라바이 적용안 / 약기법 리스크."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import anthropic

PROMPT = """너는 일본 화장품 퍼포먼스 광고 전문가다. 아래 경쟁사 메타 광고 소재를 분석해라.
이미지는 소재 썸네일(영상이면 0.5초·2.5초·중간 프레임 순서)이다.

[광고 정보]
브랜드: {brand} / 페이지: {page_name}
게재 일수: {run_days}일 (게재 중: {active}) / 같은 소재 복제 수: {collation}
협력 광고 크리에이터: {partner}
영상 길이: {duration}
광고 문구:
{body}
제목/CTA: {title} / {cta}

[우리 브랜드 셀로라바이(セロラバイ) 제품]
{products}

[따라하기 등급 기준]
A = 소구점만 바꾸면 바로 응용 가능 (비포애프터, 성분 클로즈업, 텍스트 자막형, 제형 시연, UGC 리뷰형 등 저비용 범용 포맷)
B = 구조/훅만 참고 가능 (모델·세트·편집 비용이 드는 연출)
C = 따라하기 어려움 (연예인·유명 인플루언서, 브랜드 고유 IP/캐릭터, 독자 성분·특허 주장, 대규모 제작)

[약기법(薬機法)·경품표시법 체크]
화장품 효능 56항목 범위를 넘는 표현(치료·완치·シミが消える·アトピー·医薬品的効果), 근거 없는 No.1/最高,
의사 추천, 의학적 효과를 암시하는 비포애프터 등이 있으면 표시해라.

반드시 아래 JSON만 출력 (한국어로, 일본어 원문 표현은 그대로 인용 가능):
{{
 "format": "영상/이미지/캐러셀 + 스타일 한 줄 (예: UGC 셀카 리뷰형 15초)",
 "hook_3s": "첫 3초에 무엇으로 시선을 잡는지",
 "appeal_points": ["핵심 소구점 태그 1~4개, 짧게 (예: 모공, 진정, 가격, 1+1)"],
 "structure": "전개 구조 한 줄 (예: 문제제기→제형시연→비포애프터→할인CTA)",
 "production": "저|중|고",
 "grade": "A|B|C",
 "grade_reason": "등급 이유 한 줄",
 "celoraby_idea": "이 구조를 셀로라바이 제품에 적용한 구체적 아이디어 1~2문장 (어떤 제품, 어떤 소구점으로)",
 "yakkiho_risk": "없음|주의|높음",
 "yakkiho_notes": "위험 표현과 대체 표현 제안 (없으면 빈 문자열)",
 "why_winning": "오래 살아남은 이유 추정 한 줄"
}}"""


def _img_block(path: str) -> dict:
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _products(cfg: dict) -> str:
    lines = []
    for p in (cfg.get("celoraby") or {}).get("products") or []:
        lines.append(f"- {p.get('name')}: 소구점 {', '.join(p.get('appeal_points') or [])}")
    return "\n".join(lines) or "- (미입력)"


def analyze(rec: dict, run_days: int, cfg: dict, client: anthropic.Anthropic) -> dict | None:
    frames = [f for f in rec.get("frames") or [] if Path(f).exists()][:3]
    text = PROMPT.format(
        brand=rec.get("brand"), page_name=rec.get("page_name"), run_days=run_days,
        active="예" if rec.get("is_active") else "아니오(종료)",
        collation=rec.get("collation_count", 1), partner=rec.get("partner") or "없음",
        duration=f"{rec.get('duration')}초" if rec.get("duration") else "-",
        body=(rec.get("body") or "")[:1500], title=rec.get("title") or "-", cta=rec.get("cta") or "-",
        products=_products(cfg),
    )
    content = [_img_block(f) for f in frames] + [{"type": "text", "text": text}]
    resp = client.messages.create(
        model=cfg["analysis"]["model"], max_tokens=1200,
        messages=[{"role": "user", "content": content}],
    )
    out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
