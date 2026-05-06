"""
AnimeTracker — AniList GraphQL API Client
Fetches full anime data: covers, banners, synopsis, studios, trailers, airing schedule.
"""
import requests
import time
import threading
from typing import Optional, List, Dict, Any, Union
from collections import OrderedDict
from datetime import datetime


ANILIST_URL = "https://graphql.anilist.co"
CACHE_MAX_SIZE = 200
_cache: OrderedDict[str, Any] = OrderedDict()
_cache_lock = threading.Lock()


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _cache_put(key: str, value: Any):
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
        _cache[key] = value
        if len(_cache) > CACHE_MAX_SIZE:
            _cache.popitem(last=False)


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _cache_clear():
    with _cache_lock:
        _cache.clear()


# ─── GraphQL fragments ────────────────────────────────────────────────────────

MEDIA_FIELDS = """
    id
    title { romaji english native }
    coverImage { extraLarge large medium color }
    bannerImage
    description(asHtml: false)
    status
    episodes
    season
    seasonYear
    averageScore
    popularity
    genres
    studios(isMain: true) { nodes { name } }
    startDate { year month day }
    endDate { year month day }
    nextAiringEpisode { airingAt episode timeUntilAiring }
    trailer { id site }
    format
    source
    hashtag
    siteUrl
"""

MEDIA_FIELDS_SLIM = """
    id
    title { romaji english }
    coverImage { large medium color }
    bannerImage
    status
    episodes
    season
    seasonYear
    averageScore
    popularity
    genres
    studios(isMain: true) { nodes { name } }
    startDate { year month day }
    nextAiringEpisode { airingAt episode }
"""


def _post(query: str, variables: Dict, timeout: int = 10, retries: int = 3) -> Optional[Dict]:
    backoff = 1.5
    for attempt in range(retries):
        try:
            resp = requests.post(
                ANILIST_URL,
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=timeout,
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                time.sleep(min(wait, 90))
                continue
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                return None
            return data.get("data")
        except requests.Timeout:
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
        except requests.HTTPError as e:
            if e.response.status_code >= 500 and attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
            else:
                break
        except Exception:
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def search_anime(query: str, page: int = 1, per_page: int = 10) -> List[Dict]:
    """Full-text search against AniList."""
    cache_key = f"search:{query}:{page}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    gql = f"""
    query ($search: String, $page: Int, $perPage: Int) {{
        Page(page: $page, perPage: $perPage) {{
            media(search: $search, type: ANIME, isAdult: false) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {"search": query, "page": page, "perPage": per_page})
    result = data["Page"]["media"] if data else []
    _cache_put(cache_key, result)
    return result


def get_anime_by_id(anilist_id: int) -> Optional[Dict]:
    """Fetch full anime details by AniList ID."""
    cache_key = f"id:{anilist_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    gql = f"""
    query ($id: Int) {{
        Media(id: $id, type: ANIME) {{
            {MEDIA_FIELDS}
        }}
    }}
    """
    data = _post(gql, {"id": anilist_id})
    result = data.get("Media") if data else None
    if result:
        _cache_put(cache_key, result)
    return result


def get_anime_by_name(name: str, fuzzy: bool = True) -> Optional[Dict]:
    """Search by name and return best match with full data."""
    cache_key = f"name:{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    gql = f"""
    query ($search: String) {{
        Page(page: 1, perPage: 5) {{
            media(search: $search, type: ANIME, isAdult: false) {{
                {MEDIA_FIELDS}
            }}
        }}
    }}
    """
    data = _post(gql, {"search": name})
    if not data:
        return None
    media_list = data.get("Page", {}).get("media", [])
    if not media_list:
        return None

    # Pick best match: exact title match preferred
    best = media_list[0]
    name_lower = name.lower()
    for m in media_list:
        romaji = (m["title"].get("romaji") or "").lower()
        english = (m["title"].get("english") or "").lower()
        if romaji == name_lower or english == name_lower:
            best = m
            break

    _cache_put(cache_key, best)
    _cache_put(f"id:{best['id']}", best)
    return best


def get_seasonal_anime(
    season: str,
    year: int,
    sort: str = "SCORE_DESC",
    genre: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
) -> List[Dict]:
    """Fetch seasonal chart with optional genre filter."""
    cache_key = f"season:{season}:{year}:{sort}:{genre}:{page}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    genre_filter = f'genre: "{genre}",' if genre else ""
    gql = f"""
    query ($season: MediaSeason, $year: Int, $page: Int, $perPage: Int, $sort: [MediaSort]) {{
        Page(page: $page, perPage: $perPage) {{
            media(
                season: $season,
                seasonYear: $year,
                {genre_filter}
                type: ANIME,
                isAdult: false,
                format_in: [TV, TV_SHORT, ONA, MOVIE],
                sort: $sort
            ) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {
        "season": season.upper(),
        "year": year,
        "page": page,
        "perPage": per_page,
        "sort": sort.upper().split(","),
    })
    result = data["Page"]["media"] if data else []
    # Filter junk
    result = [
        m for m in result
        if m.get("popularity", 0) >= 200
        and "Hentai" not in m.get("genres", [])
    ]
    _cache_put(cache_key, result)
    return result


def get_current_season() -> tuple[str, int]:
    now = datetime.now()
    month = now.month
    year = now.year
    if month in (12, 1, 2):
        return "WINTER", year if month != 12 else year + 1
    elif month in (3, 4, 5):
        return "SPRING", year
    elif month in (6, 7, 8):
        return "SUMMER", year
    else:
        return "FALL", year


def get_next_season() -> tuple[str, int]:
    season, year = get_current_season()
    order = ["WINTER", "SPRING", "SUMMER", "FALL"]
    idx = order.index(season)
    next_idx = (idx + 1) % 4
    next_year = year + 1 if next_idx == 0 else year
    return order[next_idx], next_year


def get_trending_anime(page: int = 1, per_page: int = 20) -> List[Dict]:
    cache_key = f"trending:{page}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    gql = f"""
    query ($page: Int, $perPage: Int) {{
        Page(page: $page, perPage: $perPage) {{
            media(
                type: ANIME, isAdult: false, sort: TRENDING_DESC,
                format_in: [TV, TV_SHORT, ONA, MOVIE]
            ) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {"page": page, "perPage": per_page})
    result = data["Page"]["media"] if data else []
    _cache_put(cache_key, result)
    return result


def get_upcoming_anime(page: int = 1, per_page: int = 20) -> List[Dict]:
    cache_key = f"upcoming:{page}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    gql = f"""
    query ($page: Int, $perPage: Int) {{
        Page(page: $page, perPage: $perPage) {{
            media(
                type: ANIME, isAdult: false, status: NOT_YET_RELEASED,
                sort: POPULARITY_DESC,
                format_in: [TV, TV_SHORT, ONA, MOVIE]
            ) {{
                {MEDIA_FIELDS_SLIM}
            }}
        }}
    }}
    """
    data = _post(gql, {"page": page, "perPage": per_page})
    result = data["Page"]["media"] if data else []
    _cache_put(cache_key, result)
    return result


def refresh_airing_data(anilist_ids: List[int]) -> Dict[int, Optional[Dict]]:
    """Batch-refresh airing data for a list of AniList IDs."""
    if not anilist_ids:
        return {}

    BATCH = 5
    results: Dict[int, Optional[Dict]] = {}

    for i in range(0, len(anilist_ids), BATCH):
        batch = anilist_ids[i:i + BATCH]
        parts = []
        variables: Dict[str, Any] = {}
        for j, aid in enumerate(batch):
            parts.append(f"""
                a{j}: Media(id: $id{j}, type: ANIME) {{
                    id
                    status
                    episodes
                    nextAiringEpisode {{ airingAt episode timeUntilAiring }}
                    averageScore
                }}
            """)
            variables[f"id{j}"] = aid

        var_decls = ", ".join(f"$id{j}: Int" for j in range(len(batch)))
        gql = f"query ({var_decls}) {{ {''.join(parts)} }}"
        data = _post(gql, variables, timeout=15)
        if data:
            for j, aid in enumerate(batch):
                media = data.get(f"a{j}")
                results[aid] = media
                if media:
                    _cache_put(f"id:{aid}", {**(_cache_get(f"id:{aid}") or {}), **media})
        else:
            for aid in batch:
                results[aid] = None

    return results


def check_connection() -> tuple[bool, str, float]:
    """Check AniList connectivity and measure latency."""
    import socket
    hosts = [("graphql.anilist.co", 443), ("8.8.8.8", 53), ("1.1.1.1", 53)]
    times = []
    successes = 0
    for host, port in hosts:
        try:
            t0 = time.time()
            socket.create_connection((host, port), timeout=3)
            times.append((time.time() - t0) * 1000)
            successes += 1
        except Exception:
            pass

    if successes == 0:
        return False, "none", 0.0
    avg = sum(times) / len(times)
    if successes == len(hosts) and avg < 150:
        quality = "excellent"
    elif successes >= 2 and avg < 300:
        quality = "good"
    else:
        quality = "poor"
    return True, quality, avg


def format_air_date(start_date: Optional[Dict]) -> str:
    if not start_date:
        return "TBA"
    y, m, d = start_date.get("year"), start_date.get("month"), start_date.get("day")
    if y and m and d:
        try:
            return datetime(y, m, d).strftime("%b %d, %Y")
        except ValueError:
            pass
    if y and m:
        return datetime(y, m, 1).strftime("%b %Y")
    if y:
        return str(y)
    return "TBA"


def get_genres_list() -> List[str]:
    return [
        "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy",
        "Horror", "Mahou Shoujo", "Mecha", "Music", "Mystery", "Psychological",
        "Romance", "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller",
    ]