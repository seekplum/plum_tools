"""只为重复克隆读取本地历史，并按固定提交缓存比较结果。"""

import re
from itertools import combinations

from plum_tools._gitrepo.grouping import duplicate_groups
from plum_tools._gitrepo.models import GitScanError, Repository, RepositoryRelation
from plum_tools._gitrepo.repository import _git
from plum_tools.utils.git_history import CommitRelationStatus, compare_commits


def _read_head(repo: Repository) -> str:
    try:
        if not repo.commit:
            repo.commit = _git(
                repo.path, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", allowed_codes=(0, 1), local_history=True
            ).strip()
        if not repo.commit:
            return "尚无提交" if "unborn" in repo.statuses else "无法读取 HEAD 提交"
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", repo.commit):
            return "HEAD 提交 ID 无效"
    except GitScanError as exc:
        return str(exc)
    return ""


def _read_history(repo: Repository) -> tuple[set[str], str]:
    try:
        if _git(repo.path, "rev-parse", "--is-shallow-repository", local_history=True).strip() != "false":
            return set(), "浅克隆历史不完整"
        history = set(_git(repo.path, "rev-list", repo.commit, "--", local_history=True).splitlines())
        if repo.commit not in history:
            return set(), "提交历史不完整"
        return history, ""
    except GitScanError as exc:
        return set(), str(exc)


def compare_duplicate_heads(repos: list[Repository]) -> None:
    """为重复组填充逐对目录关系，读取失败时保留原因且允许完整副本补充缓存。"""
    # 同一提交的完整可达集可跨克隆复用，失败副本不占缓存，允许后续完整副本补齐。
    histories: dict[str, set[str]] = {}
    for group in duplicate_groups(repos):
        reasons = {repo.path: _read_head(repo) for repo in group}
        heads = {repo.path: repo.commit if not reasons[repo.path] else "" for repo in group}
        if len({repo.commit for repo in group if repo.commit}) > 1:
            for repo in group:
                if not reasons[repo.path] and repo.commit not in histories:
                    history, reasons[repo.path] = _read_history(repo)
                    if history:
                        histories[repo.commit] = history
        for repo in group:
            repo.commit_relations.clear()
        for left, right in combinations(group, 2):
            status, left_only, right_only = compare_commits(
                heads[left.path],
                heads[right.path],
                histories.get(left.commit, set()),
                histories.get(right.commit, set()),
            )
            reason = (
                "；".join(
                    f"{repo.path!r}：{reasons[repo.path]}"
                    for repo in (left, right)
                    if reasons[repo.path] and (not heads[repo.path] or repo.commit not in histories)
                )
                if status == CommitRelationStatus.UNKNOWN
                else ""
            )
            left.commit_relations.append(RepositoryRelation(right.path, status, left_only, right_only, reason))
            reverse = {
                CommitRelationStatus.AHEAD: CommitRelationStatus.BEHIND,
                CommitRelationStatus.BEHIND: CommitRelationStatus.AHEAD,
            }.get(status, status)
            right.commit_relations.append(RepositoryRelation(left.path, reverse, right_only, left_only, reason))
