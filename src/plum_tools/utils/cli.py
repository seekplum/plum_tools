"""统一 CLI 取消、进程回收及并发任务的中断协作。"""

import os
import signal
import subprocess
import sys
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import CancelledError
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from multiprocessing import Pool
from multiprocessing.pool import Pool as ProcessPool
from threading import current_thread, main_thread
from time import monotonic
from types import FrameType
from typing import Any, ParamSpec, TypeVar

# 保留入口函数的参数及返回类型。
_P = ParamSpec("_P")
# 保留入口函数的返回类型。
_R = TypeVar("_R")


@dataclass
class _Cancellation:
    cancelled: bool = False


# 每次命令独立保存取消状态，线程任务通过复制上下文共享该状态。
_ACTIVE_CANCELLATION: ContextVar[_Cancellation | None] = ContextVar("cli_cancellation", default=None)


def cancel_current() -> None:
    """标记当前命令及继承上下文的任务已取消，无活动命令时不操作。"""
    state = _ACTIVE_CANCELLATION.get()
    if state is not None:
        state.cancelled = True


def cli_entry(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """包装 CLI 入口，取消时清理终端、向 stderr 提示并以 130 退出，其他结果原样保留。"""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        state = _Cancellation()
        token = _ACTIVE_CANCELLATION.set(state)
        in_main = current_thread() is main_thread()
        previous = signal.getsignal(signal.SIGINT) or signal.SIG_DFL

        def interrupt(_signum: int, _frame: FrameType | None) -> None:
            state.cancelled = True
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            raise KeyboardInterrupt

        try:
            if in_main and previous != signal.SIG_IGN:
                signal.signal(signal.SIGINT, interrupt)
            try:
                return function(*args, **kwargs)
            except KeyboardInterrupt:
                state.cancelled = True
                if in_main:
                    signal.signal(signal.SIGINT, signal.SIG_IGN)
                with suppress(OSError):
                    sys.stderr.write("\n已取消\n")
                    sys.stderr.flush()
                raise SystemExit(130) from None
        finally:
            if in_main:
                signal.signal(signal.SIGINT, previous)
            _ACTIVE_CANCELLATION.reset(token)

    return wrapped


def _stop_process(process: subprocess.Popen[Any]) -> None:
    # 子命令独立成组，取消时一并回收 shell、SSH 等派生进程，避免只结束直接子进程。
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        pass
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


@contextmanager
def managed_process(args: str | Sequence[str], **kwargs: Any) -> Generator[subprocess.Popen[Any], None, None]:
    """启动独立进程组并返回进程，异常或取消时回收整个进程组后继续抛出异常。"""
    with subprocess.Popen(args, start_new_session=True, **kwargs) as process:  # nosec B603
        try:
            yield process
        except BaseException:
            _stop_process(process)
            raise


def _communicate(
    process: subprocess.Popen[str], data: str | None, timeout: float | None, state: _Cancellation
) -> tuple[str, str]:
    deadline = None if timeout is None else monotonic() + timeout
    while True:
        if state.cancelled:
            raise CancelledError
        remaining = None if deadline is None else deadline - monotonic()
        try:
            return process.communicate(input=data, timeout=0.1 if remaining is None else max(0, min(0.1, remaining)))
        except subprocess.TimeoutExpired as exc:
            if timeout is not None and deadline is not None and monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, timeout, output=exc.output, stderr=exc.stderr) from exc
            data = None


def run_process(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """执行捕获文本输出的子命令，CLI 内轮询取消状态；库调用沿用 subprocess.run 行为。"""
    state = _ACTIVE_CANCELLATION.get()
    if state is None:
        return subprocess.run(args, check=kwargs.pop("check", False), **kwargs)  # nosec B603
    if state.cancelled:
        raise CancelledError
    timeout = kwargs.pop("timeout", None)
    data = kwargs.pop("input", None)
    check = kwargs.pop("check", False)
    if kwargs.pop("capture_output", False):
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if data is not None:
        kwargs["stdin"] = subprocess.PIPE
    with managed_process(args, **kwargs) as process:
        output, error = _communicate(process, data, timeout, state)
        result = subprocess.CompletedProcess(args, process.returncode, output, error)
    if check:
        result.check_returncode()
    return result


def call_process(function: Callable[..., int], args: str, **kwargs: Any) -> int:
    """等待继承终端输出的命令；CLI 内托管进程组，库调用沿用传入的 call 函数。"""
    if _ACTIVE_CANCELLATION.get() is None:
        return function(args, **kwargs)
    timeout = kwargs.pop("timeout", None)
    with managed_process(args, **kwargs) as process:
        return process.wait(timeout=timeout)


def _worker_exit(_signum: int, _frame: FrameType | None) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise SystemExit(130)


def _initialize_worker() -> None:
    # 主进程统一处理 Ctrl+C；终止 worker 时先展开资源清理，避免遗留派生进程。
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _worker_exit)


def process_pool(processes: int) -> ProcessPool:
    """创建由主进程接收 Ctrl+C 的进程池，worker 终止时执行已有清理逻辑。"""
    return Pool(processes=processes, initializer=_initialize_worker)
