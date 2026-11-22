"""安全读写清理计划，并校验环境与实现摘要。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path

from .constants import PlanVersion
from .filesystem import directory_fd, signature
from .runtime import implementation_digest


def plan_file_path(value: str) -> Path:
    """规范化计划文件的父目录，支持 macOS 的 /tmp 等目录别名。"""
    path = Path(value).expanduser().absolute()
    return path.parent.resolve(strict=True) / path.name


def plan_checksum(data: dict) -> str:
    """计算规范 JSON 的摘要，用于识别计划损坏或意外编辑。"""
    content = json.dumps(data, sort_keys=True, ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


def plan_runtime() -> dict:
    """绑定当前用户、主机和脚本规则，避免跨环境沿用旧清理计划。"""
    return {
        "version": PlanVersion.CURRENT,
        "uid": os.getuid(),
        "host": os.uname().nodename,
        "platform": sys.platform,
        "home": str(Path.home().resolve()),
        "script": implementation_digest(),
    }


def read_plan(path: Path, check_script: bool = True) -> tuple[dict, tuple[int, ...]]:
    """读取当前用户持有的完整计划，返回内容及同一打开文件的身份。"""
    with directory_fd(path.parent) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("清理计划必须为当前用户持有且其他用户不可写的普通文件")
        data = json.load(stream)
        if signature(os.fstat(stream.fileno())) != signature(info):
            raise ValueError("清理计划在读取期间发生变化，请重新预览")
    if not isinstance(data, dict):
        raise ValueError("无效的清理计划格式")
    checksum = data.pop("checksum", None)
    if checksum != plan_checksum(data):
        raise ValueError("清理计划已损坏或被修改，请重新预览并保存")
    if set(data) != {"runtime", "created_at", "options", "candidates", "notes"}:
        raise ValueError("清理计划格式不完整，请重新预览并保存")
    runtime = data.get("runtime")
    expected = plan_runtime()
    if not check_script and isinstance(runtime, dict):
        expected["script"] = runtime.get("script")
    if runtime != expected:
        raise ValueError("清理计划与当前用户、主机或脚本版本不一致，请重新生成")
    return data, signature(info)


def write_plan(path: Path, data: dict, previous: tuple[int, ...] | None) -> None:
    """完整落盘后发布计划，仅在原文件未变化时刷新默认计划。"""
    temporary = f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    with directory_fd(path.parent) as parent:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            if previous is None:
                os.link(
                    temporary,
                    path.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
            else:
                current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if signature(current) != previous:
                    raise ValueError("默认清理计划在扫描期间发生变化，请重新预览")
                os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
