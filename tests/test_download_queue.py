import asyncio
import tempfile
import unittest
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import handlers
from downloader_core import process
from i18n import get_text
from telegram_handlers.queue import (
    DOWNLOAD_QUEUE,
    DownloadJob,
    DownloadQueueManager,
)
from telegram_handlers.download import get_download_semaphore
from telegram_handlers.cancellation import cancel_command
from utils import (
    DownloadDurationLimitError,
    DownloadFailedError,
    DownloadFileTooLargeError,
    InstagramRateLimitError,
)


def make_job(user_id, execute, begin=None, finish=None):
    return DownloadJob(
        user_id=user_id,
        execute=execute,
        begin=begin or Mock(),
        finish=finish or Mock(),
    )


class DownloadQueueManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_positions_capacity_and_fifo_order(self):
        manager = DownloadQueueManager(max_queued=2)
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        order = []

        async def first():
            order.append("A")
            first_started.set()
            await release_first.wait()

        async def later(label):
            order.append(label)

        self.assertEqual(
            manager.enqueue(make_job(1, first)).state,
            "started",
        )
        await asyncio.wait_for(first_started.wait(), 1)
        self.assertEqual(manager.enqueue(make_job(1, lambda: later("B"))).position, 1)
        self.assertEqual(manager.enqueue(make_job(1, lambda: later("C"))).position, 2)
        self.assertEqual(manager.enqueue(make_job(1, lambda: later("D"))).state, "full")

        release_first.set()
        await manager.wait_until_idle(1)
        self.assertEqual(order, ["A", "B", "C"])
        self.assertNotIn(1, manager.queues)
        self.assertNotIn(1, manager.workers)
        self.assertNotIn(1, manager.active_jobs)

    async def test_same_user_jobs_never_overlap_and_users_can_run_concurrently(self):
        manager = DownloadQueueManager(max_queued=2)
        semaphore = get_download_semaphore()
        first_started = asyncio.Event()
        other_user_started = asyncio.Event()
        release_first = asyncio.Event()
        release_other = asyncio.Event()
        active_by_user = defaultdict(int)
        peak_by_user = defaultdict(int)
        active_total = 0
        peak_total = 0
        job_names = []

        async def media_job(user_id, name, started, release=None):
            nonlocal active_total, peak_total
            async with semaphore:
                active_by_user[user_id] += 1
                active_total += 1
                peak_by_user[user_id] = max(
                    peak_by_user[user_id],
                    active_by_user[user_id],
                )
                peak_total = max(peak_total, active_total)
                job_names.append(name)
                started.set()
                if release is not None:
                    await release.wait()
                active_by_user[user_id] -= 1
                active_total -= 1

        manager.enqueue(
            make_job(
                10,
                lambda: media_job(10, "A1", first_started, release_first),
            )
        )
        await asyncio.wait_for(first_started.wait(), 1)
        manager.enqueue(make_job(10, lambda: media_job(10, "A2", asyncio.Event())))
        manager.enqueue(
            make_job(
                20,
                lambda: media_job(20, "B1", other_user_started, release_other),
            )
        )
        await asyncio.wait_for(other_user_started.wait(), 1)

        self.assertEqual(job_names, ["A1", "B1"])
        self.assertEqual(peak_total, 2)
        self.assertEqual(peak_by_user[10], 1)

        release_first.set()
        release_other.set()
        await asyncio.gather(
            manager.wait_until_idle(10),
            manager.wait_until_idle(20),
        )
        self.assertEqual(job_names, ["A1", "B1", "A2"])
        self.assertEqual(peak_by_user[10], 1)

    async def test_failure_advances_fifo_and_cancellation_clears_waiters(self):
        manager = DownloadQueueManager(max_queued=2)
        started = asyncio.Event()
        never_release = asyncio.Event()
        order = []

        async def blocked():
            started.set()
            await never_release.wait()

        manager.enqueue(make_job(3, blocked))
        await asyncio.wait_for(started.wait(), 1)
        manager.enqueue(make_job(3, lambda: self._record(order, "B")))
        state = manager.clear_waiting(3)
        self.assertTrue(state.had_work)
        state.worker.cancel()
        await manager.wait_until_idle(3)
        self.assertEqual(order, [])
        self.assertNotIn(3, manager.workers)
        self.assertNotIn(3, manager.queues)

        async def fail():
            order.append("fail")
            raise RuntimeError("expected test failure")

        manager.enqueue(make_job(4, fail))
        manager.enqueue(make_job(4, lambda: self._record(order, "next")))
        await manager.wait_until_idle(4)
        self.assertEqual(order, ["fail", "next"])

    async def test_cancel_before_worker_starts_does_not_run_job(self):
        manager = DownloadQueueManager(max_queued=2)
        executed = False

        async def run():
            nonlocal executed
            executed = True

        manager.enqueue(make_job(5, run))
        state = manager.clear_waiting(5)
        self.assertTrue(state.had_work)
        state.worker.cancel()
        await manager.wait_until_idle(5)
        self.assertFalse(executed)
        self.assertFalse(manager.has_work(5))

    async def test_shutdown_cancels_worker_and_discards_pending_jobs(self):
        manager = DownloadQueueManager(max_queued=2)
        started = asyncio.Event()
        never_release = asyncio.Event()
        finish = Mock()
        next_job = AsyncMock()
        stop_process = AsyncMock()

        async def active_job():
            started.set()
            await never_release.wait()

        manager.enqueue(
            make_job(6, active_job, finish=finish)
        )
        await asyncio.wait_for(started.wait(), 1)
        manager.enqueue(make_job(6, next_job))

        await manager.shutdown(stop_process)

        stop_process.assert_awaited_once_with(6)
        finish.assert_called_once()
        next_job.assert_not_awaited()
        self.assertEqual(manager.workers, {})
        self.assertEqual(manager.active_jobs, {})
        self.assertEqual(manager.queues, {})

    @staticmethod
    async def _record(order, label):
        order.append(label)


class QueuedHandlerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    USER_ID = 7800123

    async def asyncSetUp(self):
        await DOWNLOAD_QUEUE.shutdown()
        process.ACTIVE_USERS.discard(self.USER_ID)
        process.CANCEL_REQUESTS.discard(self.USER_ID)
        process.DOWNLOAD_ATTEMPTS.pop(self.USER_ID, None)

    async def asyncTearDown(self):
        await DOWNLOAD_QUEUE.shutdown(process.cancel_download)
        process.ACTIVE_USERS.discard(self.USER_ID)
        process.CANCEL_REQUESTS.discard(self.USER_ID)
        process.DOWNLOAD_ATTEMPTS.pop(self.USER_ID, None)

    def make_update(self, label):
        status = SimpleNamespace(edit_text=AsyncMock())
        message = SimpleNamespace(
            text=f"https://www.youtube.com/watch?v={label}",
            reply_text=AsyncMock(return_value=status),
            reply_video=AsyncMock(),
        )
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=self.USER_ID),
            message=message,
        )

    def common_patches(self):
        return (
            patch.object(handlers, "PUBLIC_ACCESS", True),
            patch.object(handlers, "get_user_language", return_value="en"),
            patch.object(handlers, "has_accepted_terms", return_value=True),
            patch.object(handlers, "get_daily_usage", return_value=0),
            patch.object(handlers, "get_platform", side_effect=lambda url: "youtube"),
            patch.object(handlers, "download_video"),
            patch.object(handlers, "keep_user_updated", AsyncMock()),
            patch.object(handlers, "increment_daily_usage"),
            patch.object(handlers, "get_remaining_downloads", return_value=29),
            patch("builtins.print"),
        )

    async def test_urls_enqueue_fifo_and_full_queue_is_localized(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        order = []
        upload_path = Path(tempfile.gettempdir(), "queued-test-media.mp4")
        upload_path.write_bytes(b"video")

        async def fake_download(platform, url, tmpdir, user_id):
            label = url.rsplit("=", 1)[-1]
            order.append(label)
            if label == "A":
                first_started.set()
                await release_first.wait()
                raise DownloadFailedError("first job intentionally fails")
            return str(upload_path)

        updates = [self.make_update(label) for label in "ABCD"]
        patches = list(self.common_patches())
        patches[5] = patch.object(handlers, "download_video", side_effect=fake_download)

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            await handlers.handle_url(updates[0], Mock())
            await asyncio.wait_for(first_started.wait(), 1)
            await handlers.handle_url(updates[1], Mock())
            await handlers.handle_url(updates[2], Mock())
            await handlers.handle_url(updates[3], Mock())

            updates[1].message.reply_text.assert_any_await(
                get_text("en", "download_queued", position=1)
            )
            updates[2].message.reply_text.assert_any_await(
                get_text("en", "download_queued", position=2)
            )
            updates[3].message.reply_text.assert_awaited_once_with(
                get_text("en", "download_queue_full")
            )
            release_first.set()
            await DOWNLOAD_QUEUE.wait_until_idle(self.USER_ID)

        self.assertEqual(order, ["A", "B", "C"])
        updates[1].message.reply_video.assert_awaited_once()
        updates[2].message.reply_video.assert_awaited_once()
        updates[3].message.reply_video.assert_not_awaited()
        upload_path.unlink(missing_ok=True)

    async def test_immediate_queue_add_bypasses_cooldown_but_rolling_cap_remains(self):
        now = 1000.0
        with patch("downloader_core.process.time.monotonic", return_value=now):
            self.assertTrue(process.try_record_download_attempt(self.USER_ID))
            self.assertTrue(
                process.try_record_download_attempt(
                    self.USER_ID,
                    allow_cooldown=True,
                )
            )
            for _ in range(3):
                self.assertTrue(
                    process.try_record_download_attempt(
                        self.USER_ID,
                        allow_cooldown=True,
                    )
                )
            self.assertFalse(
                process.try_record_download_attempt(
                    self.USER_ID,
                    allow_cooldown=True,
                )
            )

    async def test_failure_categories_do_not_block_later_jobs_or_count_usage(self):
        upload_path = Path(tempfile.gettempdir(), "queued-failure-test.mp4")
        upload_path.write_bytes(b"video")
        order = []
        increments = []
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def fake_download(platform, url, tmpdir, user_id):
            label = url.rsplit("=", 1)[-1]
            order.append(label)
            if label == "A":
                first_started.set()
                await release_first.wait()
                raise DownloadDurationLimitError("duration limit")
            if label == "B":
                raise DownloadFileTooLargeError("too large")
            return str(upload_path)

        updates = [self.make_update(label) for label in "ABC"]
        patches = list(self.common_patches())
        patches[5] = patch.object(handlers, "download_video", side_effect=fake_download)
        patches[7] = patch.object(
            handlers,
            "increment_daily_usage",
            side_effect=lambda user_id: increments.append(user_id),
        )

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            await handlers.handle_url(updates[0], Mock())
            await asyncio.wait_for(first_started.wait(), 1)
            await handlers.handle_url(updates[1], Mock())
            await handlers.handle_url(updates[2], Mock())
            release_first.set()
            await DOWNLOAD_QUEUE.wait_until_idle(self.USER_ID)

        self.assertEqual(order, ["A", "B", "C"])
        self.assertEqual(increments, [self.USER_ID])
        updates[2].message.reply_video.assert_awaited_once()
        upload_path.unlink(missing_ok=True)

    async def test_upload_failure_advances_to_next_job(self):
        upload_path = Path(tempfile.gettempdir(), "queued-upload-test.mp4")
        upload_path.write_bytes(b"video")
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        calls = []
        increments = []

        async def fake_download(platform, url, tmpdir, user_id):
            label = url.rsplit("=", 1)[-1]
            calls.append(label)
            if label == "A":
                first_started.set()
                await release_first.wait()
            return str(upload_path)

        first, second = self.make_update("A"), self.make_update("B")
        first.message.reply_video.side_effect = RuntimeError("upload failed")
        patches = list(self.common_patches())
        patches[5] = patch.object(handlers, "download_video", side_effect=fake_download)
        patches[7] = patch.object(
            handlers,
            "increment_daily_usage",
            side_effect=lambda user_id: increments.append(user_id),
        )

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            await handlers.handle_url(first, Mock())
            await asyncio.wait_for(first_started.wait(), 1)
            await handlers.handle_url(second, Mock())
            release_first.set()
            await DOWNLOAD_QUEUE.wait_until_idle(self.USER_ID)

        self.assertEqual(calls, ["A", "B"])
        first.message.reply_video.assert_awaited_once()
        second.message.reply_video.assert_awaited_once()
        self.assertEqual(increments, [self.USER_ID])
        upload_path.unlink(missing_ok=True)

    async def test_instagram_photo_rate_limit_advances_to_next_job(self):
        upload_path = Path(tempfile.gettempdir(), "queued-instagram-test.mp4")
        upload_path.write_bytes(b"video")
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        downloaded = []
        increments = []

        async def fake_video_download(platform, url, tmpdir, user_id):
            if "/p/" in url:
                first_started.set()
                await release_first.wait()
                raise DownloadFailedError("use existing photo fallback")
            downloaded.append(url)
            return str(upload_path)

        first, second = self.make_update("unused"), self.make_update("B")
        first.message.text = "https://www.instagram.com/p/photo-code/"
        patches = list(self.common_patches())
        patches[4] = patch.object(
            handlers,
            "get_platform",
            side_effect=lambda url: "instagram" if "/p/" in url else "youtube",
        )
        patches[5] = patch.object(
            handlers,
            "download_video",
            side_effect=fake_video_download,
        )
        patches[7] = patch.object(
            handlers,
            "increment_daily_usage",
            side_effect=lambda user_id: increments.append(user_id),
        )

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            photo_download = stack.enter_context(
                patch.object(
                    handlers,
                    "download_instagram_photo",
                    AsyncMock(
                        side_effect=InstagramRateLimitError(
                            "photo temporarily rate limited"
                        )
                    ),
                )
            )
            await handlers.handle_url(first, Mock())
            await asyncio.wait_for(first_started.wait(), 1)
            await handlers.handle_url(second, Mock())
            release_first.set()
            await DOWNLOAD_QUEUE.wait_until_idle(self.USER_ID)

        photo_download.assert_awaited_once()
        self.assertEqual(downloaded, [second.message.text])
        second.message.reply_video.assert_awaited_once()
        self.assertEqual(increments, [self.USER_ID])
        upload_path.unlink(missing_ok=True)

    async def test_cancel_before_first_job_starts_clears_pending_work(self):
        update = self.make_update("pending")
        download_video = AsyncMock()
        patches = list(self.common_patches())
        patches[5] = patch.object(
            handlers,
            "download_video",
            download_video,
        )
        cancel_message = SimpleNamespace(reply_text=AsyncMock())
        cancel_update = SimpleNamespace(
            effective_user=SimpleNamespace(id=self.USER_ID),
            message=cancel_message,
        )

        with ExitStack() as stack:
            for active_patch in patches:
                stack.enter_context(active_patch)
            await handlers.handle_url(update, Mock())
            with patch(
                "telegram_handlers.cancellation.get_language",
                return_value="en",
            ):
                await cancel_command(cancel_update, Mock())
            await DOWNLOAD_QUEUE.wait_until_idle(self.USER_ID)

        cancel_message.reply_text.assert_awaited_once_with(
            get_text("en", "download_queue_cancelled"),
            reply_markup=handlers.get_home_keyboard("en"),
        )
        download_video.assert_not_awaited()
        self.assertFalse(DOWNLOAD_QUEUE.has_work(self.USER_ID))


if __name__ == "__main__":
    unittest.main()
