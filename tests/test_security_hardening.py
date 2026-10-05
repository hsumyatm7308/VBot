import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from config import MAX_MB
from downloader_core import process
from platforms import resolve_tiktok_url
from utils import (
    InsufficientDiskSpaceError,
    ensure_temporary_disk_space,
    sanitize_log_text,
)


class LogSanitizationTests(unittest.TestCase):
    def test_removes_proxy_credentials_and_signed_query_parameters(self):
        message = (
            "request failed at "
            "https://proxy-user:proxy-pass@media.example/video?id=123&token=abc#part"
        )

        sanitized = sanitize_log_text(message)

        self.assertNotIn("proxy-user", sanitized)
        self.assertNotIn("proxy-pass", sanitized)
        self.assertNotIn("token=abc", sanitized)
        self.assertNotIn("id=123", sanitized)
        self.assertIn("https://media.example/video?[REDACTED]", sanitized)

    def test_redacts_bare_secret_assignments(self):
        sanitized = sanitize_log_text(
            "access_token=topsecret Authorization: Bearer bearer-secret "
            "Proxy-Authorization: Basic proxy-secret sig=signature"
        )

        self.assertNotIn("topsecret", sanitized)
        self.assertNotIn("bearer-secret", sanitized)
        self.assertNotIn("proxy-secret", sanitized)
        self.assertNotIn("signature", sanitized)
        self.assertEqual(
            sanitized,
            "access_token=[REDACTED] Authorization: [REDACTED] "
            "Proxy-Authorization: [REDACTED] sig=[REDACTED]",
        )


class ChildEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_process_does_not_inherit_bot_token(self):
        user_id = 998877
        process.begin_download(user_id)
        try:
            with patch.dict(os.environ, {"BOT_TOKEN": "must-not-leak"}):
                result = await process.run_command(
                    [
                        sys.executable,
                        "-c",
                        "import os; print(os.getenv('BOT_TOKEN', 'absent'))",
                    ],
                    user_id,
                    timeout=10,
                )
            self.assertEqual(result.stdout.strip(), "absent")
        finally:
            process.finish_download(user_id)


class DiskSpacePreflightTests(unittest.TestCase):
    def test_preflight_rejects_insufficient_free_space(self):
        with patch("utils.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaises(InsufficientDiskSpaceError):
                ensure_temporary_disk_space("/tmp")

    def test_preflight_allows_sufficient_free_space(self):
        required_bytes = MAX_MB * 2 * 1024 * 1024
        with patch(
            "utils.shutil.disk_usage",
            return_value=SimpleNamespace(free=required_bytes),
        ):
            ensure_temporary_disk_space("/tmp")


class TikTokRedirectSecurityTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def response(status, url, location=None):
        headers = {"location": location} if location else {}
        return SimpleNamespace(
            status_code=status,
            headers=headers,
            url=url,
        )

    async def test_private_redirect_targets_are_rejected_before_request(self):
        unsafe_targets = (
            "http://127.0.0.1/video/123",
            "http://169.254.169.254/video/123",
            "http://192.168.1.5/video/123",
            "http://[::1]/video/123",
            "https://user:password@www.tiktok.com/@x/video/123",
            "file:///etc/passwd",
        )

        for target in unsafe_targets:
            with self.subTest(target=target):
                first_response = self.response(
                    302,
                    "https://vm.tiktok.com/short/",
                    target,
                )
                client = SimpleNamespace(
                    get=AsyncMock(return_value=first_response)
                )
                client_context = MagicMock()
                client_context.__aenter__ = AsyncMock(return_value=client)
                client_context.__aexit__ = AsyncMock(return_value=None)
                with (
                    patch("platforms.httpx.AsyncClient", return_value=client_context),
                    patch(
                        "platforms.socket.getaddrinfo",
                        return_value=[
                            (2, 1, 6, "", ("93.184.216.34", 443))
                        ],
                    ),
                ):
                    result = await resolve_tiktok_url(
                        "https://vm.tiktok.com/short/"
                    )

                self.assertIsNone(result)
                client.get.assert_awaited_once()

    async def test_safe_tiktok_redirect_is_followed_manually(self):
        short_url = "https://vm.tiktok.com/short/"
        final_url = "https://www.tiktok.com/@creator/video/123"
        client = SimpleNamespace(
            get=AsyncMock(
                side_effect=[
                    self.response(302, short_url, final_url),
                    self.response(200, final_url),
                ]
            )
        )
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("platforms.httpx.AsyncClient", return_value=client_context),
            patch(
                "platforms.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
            ),
        ):
            result = await resolve_tiktok_url(short_url)

        self.assertEqual(result, final_url)
        self.assertEqual(client.get.await_count, 2)
        self.assertTrue(
            all(call.kwargs["follow_redirects"] is False for call in client.get.await_args_list)
        )

    async def test_hostname_with_private_dns_answer_is_rejected(self):
        client = SimpleNamespace(
            get=AsyncMock(return_value=self.response(200, "https://vm.tiktok.com/a/"))
        )
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("platforms.httpx.AsyncClient", return_value=client_context),
            patch(
                "platforms.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
            ),
        ):
            result = await resolve_tiktok_url("https://vm.tiktok.com/a/")

        self.assertIsNone(result)
        client.get.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
