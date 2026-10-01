from downloader_core.formats import (
    PINTEREST_FORMAT,
    PINTEREST_FORMAT_SORT,
)


def is_unsupported_media_error(error_text: str) -> bool:
    normalized_error = " ".join(error_text.lower().split())
    unsupported_media_markers = (
        "no video formats found",
        "does not contain a video",
        "no video could be found",
        "not a video pin",
    )
    return any(
        marker in normalized_error
        for marker in unsupported_media_markers
    )


def build_commands(common_options, output_template, url):
    return [[
        "yt-dlp",
        *common_options,
        "-f", PINTEREST_FORMAT,
        "-S", PINTEREST_FORMAT_SORT,
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ]]
