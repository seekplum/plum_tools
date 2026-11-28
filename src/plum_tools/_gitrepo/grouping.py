"""对仓库分组、应用筛选并计算汇总。"""

import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from plum_tools._gitrepo.models import DirectoryScanError, Repository, _ScanReport
from plum_tools._gitrepo.sorting import sorted_repository_groups
from plum_tools.utils.sorting import SortField


def _remote_groups(repos: list[Repository]) -> list[list[Repository]]:
    parents = list(range(len(repos)))
    owners: dict[tuple[str, str], int] = {}

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    # 用地址和共用 Git 目录建立连通分量，保留跨主机、跨 worktree 的间接关联。
    for index, repo in enumerate(repos):
        identities = [("remote", url) for url in sorted(repo.remote_urls)]
        if repo.common_dir:
            identities.append(("common", repo.common_dir))
        for identity in identities:
            parents[root(index)] = root(owners.setdefault(identity, index))
    components: dict[int, list[Repository]] = defaultdict(list)
    for index, repo in enumerate(repos):
        components[root(index)].append(repo)
    return list(components.values())


def _repository_statuses(repo: Repository, duplicates: set[str]) -> set[str]:
    statuses = set(repo.statuses)
    if repo.worktree:
        statuses.add("worktree")
    if repo.path in duplicates:
        statuses.add("duplicate")
    if repo.issues or repo.errors:
        statuses.add("issues")
    if repo.errors:
        statuses.add("error")
    if not repo.issues and not repo.errors:
        statuses.add("clean")
    return statuses


def duplicate_groups(repos: list[Repository]) -> list[list[Repository]]:
    """返回含多个独立克隆的远程关联组，保留普通 worktree，排除子模块。"""
    return [
        group
        for group in _remote_groups([repo for repo in repos if not repo.submodule])
        if any(repo.remote_urls for repo in group) and len({repo.common_dir for repo in group if repo.common_dir}) > 1
    ]


def _remote_host(url: str) -> str:
    if not url:
        return "无远程 / 无法识别"
    if Path(url).is_absolute() or url.startswith("file://"):
        return "本地路径"
    try:
        return urlsplit(f"//{url}").hostname or url.partition("/")[0]
    except ValueError:
        return url.partition("/")[0]


def _group_repositories(remote_groups: list[list[Repository]], group_by: str) -> dict[str, dict[str, list[Repository]]]:
    grouped: dict[str, dict[str, list[Repository]]] = {}
    for repos in remote_groups:
        remote_key = min((url for repo in repos for url in repo.remote_urls), default=min(repo.path for repo in repos))
        host = _remote_host(remote_key) if any(repo.remote_urls for repo in repos) else _remote_host("")
        for repo in repos:
            key = Path(repo.path).name if group_by == "name" else remote_key
            grouped.setdefault(host, {}).setdefault(key, []).append(repo)
    return grouped


def _latest_paths(duplicate_repos: list[list[Repository]]) -> set[str]:
    latest_paths: set[str] = set()
    for group in duplicate_repos:
        latest = max((repo.commit_time for repo in group if repo.commit_time is not None), default=None)
        if latest is not None:
            latest_paths.update(repo.path for repo in group if repo.commit_time == latest)
    return latest_paths


def _build_scan_report(
    repos: list[Repository],
    errors: list[DirectoryScanError],
    group_by: str,
    statuses: tuple[str, ...],
    host_filter: re.Pattern[str] | None,
    sort: list[SortField] | None = None,
) -> _ScanReport:
    remote_groups = _remote_groups(repos)
    duplicate_repos = duplicate_groups(repos)
    duplicates = {repo.path for group in duplicate_repos for repo in group}
    grouped = _group_repositories(remote_groups, group_by)
    selected = {}
    for host in sorted(grouped):
        groups = {
            key: [
                repo
                for repo in group
                if "all" in statuses or _repository_statuses(repo, duplicates).intersection(statuses)
            ]
            for key, group in grouped[host].items()
            if host_filter is None or _matches_host(group, host_filter)
        }
        groups = {key: group for key, group in groups.items() if group}
        if groups:
            selected[host] = sorted_repository_groups(groups, sort)
    return _ScanReport(
        selected,
        duplicates,
        {
            "repository_count": len(repos),
            "shown_repository_count": sum(len(group) for groups in selected.values() for group in groups.values()),
            "independent_repository_count": len({repo.common_dir for repo in repos if repo.common_dir}),
            "group_count": sum(len(groups) for groups in grouped.values()),
            "shown_group_count": sum(len(groups) for groups in selected.values()),
            "duplicate_group_count": len(duplicate_repos),
            "issue_repository_count": sum(bool(repo.issues or repo.errors) for repo in repos),
            "failed_repository_count": sum(bool(repo.errors) for repo in repos),
            "directory_error_count": len(errors),
        },
        _latest_paths(duplicate_repos),
        {
            repo.path
            for group in duplicate_repos
            if len(latest := _latest_paths([group])) > 1
            for repo in group
            if repo.path in latest
        },
    )


def _matches_host(repos: list[Repository], host_filter: re.Pattern[str]) -> bool:
    hosts = {_remote_host(url) for repo in repos for url in repo.remote_urls} - {"本地路径", "无远程 / 无法识别"}
    return any(host_filter.fullmatch(host) for host in hosts)
