import unittest

from platforms import get_platform, is_instagram_story_url


class PinterestPlatformTests(unittest.TestCase):
    def test_pin_it_short_link_is_recognized(self):
        self.assertEqual(
            get_platform("https://pin.it/AbCd123"),
            "pinterest",
        )

    def test_pinterest_pin_urls_are_recognized(self):
        for host in (
            "pinterest.com",
            "www.pinterest.com",
            "m.pinterest.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(
                    get_platform(f"https://{host}/pin/123456789/"),
                    "pinterest",
                )

    def test_unsupported_pinterest_pages_are_rejected(self):
        unsupported_urls = (
            "https://pinterest.com/",
            "https://www.pinterest.com/example/board/",
            "https://m.pinterest.com/example/",
            "https://pin.it/",
            "https://pin.it/code/extra",
        )

        for url in unsupported_urls:
            with self.subTest(url=url):
                self.assertIsNone(get_platform(url))


class InstagramPlatformTests(unittest.TestCase):
    def test_story_url_is_identified_but_remains_unsupported(self):
        story_url = (
            "https://www.instagram.com/stories/tester/123456/"
        )

        self.assertTrue(is_instagram_story_url(story_url))
        self.assertIsNone(get_platform(story_url))


if __name__ == "__main__":
    unittest.main()
