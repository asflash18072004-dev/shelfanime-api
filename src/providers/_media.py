import httpx

from src.extractor import anilist_query
from src.providers import _cache
from src.providers._http import UA

ARM = "https://arm.haglund.dev/api/v2/ids"
ANIZIP = "https://api.ani.zip/mappings"
KITSU = "https://kitsu.io/api/edge"

MEDIA_QUERY = (
    "query($id:Int){Media(id:$id,type:ANIME){id idMal title{english romaji native} "
    "status format episodes seasonYear startDate{year} synonyms "
    "nextAiringEpisode{episode airingAt timeUntilAiring}}}"
)

_STATUS = {
    "RELEASING": "RELEASING",
    "FINISHED": "FINISHED",
    "NOT_YET_RELEASED": "NOT_YET_RELEASED",
    "CANCELLED": "FINISHED",
    "HIATUS": "HIATUS",
}


async def _fetch_arm(anilist_id: int):
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(
                f"{ARM}?source=anilist&id={anilist_id}",
                headers={"User-Agent": UA, "Accept": "application/json"},
            )
        if res.status_code != 200:
            return None
        return res.json()
    except Exception:
        return None


async def _fetch_anilist(anilist_id: int):
    try:
        data = await anilist_query(MEDIA_QUERY, {"id": int(anilist_id)})
        return (data or {}).get("Media")
    except Exception:
        return None


async def _fetch_kitsu(anilist_id: int, arm: dict | None = None):
    """Fallback identity when AniList is down. Prefer MAL id from ARM."""
    try:
        mal = (arm or {}).get("myanimelist")
        async with httpx.AsyncClient(timeout=12.0) as client:
            if mal:
                res = await client.get(
                    f"{KITSU}/mappings",
                    params={
                        "filter[externalSite]": "myanimelist/anime",
                        "filter[externalId]": str(mal),
                        "include": "item",
                    },
                    headers={"User-Agent": UA, "Accept": "application/vnd.api+json"},
                )
                if res.status_code == 200:
                    body = res.json() or {}
                    included = body.get("included") or []
                    for inc in included:
                        if (inc or {}).get("type") == "anime":
                            attrs = (inc or {}).get("attributes") or {}
                            titles = attrs.get("titles") or {}
                            return {
                                "id": int(anilist_id),
                                "idMal": mal,
                                "title": {
                                    "english": titles.get("en") or attrs.get("canonicalTitle"),
                                    "romaji": titles.get("en_jp") or attrs.get("canonicalTitle"),
                                    "native": titles.get("ja_jp"),
                                },
                                "status": "RELEASING",
                                "format": None,
                                "episodes": attrs.get("episodeCount"),
                                "seasonYear": None,
                                "startDate": None,
                                "nextAiringEpisode": None,
                                "synonyms": list(
                                    filter(
                                        None,
                                        [
                                            attrs.get("canonicalTitle"),
                                            titles.get("en"),
                                            titles.get("en_jp"),
                                            titles.get("ja_jp"),
                                        ],
                                    )
                                ),
                                "arm": arm or {},
                                "_source": "kitsu",
                            }
            res = await client.get(
                f"{KITSU}/mappings",
                params={
                    "filter[externalSite]": "anilist/anime",
                    "filter[externalId]": str(anilist_id),
                    "include": "item",
                },
                headers={"User-Agent": UA, "Accept": "application/vnd.api+json"},
            )
            if res.status_code != 200:
                return None
            body = res.json() or {}
            included = body.get("included") or []
            for inc in included:
                if (inc or {}).get("type") == "anime":
                    attrs = (inc or {}).get("attributes") or {}
                    titles = attrs.get("titles") or {}
                    return {
                        "id": int(anilist_id),
                        "idMal": (arm or {}).get("myanimelist"),
                        "title": {
                            "english": titles.get("en") or attrs.get("canonicalTitle"),
                            "romaji": titles.get("en_jp") or attrs.get("canonicalTitle"),
                            "native": titles.get("ja_jp"),
                        },
                        "status": "RELEASING",
                        "format": None,
                        "episodes": attrs.get("episodeCount"),
                        "seasonYear": None,
                        "startDate": None,
                        "nextAiringEpisode": None,
                        "synonyms": list(
                            filter(
                                None,
                                [
                                    attrs.get("canonicalTitle"),
                                    titles.get("en"),
                                    titles.get("en_jp"),
                                ],
                            )
                        ),
                        "arm": arm or {},
                        "_source": "kitsu",
                    }
    except Exception:
        return None
    return None


def _stub_media(anilist_id: int, arm: dict | None = None) -> dict:
    return {
        "id": int(anilist_id),
        "idMal": (arm or {}).get("myanimelist"),
        "title": {"english": None, "romaji": None, "native": None},
        "status": "RELEASING",
        "format": None,
        "episodes": None,
        "seasonYear": None,
        "startDate": None,
        "nextAiringEpisode": None,
        "synonyms": [],
        "arm": arm or {},
        "_source": "stub",
    }


async def get_media(anilist_id: int) -> dict:
    key = f"np-media:{anilist_id}"
    hit = _cache.cached(key, _cache.MAPPING_TTL)
    if hit is not None:
        return hit

    arm = await _fetch_arm(anilist_id)
    al = await _fetch_anilist(anilist_id)

    if al:
        media = {
            "id": int(anilist_id),
            "idMal": (arm or {}).get("myanimelist") or al.get("idMal"),
            "title": {
                "english": (al.get("title") or {}).get("english"),
                "romaji": (al.get("title") or {}).get("romaji"),
                "native": (al.get("title") or {}).get("native"),
            },
            "status": _STATUS.get(al.get("status"), "RELEASING"),
            "format": al.get("format"),
            "episodes": al.get("episodes"),
            "seasonYear": al.get("seasonYear"),
            "startDate": al.get("startDate"),
            "nextAiringEpisode": al.get("nextAiringEpisode"),
            "synonyms": al.get("synonyms") or [],
            "arm": arm or {},
            "_source": "anilist",
        }
        _cache.set(key, media, _cache.MAPPING_TTL)
        return media

    kitsu = await _fetch_kitsu(anilist_id, arm)
    if kitsu and (
        (kitsu.get("title") or {}).get("english")
        or (kitsu.get("title") or {}).get("romaji")
        or (kitsu.get("synonyms") or [])
    ):
        _cache.set(key, kitsu, _cache.MAPPING_TTL)
        return kitsu

    media = _stub_media(anilist_id, arm)
    _cache.set(key, media, 60)
    return media


async def get_anizip(anilist_id: int):
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(
                f"{ANIZIP}?anilist_id={anilist_id}",
                headers={"User-Agent": UA, "Accept": "application/json"},
            )
        if res.status_code != 200:
            return None
        return res.json()
    except Exception:
        return None


async def build_ctx(anilist_id: int, media: dict | None = None) -> dict:
    media = media or await get_media(anilist_id)
    try:
        anizip = await get_anizip(anilist_id)
    except Exception:
        anizip = None
    return {"media": media, "anizip": anizip}
