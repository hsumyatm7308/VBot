import re


YOUTUBE_1080_FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]"
    "+ba[acodec^=mp4a]"
    "/b[ext=mp4][height<=1080]"
)
YOUTUBE_720_FORMAT = (
    "bv*[vcodec^=avc1][height<=720]"
    "+ba[acodec^=mp4a]"
    "/b[ext=mp4][height<=720]"
)
YOUTUBE_480_FORMAT = (
    "b[ext=mp4][height<=480]"
    "/best[height<=480]"
    "/best"
)
YOUTUBE_FORMATS = (
    YOUTUBE_1080_FORMAT,
    YOUTUBE_720_FORMAT,
    YOUTUBE_480_FORMAT,
)
YOUTUBE_QUALITY_HEIGHTS = {
    YOUTUBE_1080_FORMAT: 1080,
    YOUTUBE_720_FORMAT: 720,
    YOUTUBE_480_FORMAT: 480,
}
YOUTUBE_PLAYER_CLIENT_FALLBACKS = (
    (
        "--extractor-args",
        "youtube:player_client=default,-android_sdkless",
    ),
    (
        "--extractor-args",
        "youtube:player_client=android",
    ),
    (),
)
YOUTUBE_SIZE_SAFETY_RATIO = 0.9
TIKTOK_VIDEO_FORMAT = (
    "b[ext=mp4][vcodec^=h264]"
    "/b[ext=mp4][vcodec^=avc1]"
    "/b[ext=mp4]"
    "/best"
)
TIKTOK_FORMAT_SORT = "res:1080,br"
PINTEREST_FORMAT = "bv[vcodec^=avc1]+ba/b[ext=mp4]/best"
PINTEREST_FORMAT_SORT = "res:1080,br"


def positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return number


def estimate_format_size(format_info: dict, duration):
    for size_key in ("filesize", "filesize_approx"):
        size = positive_number(format_info.get(size_key))
        if size is not None:
            return size

    media_duration = (
        positive_number(duration)
        or positive_number(format_info.get("duration"))
    )
    if media_duration is None:
        return None

    bitrate = positive_number(format_info.get("tbr"))
    if bitrate is None:
        if str(format_info.get("vcodec", "none")) == "none":
            bitrate = positive_number(format_info.get("abr"))
        elif str(format_info.get("acodec", "none")) == "none":
            bitrate = positive_number(format_info.get("vbr"))

    if bitrate is None:
        return None

    return bitrate * 1000 * media_duration / 8


def format_quality_key(format_info: dict):
    return (
        positive_number(format_info.get("height")) or 0,
        positive_number(format_info.get("fps")) or 0,
        positive_number(format_info.get("tbr"))
        or positive_number(format_info.get("vbr"))
        or positive_number(format_info.get("abr"))
        or 0,
    )


def get_format_selector(command) -> str:
    try:
        option_index = command.index("-f")
        return command[option_index + 1]
    except (ValueError, IndexError):
        return ""


def get_downloaded_format_ids(command_output: str) -> str:
    matches = re.findall(
        r"Downloading(?:\s+\d+)?\s+format(?:\(s\)|s)?:\s*([^\r\n]+)",
        command_output,
        flags=re.IGNORECASE,
    )
    return matches[-1].strip() if matches else ""


def get_actual_media_properties(
    metadata: dict | None,
    command_output: str,
):
    format_ids = get_downloaded_format_ids(command_output)
    properties = {}

    if format_ids:
        properties["format_id"] = format_ids

    if not metadata or not format_ids:
        return properties

    formats_by_id = {
        str(format_info.get("format_id")): format_info
        for format_info in metadata.get("formats") or []
        if format_info.get("format_id") is not None
    }
    selected_formats = [
        formats_by_id[format_id.strip()]
        for format_id in format_ids.split("+")
        if format_id.strip() in formats_by_id
    ]

    video_formats = [
        format_info
        for format_info in selected_formats
        if str(format_info.get("vcodec", "none")) != "none"
    ]
    audio_formats = [
        format_info
        for format_info in selected_formats
        if str(format_info.get("acodec", "none")) != "none"
    ]

    if video_formats:
        video_format = max(video_formats, key=format_quality_key)
        width = positive_number(video_format.get("width"))
        height = positive_number(video_format.get("height"))
        metadata_resolution = str(
            video_format.get("resolution", "")
        ).strip()
        resolution_match = re.fullmatch(
            r"(\d+)x(\d+)",
            metadata_resolution,
        )

        if resolution_match is not None:
            if width is None:
                width = float(resolution_match.group(1))
            if height is None:
                height = float(resolution_match.group(2))

        if width is not None:
            properties["actual_width"] = int(width)
        if height is not None:
            properties["actual_height"] = int(height)
        if width is not None and height is not None:
            properties["actual_resolution"] = f"{int(width)}x{int(height)}"
        elif metadata_resolution and metadata_resolution != "audio only":
            properties["actual_resolution"] = metadata_resolution

        video_codec = str(video_format.get("vcodec", ""))
        if video_codec and video_codec != "none":
            properties["vcodec"] = video_codec

    if audio_formats:
        audio_codec = str(audio_formats[-1].get("acodec", ""))
        if audio_codec and audio_codec != "none":
            properties["acodec"] = audio_codec

    return properties


def format_media_properties(properties: dict) -> str:
    return " ".join(
        f"{key}={value}"
        for key, value in properties.items()
    )
