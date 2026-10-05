import ipaddress
import socket
import asyncio
from urllib.parse import urljoin, urlparse

import httpx


MAX_TIKTOK_REDIRECTS = 10
TIKTOK_SHORT_HOSTS = {"vt.tiktok.com", "vm.tiktok.com"}


async def _is_safe_tiktok_target(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.hostname
            or get_platform(url) != "tiktok"
        ):
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = parsed.hostname.rstrip(".")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                0,
                socket.SOCK_STREAM,
            )
            addresses = [
                ipaddress.ip_address(result[4][0].split("%", 1)[0])
                for result in resolved
            ]
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, TypeError, ValueError):
        return False


async def resolve_tiktok_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        if (parsed.hostname or "").lower().rstrip(".") not in TIKTOK_SHORT_HOSTS:
            return url
    except (TypeError, ValueError):
        return None

    current_url = url
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(MAX_TIKTOK_REDIRECTS + 1):
                if not await _is_safe_tiktok_target(current_url):
                    return None

                response = await client.get(
                    current_url,
                    follow_redirects=False,
                )
                if response.status_code not in {301, 302, 303, 307, 308}:
                    return str(response.url)

                location = response.headers.get("location")
                if not location:
                    return None
                current_url = urljoin(current_url, location)
    except Exception:
        return None

    return None


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

    # Pinterest video Pins
    if host == "pin.it":
        short_code = path.strip("/")
        if short_code and "/" not in short_code:
            return "pinterest"

        return None

    pinterest_hosts = {
        "pinterest.com",
        "www.pinterest.com",
        "m.pinterest.com",
    }

    if host in pinterest_hosts:
        path_parts = [
            part
            for part in path.strip("/").split("/")
            if part
        ]
        if len(path_parts) == 2 and path_parts[0].lower() == "pin":
            return "pinterest"

        return None

    return None


def is_tiktok_photo_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or ""
    return "/photo/" in path


def is_instagram_post_url(url: str) -> bool:
    parsed = urlparse(url)

    return (
        parsed.netloc.lower()
        in {
            "instagram.com",
            "www.instagram.com",
            "m.instagram.com",
        }
        and parsed.path.lower().startswith("/p/")
    )


def is_instagram_story_url(url: str) -> bool:
    parsed = urlparse(url)

    return (
        parsed.scheme in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (parsed.hostname or "").lower().rstrip(".")
        in {
            "instagram.com",
            "www.instagram.com",
            "m.instagram.com",
        }
        and parsed.path.lower().startswith("/stories/")
    )
