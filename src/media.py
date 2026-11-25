"""소재 다운로드 + 썸네일/분석용 프레임 만들기 (ffmpeg)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}
THUMBS = Path("docs/thumbs")     # 대시보드 카드용 작은 썸네일
FRAMES = Path("data/frames")     # AI 분석용 프레임 (영상은 첫 3초 훅 + 중간)


def download(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, headers=UA, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return dest.stat().st_size > 0
    except Exception as e:
        print(f"  ! 다운로드 실패: {e}")
        return False


def _ff(args: list[str]) -> bool:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True)
    return r.returncode == 0


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def make_previews(ad_id: str, path: Path, kind: str) -> dict:
    """썸네일 1장 + 분석용 프레임 경로를 돌려준다."""
    THUMBS.mkdir(parents=True, exist_ok=True)
    FRAMES.mkdir(parents=True, exist_ok=True)
    thumb = THUMBS / f"{ad_id}.jpg"
    frames = []
    if kind == "video":
        dur = duration(path)
        points = [0.5, 2.5] + ([dur / 2] if dur > 6 else [])
        for i, t in enumerate(points):
            out = FRAMES / f"{ad_id}_{i}.jpg"
            if _ff(["-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                    "-vf", "scale=512:-2", "-q:v", "6", str(out)]):
                frames.append(str(out))
        if frames:
            _ff(["-i", frames[0], "-vf", "scale=360:-2", "-q:v", "6", str(thumb)])
        return {"thumb": thumb.name if thumb.exists() else None, "frames": frames,
                "duration": round(dur, 1)}
    out = FRAMES / f"{ad_id}_0.jpg"
    if _ff(["-i", str(path), "-vf", "scale='min(768,iw)':-2", "-q:v", "4", str(out)]):
        frames.append(str(out))
    _ff(["-i", str(path), "-vf", "scale=360:-2", "-q:v", "6", str(thumb)])
    return {"thumb": thumb.name if thumb.exists() else None, "frames": frames}


def save_thumb(ad_id: str, media: list[dict]) -> str | None:
    """발견 즉시 썸네일만 가볍게 저장 (영상 본편은 조건 충족 시 따로 다운로드)."""
    THUMBS.mkdir(parents=True, exist_ok=True)
    thumb = THUMBS / f"{ad_id}.jpg"
    for m in media:
        url = m.get("preview") if m["type"] == "video" else m.get("url")
        if not url:
            continue
        tmp = THUMBS / f"_{ad_id}.tmp"
        if download(url, tmp):
            ok = _ff(["-i", str(tmp), "-vf", "scale=300:-2", "-q:v", "7", str(thumb)])
            tmp.unlink(missing_ok=True)
            if ok:
                return thumb.name
    return None
