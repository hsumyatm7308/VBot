from urllib.parse import urlparse

import httpx


async def resolve_tiktok_url(url: str) -> str:
    if not (
        "vt.tiktok.com" in url
        or "vm.tiktok.com" in url
    ):
        return url

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
        ) as client:
            response = await client.get(url)

        return str(response.url)

    except Exception:
        return url


def is_http_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def get_platform(url: str):
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if parsed.scheme not in ("http", "https"):
        return None

    if parsed.username or parsed.password:
        return None

    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path or "/"

    # YouTube
    youtube_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }

    if host in youtube_hosts:
        if host == "youtu.be":
            return "youtube" if path.strip("/") else None

        if path.startswith((
            "/watch",
            "/shorts/",
            "/live/",
        )):
            return "youtube"

        return None

    # TikTok
    tiktok_hosts = {
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }

    if host in tiktok_hosts:
        if host in {
            "vm.tiktok.com",
            "vt.tiktok.com",
        }:
            return "tiktok" if path.strip("/") else None

        # Normal TikTok video
        if "/video/" in path:
            return "tiktok"

        # TikTok photo post
        if "/photo/" in path:
            return "tiktok"

        return None

    # X / Twitter
    twitter_hosts = {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }

    if host in twitter_hosts:
        if "/status/" in path:
            return "twitter"

        return None

    # Instagram
    instagram_hosts = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
}

    if host in instagram_hosts:
        if path.startswith((
            "/reel/",
            "/reels/",
            "/p/",
            "/tv/",
        )):
            return "instagram"

        return None

    return None


def is_tiktok_photo_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or ""
    return "/photo/" in path
