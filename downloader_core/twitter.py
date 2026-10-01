def build_commands(common_options, output_template, url, proxy):
    proxy_args = ["--proxy", proxy] if proxy else []
    format_selector = (
        "b[ext=mp4][height<=480]/best[height<=480]/best"
    )

    return [
        [
            "yt-dlp",
            *common_options,
            *proxy_args,
            "--retries", "3",
            "--extractor-args",
            "twitter:api=syndication",
            "-f", format_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ],
        [
            "yt-dlp",
            *common_options,
            *proxy_args,
            "--retries", "3",
            "--extractor-args",
            "twitter:api=legacy",
            "-f", format_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ],
        [
            "yt-dlp",
            *common_options,
            *proxy_args,
            "--retries", "3",
            "-f", format_selector,
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ],
    ]
