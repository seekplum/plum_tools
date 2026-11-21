"""测试 CLI 取消、进程回收及并发任务的中断协作。"""

import signal
import subprocess
from unittest import mock

import pytest

from plum_tools.utils.cli import (
    call_process,
    cancel_current,
    cli_entry,
    managed_process,
    process_pool,
    run_process,
)


def test_cancel_current_without_active_cancellation() -> None:
    """验证无活动命令时 cancel_current 不操作。"""
    # 确保没有活动的取消状态
    cancel_current()
    # 应正常执行，不抛出异常


def test_cancel_current_marks_state_cancelled() -> None:
    """验证 cancel_current 标记状态为已取消。"""
    from plum_tools.utils.cli import _ACTIVE_CANCELLATION, _Cancellation

    state = _Cancellation()
    token = _ACTIVE_CANCELLATION.set(state)
    try:
        cancel_current()
        assert state.cancelled is True
    finally:
        _ACTIVE_CANCELLATION.reset(token)


def test_cli_entry_wraps_function_normally() -> None:
    """验证 cli_entry 装饰器在正常情况下不改变函数行为。"""

    @cli_entry
    def sample_function(value: int) -> str:
        return f"result: {value}"

    result = sample_function(42)
    assert result == "result: 42"


def test_cli_entry_handles_keyboard_interrupt() -> None:
    """验证 cli_entry 装饰器在键盘中断时退出码为 130。"""

    @cli_entry
    def failing_function() -> str:
        raise KeyboardInterrupt

    with pytest.raises(SystemExit) as exc_info:
        failing_function()

    assert exc_info.value.code == 130


def test_managed_process_stops_on_exception() -> None:
    """验证 managed_process 在异常时回收进程。"""
    with (
        mock.patch("subprocess.Popen") as mock_popen,
        mock.patch("plum_tools.utils.cli._stop_process") as mock_stop,
    ):
        mock_process = mock.MagicMock()
        mock_process.__enter__.return_value = mock_process
        mock_process.__exit__.return_value = None
        mock_popen.return_value = mock_process

        with pytest.raises(RuntimeError, match="test error"):
            with managed_process(["echo", "test"]) as process:
                assert process is mock_process
                raise RuntimeError("test error")

        # 应调用 _stop_process 回收进程
        mock_stop.assert_called_once_with(mock_process)


def test_run_process_without_cancellation_uses_subprocess_run() -> None:
    """验证无取消状态时 run_process 使用 subprocess.run。"""
    from plum_tools.utils.cli import _ACTIVE_CANCELLATION

    # 确保没有活动的取消状态
    token = _ACTIVE_CANCELLATION.set(None)
    try:
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(["echo"], 0, "output", "")
            result = run_process(["echo", "test"])

            mock_run.assert_called_once()
            assert result.stdout == "output"
    finally:
        _ACTIVE_CANCELLATION.reset(token)


def test_run_process_with_cancellation_raises_cancelled_error() -> None:
    """验证有取消状态时 run_process 抛出 CancelledError。"""
    from concurrent.futures import CancelledError

    from plum_tools.utils.cli import _ACTIVE_CANCELLATION, _Cancellation

    state = _Cancellation(cancelled=True)
    token = _ACTIVE_CANCELLATION.set(state)
    try:
        with pytest.raises(CancelledError):
            run_process(["echo", "test"])
    finally:
        _ACTIVE_CANCELLATION.reset(token)


def test_run_process_with_capture_output() -> None:
    """验证 run_process 正确处理 capture_output 参数。"""
    from plum_tools.utils.cli import _ACTIVE_CANCELLATION, _Cancellation

    state = _Cancellation()
    token = _ACTIVE_CANCELLATION.set(state)
    try:
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.MagicMock()
            mock_process.__enter__.return_value = mock_process
            mock_process.__exit__.return_value = None
            mock_process.communicate.return_value = ("output", "error")
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            result = run_process(["echo", "test"], capture_output=True)

            assert result.stdout == "output"
            assert result.stderr == "error"
            mock_popen.assert_called_once_with(["echo", "test"], start_new_session=True, stdout=-1, stderr=-1)
    finally:
        _ACTIVE_CANCELLATION.reset(token)


def test_call_process_without_cancellation_uses_function() -> None:
    """验证无取消状态时 call_process 使用传入的函数。"""
    from plum_tools.utils.cli import _ACTIVE_CANCELLATION

    token = _ACTIVE_CANCELLATION.set(None)
    try:
        mock_function = mock.MagicMock(return_value=0)
        result = call_process(mock_function, "echo test")

        mock_function.assert_called_once_with("echo test")
        assert result == 0
    finally:
        _ACTIVE_CANCELLATION.reset(token)


def test_call_process_with_cancellation_uses_managed_process() -> None:
    """验证有取消状态时 call_process 使用 managed_process。"""
    from plum_tools.utils.cli import _ACTIVE_CANCELLATION, _Cancellation

    state = _Cancellation()
    token = _ACTIVE_CANCELLATION.set(state)
    try:
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_process = mock.MagicMock()
            mock_process.__enter__.return_value = mock_process
            mock_process.__exit__.return_value = None
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            result = call_process(mock.MagicMock(), "echo test")

            assert result == 0
            mock_process.wait.assert_called_once()
    finally:
        _ACTIVE_CANCELLATION.reset(token)


def test_process_pool_creates_pool_with_initializer() -> None:
    """验证 process_pool 创建带有初始化器的进程池。"""
    with mock.patch("plum_tools.utils.cli.Pool") as mock_pool:
        mock_pool.return_value = mock.MagicMock()

        process_pool(4)

        mock_pool.assert_called_once()
        call_kwargs = mock_pool.call_args[1]
        assert call_kwargs["processes"] == 4
        assert "initializer" in call_kwargs


def test_cli_entry_restores_signal_handler() -> None:
    """验证 cli_entry 在退出时恢复信号处理器。"""
    original_handler = signal.SIG_DFL

    @cli_entry
    def sample_function() -> str:
        return "done"

    with (
        mock.patch("signal.getsignal", return_value=original_handler),
        mock.patch("signal.signal") as mock_signal,
    ):
        sample_function()

        # 应调用 signal.signal 两次：设置和恢复
        assert mock_signal.call_count == 2
        # 第二次调用应恢复原始处理器
        restore_call = mock_signal.call_args_list[1]
        assert restore_call[0][1] == original_handler
