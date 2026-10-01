from config import MAX_DURATION_SECONDS, MAX_MB
from downloader_core import instagram, pinterest, tiktok, twitter, youtube


def build_commands(
    platform: str,
    output_template: str,
    url: str,
    *,
    instagram_proxy,
    twitter_proxy,
):
    duration_filter = (
        f"duration <=? {MAX_DURATION_SECONDS}"
        if platform in {"instagram", "pinterest"}
        else f"duration <= {MAX_DURATION_SECONDS}"
    )
    common_options = [
        "--no-playlist",
        "--max-filesize", f"{MAX_MB}M",
        "--match-filter", duration_filter,
    ]

    if platform == "youtube":
        return youtube.build_video_commands(
            common_options,
            output_template,
            url,
        )

    if platform == "tiktok":
        return tiktok.build_video_commands(
            common_options,
            output_template,
            url,
        )

    if platform == "twitter":
        return twitter.build_commands(
            common_options,
            output_template,
            url,
            twitter_proxy,
        )

    if platform == "instagram":
        return instagram.build_video_commands(
            common_options,
            output_template,
            url,
            instagram_proxy,
        )

    if platform == "pinterest":
        return pinterest.build_commands(
            common_options,
            output_template,
            url,
        )

    return []
