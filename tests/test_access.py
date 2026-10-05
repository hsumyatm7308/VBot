import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram import Chat
from telegram.ext import ApplicationHandlerStop

from i18n import get_text
import handlers
from downloader_core import process
from telegram_handlers import cancellation
from telegram_handlers.cancellation import cancel_command
from telegram_handlers.download import get_download_semaphore
from telegram_handlers.access import enforce_private_chat


class PrivateChatEnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_chat_continues_normally(self):
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(type=Chat.PRIVATE),
            effective_user=SimpleNamespace(id=123),
            effective_message=SimpleNamespace(reply_text=AsyncMock()),
            callback_query=None,
        )

        await enforce_private_chat(update, Mock())

        update.effective_message.reply_text.assert_not_awaited()

    async def test_group_message_is_replied_to_and_stopped(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(type=Chat.GROUP),
            effective_user=SimpleNamespace(id=123),
            effective_message=message,
            callback_query=None,
        )

        with (
            patch(
                "telegram_handlers.access.get_language",
                return_value="en",
            ),
            self.assertRaises(ApplicationHandlerStop),
        ):
            await enforce_private_chat(update, Mock())

        message.reply_text.assert_awaited_once_with(
            get_text("en", "private_chat_only")
        )

    async def test_group_callback_gets_private_notice_and_stops(self):
        query = SimpleNamespace(answer=AsyncMock())
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(type=Chat.SUPERGROUP),
            effective_user=SimpleNamespace(id=123),
            effective_message=None,
            callback_query=query,
        )

        with (
            patch(
                "telegram_handlers.access.get_language",
                return_value="my",
            ),
            self.assertRaises(ApplicationHandlerStop),
        ):
            await enforce_private_chat(update, Mock())

        query.answer.assert_awaited_once_with(
            get_text("my", "private_chat_only"),
            show_alert=True,
        )

    def test_private_chat_message_is_localized(self):
        self.assertEqual(
            get_text("en", "private_chat_only"),
            "Please use this bot in a private chat.",
        )
        self.assertEqual(
            get_text("my", "private_chat_only"),
            "ဒီ bot ကို private chat မှာပဲ အသုံးပြုပါ။",
        )

    def test_queue_messages_are_localized(self):
        self.assertEqual(
            get_text("en", "download_queued", position=2),
            "⏳ Added to your download queue.\nPosition: 2",
        )
        self.assertEqual(
            get_text("my", "download_queued", position=2),
            "⏳ Download queue ထဲ ထည့်ပြီးပါပြီ။\nအဆင့်: 2",
        )
        self.assertEqual(
            get_text("en", "download_queue_full"),
            "Your download queue is full. Please wait for one of your "
            "current downloads to finish.",
        )
        self.assertEqual(
            get_text("my", "download_queue_full"),
            "သင့် download queue ပြည့်နေပါပြီ။ လက်ရှိ download "
            "တစ်ခုပြီးသွားတဲ့အထိ စောင့်ပေးပါ။",
        )


class DownloadConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_stops_active_process_and_clears_queue(self):
        user_id = 631234
        fake_process = SimpleNamespace(returncode=None)
        process.ACTIVE_USERS.add(user_id)
        process.ACTIVE_PROCESSES[user_id] = fake_process
        stop_process = AsyncMock()
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            message=message,
        )

        with (
            patch.object(process, "_stop_process", stop_process),
            patch.object(cancellation, "get_language", return_value="my"),
        ):
            await cancel_command(update, Mock())

        stop_process.assert_awaited_once_with(fake_process)
        message.reply_text.assert_awaited_once_with(
            get_text("my", "download_queue_cancelled"),
            reply_markup=handlers.get_home_keyboard("my"),
        )
        process.ACTIVE_USERS.discard(user_id)
        process.CANCEL_REQUESTS.discard(user_id)

    async def test_cancel_without_active_or_queued_work_keeps_existing_message(self):
        user_id = 631235
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            message=message,
        )

        with patch.object(cancellation, "get_language", return_value="en"):
            await cancel_command(update, Mock())

        message.reply_text.assert_awaited_once_with(
            get_text("en", "no_active_download"),
            reply_markup=handlers.get_home_keyboard("en"),
        )

    async def test_semaphore_caps_jobs_and_cancels_waiter(self):
        semaphore = get_download_semaphore()
        entered = 0
        two_entered = asyncio.Event()
        release = asyncio.Event()

        async def media_job():
            nonlocal entered
            async with semaphore:
                entered += 1
                if entered == 2:
                    two_entered.set()
                await release.wait()

        jobs = [asyncio.create_task(media_job()) for _ in range(3)]
        await asyncio.wait_for(two_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertEqual(entered, 2)
        self.assertFalse(jobs[2].done())

        jobs[2].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await jobs[2]

        release.set()
        await asyncio.gather(*jobs[:2])

    async def test_same_user_second_request_is_queued_while_resolving(self):
        process.ACTIVE_USERS.clear()
        process.CANCEL_REQUESTS.clear()
        started = asyncio.Event()
        keep_resolving = asyncio.Event()

        async def delayed_resolve(url):
            started.set()
            await keep_resolving.wait()
            return url

        def make_update():
            message = SimpleNamespace(
                text="https://vm.tiktok.com/example/",
                reply_text=AsyncMock(return_value=None),
                reply_video=AsyncMock(),
            )
            return SimpleNamespace(
                effective_user=SimpleNamespace(id=7451, username="private"),
                message=message,
            )

        first_update = make_update()
        second_update = make_update()

        with (
            patch.object(handlers, "PUBLIC_ACCESS", True),
            patch.object(handlers, "get_user_language", return_value="en"),
            patch.object(handlers, "has_accepted_terms", return_value=True),
            patch.object(handlers, "get_daily_usage", return_value=0),
            patch.object(handlers, "get_platform", return_value="tiktok"),
            patch.object(handlers, "resolve_tiktok_url", delayed_resolve),
            patch("builtins.print"),
        ):
            first_task = asyncio.create_task(
                handlers.handle_url(first_update, Mock())
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            await first_task

            self.assertTrue(process.is_download_active(7451))
            self.assertFalse(process.try_begin_download(7451))

            await handlers.handle_url(second_update, Mock())
            second_update.message.reply_text.assert_awaited_once_with(
                get_text(
                    "en",
                    "download_queued",
                    position=1,
                )
            )

            cancel_message = SimpleNamespace(reply_text=AsyncMock())
            cancel_update = SimpleNamespace(
                effective_user=SimpleNamespace(id=7451),
                message=cancel_message,
            )
            with patch(
                "telegram_handlers.cancellation.get_language",
                return_value="en",
            ):
                await cancel_command(cancel_update, Mock())

            cancel_message.reply_text.assert_awaited_once_with(
                get_text("en", "download_queue_cancelled"),
                reply_markup=handlers.get_home_keyboard("en"),
            )
            await handlers.DOWNLOAD_QUEUE.wait_until_idle(7451)

        self.assertFalse(process.is_download_active(7451))
        process.CANCEL_REQUESTS.clear()


if __name__ == "__main__":
    unittest.main()
