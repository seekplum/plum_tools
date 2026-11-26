"""读取仓库对并检查本地目录。"""

import argparse
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RepoStatus(StrEnum):
    """表示仓库对的四种目录存在状态。"""

    BOTH = "fork 与父仓库均存在"
    FORK_ONLY = "仅 fork 存在"
    PARENT_ONLY = "仅父仓库存在"
    NONE = "均不存在"


@dataclass(frozen=True)
class RepoRow:
    """保存来源编号、仓库对及各自命中的目标标签。"""

    index: int
    fork: str
    parent: str
    fork_hits: tuple[str, ...]
    parent_hits: tuple[str, ...]

    @property
    def status(self) -> RepoStatus:
        """根据当前行的 fork 与父仓库命中标签返回存在状态。"""
        if self.fork_hits and self.parent_hits:
            return RepoStatus.BOTH
        if self.fork_hits:
            return RepoStatus.FORK_ONLY
        if self.parent_hits:
            return RepoStatus.PARENT_ONLY
        return RepoStatus.NONE


def _repo_reference(value: str) -> str:
    parts = value.split("/")
    if (
        len(parts) != 2
        or any(part in ("", ".", "..") for part in parts)
        or any(char.isspace() or char in "\\\x00" for char in value)
    ):
        raise argparse.ArgumentTypeError(f"仓库格式无效：{value!r}，应为 owner/repo")
    return value


def _is_directory(path: Path) -> bool:
    # 只有路径缺失属于未命中，权限等读取错误必须继续上报，避免误判为仓库不存在。
    try:
        return stat.S_ISDIR(path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _resolve_targets(paths: list[str]) -> dict[str, Path]:
    targets: dict[str, Path] = {}
    for index, value in enumerate(paths, 1):
        if not value:
            raise ValueError("目标路径不能为空")
        path = Path(value).expanduser().resolve()
        if not _is_directory(path):
            raise ValueError(f"目标路径不是已存在的目录：{path}")
        targets[f"T{index}"] = path
    return targets


def _load_pairs(path: Path) -> tuple[list[tuple[int, str, str]], int]:
    pairs: list[tuple[int, str, str]] = []
    skipped = 0
    with path.open(encoding="utf-8-sig") as source:
        for line_no, line in enumerate(source, 1):
            parts = line.split()
            if not parts:
                continue
            if len(parts) < 2:
                skipped += 1
                continue
            try:
                fork, parent = (_repo_reference(value) for value in parts[:2])
            except argparse.ArgumentTypeError:
                skipped += 1
                continue
            pairs.append((line_no, fork, parent))
    return pairs, skipped


def _find_repo(repo: str, targets: dict[str, Path]) -> tuple[str, ...]:
    owner, name = repo.split("/")
    return tuple(
        label for label, root in targets.items() if _is_directory(root / owner / name) or _is_directory(root / name)
    )
