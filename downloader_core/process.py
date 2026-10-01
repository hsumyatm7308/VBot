import asyncio
import os
import signal
import subprocess

from utils import DownloadCancelledError


ACTIVE_USERS: set[int] = set()
ACTIVE_PROCESSES: dict[int, asyncio.subprocess.Process] = {}
CANCEL_REQUESTS: set[int] = set()


def begin_download(user_id: int):
    CANCEL_REQUESTS.discard(user_id)
    ACTIVE_USERS.add(user_id)


def finish_download(user_id: int):
    ACTIVE_USERS.discard(user_id)
    CANCEL_REQUESTS.discard(user_id)


def is_download_active(user_id: int) -> bool:
    return user_id in ACTIVE_USERS


def has_active_process(user_id: int) -> bool:
    process = ACTIVE_PROCESSES.get(user_id)
    return process is not None and process.returncode is None


def is_download_cancelled(user_id: int) -> bool:
    return user_id in CANCEL_REQUESTS


def raise_if_cancelled(user_id: int):
    if is_download_cancelled(user_id):
        raise DownloadCancelledError


def _signal_process(process: asyncio.subprocess.Process, sig: signal.Signals):
    if process.returncode is not None:
        return

    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.send_signal(sig)
        except ProcessLookupError:
            pass


async def _stop_process(process: asyncio.subprocess.Process):
    if process.returncode is not None:
        return

    _signal_process(process, signal.SIGTERM)

    try:
        await asyncio.wait_for(process.wait(), timeout=3)
        return
    except asyncio.TimeoutError:
        pass

    _signal_process(process, signal.SIGKILL)

    try:
        await process.wait()
    except ProcessLookupError:
        pass


async def cancel_download(user_id: int) -> bool:
    process = ACTIVE_PROCESSES.get(user_id)
    was_active = user_id in ACTIVE_USERS or process is not None

    if not was_active:
        return False

    CANCEL_REQUESTS.add(user_id)

    if process is not None:
        await _stop_process(process)

        if ACTIVE_PROCESSES.get(user_id) is process:
            ACTIVE_PROCESSES.pop(user_id, None)

    return True


async def run_command(command, user_id: int, timeout: int):
    raise_if_cancelled(user_id)

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    ACTIVE_PROCESSES[user_id] = process

    try:
        if is_download_cancelled(user_id):
            await _stop_process(process)
            raise DownloadCancelledError

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError as error:
            await _stop_process(process)
            raise subprocess.TimeoutExpired(command[0], timeout) from error
        except asyncio.CancelledError:
            await _stop_process(process)

            if is_download_cancelled(user_id):
                raise DownloadCancelledError from None

            raise
    finally:
        if ACTIVE_PROCESSES.get(user_id) is process:
            ACTIVE_PROCESSES.pop(user_id, None)

    raise_if_cancelled(user_id)

    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )
