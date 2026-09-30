import unittest

from platforms import get_platform


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


if __name__ == "__main__":
    unittest.main()
