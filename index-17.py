"""
Voratoon Web API by Nat — v1.0.2
Sumber: https://voratoon.web.id  (/api/voratoon/*)
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

BASE = os.environ.get("VORATOON_WEB_BASE", "https://voratoon.web.id").rstrip("/")
TIMEOUT = float(os.environ.get("VORATOON_WEB_TIMEOUT", "35"))
PAGE_SIZE = max(1, int(os.environ.get("VORATOON_WEB_PAGE_SIZE", "24")))

app = FastAPI(title="Voratoon Web API by Nat", version="1.0.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
    "Origin": BASE,
}


async def fetch_json(path: str, params: Optional[dict] = None, retries: int = 4) -> Any:
    url = path if path.startswith("http") else f"{BASE}{path}"
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
                r = await client.get(url, headers=HEADERS, params=params or {})
            if r.status_code == 503:
                last_err = HTTPException(503, "Voratoon sibuk (503), coba lagi")
                await asyncio.sleep(0.7 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise HTTPException(r.status_code, f"Voratoon HTTP {r.status_code}")
            try:
                return r.json()
            except Exception:
                raise HTTPException(502, "Response bukan JSON")
        except HTTPException as e:
            if e.status_code == 503:
                last_err = e
                await asyncio.sleep(0.7 * (attempt + 1))
                continue
            raise
        except httpx.TimeoutException:
            last_err = HTTPException(504, "Timeout Voratoon")
            await asyncio.sleep(0.5 * (attempt + 1))
        except Exception as e:
            last_err = HTTPException(502, f"Fetch gagal: {type(e).__name__}")
            await asyncio.sleep(0.4 * (attempt + 1))
    if last_err:
        raise last_err
    raise HTTPException(502, "Fetch gagal")


def _inner(row: dict) -> dict:
    if not isinstance(row, dict):
        return {}
    d = row.get("data")
    return d if isinstance(d, dict) else {}


def _rows(body: Any) -> list:
    if isinstance(body, dict):
        rows = body.get("data")
        return rows if isinstance(rows, list) else []
    return []


def normalize_item(row: dict) -> dict:
    d = _inner(row)
    slug = str(d.get("slug") or row.get("slug") or "").strip()
    title = str(d.get("title") or d.get("name") or slug).strip()
    cover = str(
        d.get("coverImage")
        or d.get("backgroundImage")
        or d.get("cover")
        or d.get("thumbnail")
        or ""
    ).strip()
    typ = str(d.get("format") or d.get("type") or "MANGA").upper()
    genres = []
    for g in d.get("genres") or []:
        if isinstance(g, dict):
            gd = g.get("data") if isinstance(g.get("data"), dict) else g
            name = (gd or {}).get("name") or (gd or {}).get("title")
            if name:
                genres.append(str(name))
        elif isinstance(g, str) and g.strip():
            genres.append(g.strip())
    return {
        "judul": title,
        "title": title,
        "slug": slug,
        "thumbnail": cover,
        "sampul": cover,
        "type": typ,
        "status": str(d.get("status") or ""),
        "sinopsis": str(d.get("synopsis") or d.get("sinopsis") or ""),
        "genres": genres,
        "genre": genres,
        "total_chapter": d.get("totalChapters") or d.get("total_chapters") or 0,
        "url": f"{BASE}/series/{slug}" if slug else "",
        "source": "voratoon-web",
        "id": row.get("id"),
    }


def normalize_chapter(row: dict, series_slug: str = "") -> dict:
    d = _inner(row)
    slug = str(d.get("slug") or row.get("slug") or "").strip()
    number = str(d.get("index") or row.get("chapterIndex") or "").strip()
    if not number and slug:
        m = re.search(r"(\d+(?:\.\d+)?)", slug)
        if m:
            number = m.group(1)
    title = str(d.get("title") or (f"Chapter {number}" if number else slug)).strip()
    return {
        "judul": title,
        "title": title,
        "slug": slug,
        "number": number,
        "id": str(row.get("id") or slug),
        "url": f"{BASE}/series/{series_slug}/{slug}" if series_slug and slug else "",
    }


def _norm_list(rows: list) -> list[dict]:
    out, seen = [], set()
    for x in rows:
        if not isinstance(x, dict):
            continue
        it = normalize_item(x)
        s = it.get("slug") or ""
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(it)
    return out


def _match_query(item: dict, q: str) -> bool:
    q = (q or "").strip().lower()
    if not q:
        return True
    title = (item.get("judul") or item.get("title") or "").lower()
    slug = (item.get("slug") or "").lower()
    slug_q = re.sub(r"[^a-z0-9\-]+", "-", q).strip("-")
    if q in title or q in slug:
        return True
    if slug_q and (slug == slug_q or slug_q in slug or slug in slug_q):
        return True
    tokens = [t for t in re.split(r"\s+", q) if len(t) > 1]
    if tokens and all(t in title or t in slug for t in tokens):
        return True
    return False


def _chap_num(c: dict) -> float:
    n = str(c.get("number") or "")
    try:
        return float(n)
    except Exception:
        m = re.search(r"(\d+(?:\.\d+)?)", n or c.get("slug") or "")
        return float(m.group(1)) if m else -1.0


def _sort_chapters(chapters: list[dict]) -> list[dict]:
    return sorted(chapters, key=_chap_num, reverse=True)


async def _pull_pool(max_pages: int = 5) -> list[dict]:
    """Kumpulan item dari latest (dan series) untuk search/detail."""
    merged, seen = [], set()

    async def add_from(path: str, params: dict):
        try:
            body = await fetch_json(path, params)
        except HTTPException:
            return 0
        n = 0
        for it in _norm_list(_rows(body)):
            if it["slug"] in seen:
                continue
            seen.add(it["slug"])
            merged.append(it)
            n += 1
        return n

    first = await add_from("/api/voratoon/latest", {"page": 1})
    # coba page berikutnya; jika 0 item baru → upstream ignore page
    for p in range(2, max_pages + 1):
        added = await add_from("/api/voratoon/latest", {"page": p})
        if added == 0:
            break
    if len(merged) <= PAGE_SIZE:
        await add_from("/api/voratoon/series", {"page": 1})
        await add_from("/api/voratoon/series", {"page": 2})
    return merged


@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "1.0.2",
        "author": "Nat",
        "source": BASE,
        "endpoints": {
            "latest": "/api/latest?page=1",
            "search": "/api/search?q=",
            "detail": "/api/detail/{slug}",
            "chapter": "/api/chapter?slug=&chapter=",
        },
    }


@app.get("/health")
async def health():
    return {
        "status": "online",
        "app": "Voratoon-Web-API-By-Nat",
        "version": "1.0.2",
        "base": BASE,
    }


@app.get("/api/latest")
async def api_latest(page: int = Query(1, ge=1)):
    body = await fetch_json("/api/voratoon/latest", {"page": page})
    rows = _norm_list(_rows(body))
    meta = body.get("meta") if isinstance(body, dict) else {}
    if not isinstance(meta, dict):
        meta = {}

    upstream_page = meta.get("page")
    # Upstream sering selalu page=1 → paginasi dari pool
    if page > 1 and int(upstream_page or 1) == 1:
        pool = await _pull_pool(max_pages=min(6, page + 1))
        start = (page - 1) * PAGE_SIZE
        slice_rows = pool[start : start + PAGE_SIZE]
        return {
            "status": True,
            "page": page,
            "total": len(slice_rows),
            "meta": {**meta, "page": page, "client_paginated": True, "pool": len(pool)},
            "data": slice_rows,
        }

    return {
        "status": True,
        "page": page,
        "total": len(rows),
        "meta": meta,
        "data": rows,
    }


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), page: int = Query(1, ge=1)):
    q = q.strip()
    slug_q = re.sub(r"[^a-z0-9\-]+", "-", q.lower()).strip("-")
    candidates: list[dict] = []

    for params in (
        {"slug": slug_q} if slug_q else None,
        {"title": q},
        {"q": q},
    ):
        if not params:
            continue
        try:
            body = await fetch_json("/api/voratoon/series", params)
        except HTTPException:
            continue
        if isinstance(body, dict) and body.get("status") == 500 and not _rows(body):
            continue
        candidates.extend(_norm_list(_rows(body)))

    try:
        candidates.extend(await _pull_pool(max_pages=5))
    except HTTPException:
        pass

    filtered = [it for it in candidates if _match_query(it, q)]
    filtered.sort(
        key=lambda it: (
            0 if it.get("slug") == slug_q else 1,
            0 if q.lower() == (it.get("judul") or "").lower() else 1,
            0 if q.lower() in (it.get("judul") or "").lower() else 1,
            (it.get("judul") or ""),
        )
    )
    seen, out = set(), []
    for it in filtered:
        if it["slug"] in seen:
            continue
        seen.add(it["slug"])
        out.append(it)

    start = (page - 1) * PAGE_SIZE
    return {
        "status": True,
        "query": q,
        "page": page,
        "total": len(out),
        "data": out[start : start + PAGE_SIZE],
    }


@app.get("/api/detail/{slug}")
async def api_detail(slug: str):
    slug = slug.strip().strip("/")
    info = None

    try:
        body = await fetch_json("/api/voratoon/series", {"slug": slug})
        for it in _norm_list(_rows(body)):
            if it.get("slug") == slug:
                info = it
                break
    except HTTPException:
        pass

    if not info:
        try:
            for it in await _pull_pool(max_pages=6):
                if it.get("slug") == slug:
                    info = it
                    break
        except HTTPException:
            pass

    try:
        ch_body = await fetch_json(f"/api/voratoon/series/{quote(slug)}/chapters")
        rows = _rows(ch_body)
    except HTTPException:
        if not info:
            raise HTTPException(404, f"Series tidak ditemukan: {slug}")
        rows = []

    chapters = _sort_chapters(
        [normalize_chapter(x, slug) for x in rows if isinstance(x, dict)]
    )

    if not info:
        if not chapters:
            raise HTTPException(404, f"Series tidak ditemukan: {slug}")
        info = {
            "judul": slug.replace("-", " ").title(),
            "title": slug.replace("-", " ").title(),
            "slug": slug,
            "thumbnail": "",
            "sampul": "",
            "sinopsis": "",
            "genres": [],
            "genre": [],
            "status": "",
            "type": "MANGA",
            "source": "voratoon-web",
        }

    info = dict(info)
    info["chapters"] = chapters
    info["total_chapter"] = len(chapters)
    info["url"] = f"{BASE}/series/{slug}"
    return {"status": True, "data": info}


@app.get("/api/chapter")
async def api_chapter(
    slug: str = Query(""),
    chapter: str = Query(""),
    url: str = Query(""),
):
    series = slug.strip().strip("/")
    ch = chapter.strip().strip("/")
    if url and not (series and ch):
        m = re.search(r"/series/([^/]+)/([^/?#]+)", url)
        if m:
            series, ch = m.group(1), m.group(2)
    if not series or not ch:
        raise HTTPException(400, "Butuh slug + chapter (atau url)")
    if not ch.startswith("chapter-") and re.match(r"^\d", ch):
        ch = f"chapter-{ch}"

    body = await fetch_json(
        f"/api/voratoon/series/{quote(series)}/chapters/{quote(ch)}/pages"
    )
    node = body.get("data") if isinstance(body, dict) else None
    if node is None:
        raise HTTPException(404, "Chapter kosong / tidak tersedia di sumber")

    images: list[str] = []
    if isinstance(node, dict):
        d = node.get("data") if isinstance(node.get("data"), dict) else node
        raw = d.get("images") or d.get("pages") or []
        if isinstance(raw, list):
            for u in raw:
                if isinstance(u, str) and u.startswith("http"):
                    images.append(u)
                elif isinstance(u, dict):
                    uu = u.get("url") or u.get("src") or u.get("image")
                    if uu:
                        images.append(str(uu))
    if not images:
        raise HTTPException(404, "Gambar chapter kosong")

    return {
        "status": True,
        "slug": series,
        "chapter": ch,
        "total": len(images),
        "images": images,
        "gambar": images,
        "source": "voratoon-web",
        "url": f"{BASE}/series/{series}/{ch}",
    }


handler = Mangum(app)
