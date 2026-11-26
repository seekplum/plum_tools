"""定义 Git 扫描字段及保持仓库合并关系的排序。"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from plum_tools._gitrepo.constants import RepositorySortField
from plum_tools.utils.sorting import SortField, sort_items

if TYPE_CHECKING:
    from plum_tools._gitrepo.models import Repository


def _repository_value(repo: Repository, name: str) -> str | int | None:
    if name == "name":
        return Path(repo.path).name
    if name == "remote":
        return repo.remote_url
    if name in {"path", "branch"}:
        return getattr(repo, name)
    return repo.counts.get(name)


def sorted_repository_groups(
    groups: dict[str, list[Repository]], sort: list[SortField] | None
) -> dict[str, list[Repository]]:
    """返回按组内首项排列的新仓库组，保留组内排序和仓库合并关系。"""
    keys = {field.value: partial(_repository_value, name=field.value) for field in RepositorySortField}
    ordered = [
        (key, sort_items(sorted(group, key=lambda item: item.path), sort, keys))
        for key, group in sorted(groups.items())
    ]
    # 合并仓库必须相邻，以组内排序首项决定组间顺序，避免拆散克隆与 worktree。
    group_keys = {name: (lambda item, key=key: key(item[1][0])) for name, key in keys.items()}
    return dict(sort_items(ordered, sort, group_keys))
