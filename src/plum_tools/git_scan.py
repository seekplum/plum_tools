"""扫描 Git 仓库，按远程地址或目录名聚合展示本地状态。"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Generator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .utils.parser import add_compact_argument
from .utils.printer import compact_table

# 限制并发外部进程数，避免大型目录扫描耗尽系统资源。
_MAX_WORKERS = 16
# 单个 Git 命令的超时秒数，也约束网络更新等待时间。
_GIT_TIMEOUT = 30
# 一次读取所有本地分支的跟踪状态，供共用 Git 数据的目录复用。
_BRANCH_FORMAT = (
    "%(refname:short)%00%(upstream)%00%(upstream:short)%00%(upstream:track,nobracket)%00%(upstream:remotename)"
)


class RepositoryProgress(Progress):
    """展示目录发现和仓库检查进度；重定向输出时关闭动态展示。"""

    def __init__(self, console: Console) -> None:
        super().__init__(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[summary]}"),
            TimeElapsedColumn(),
            console=console,
            disable=not console.is_terminal,
            auto_refresh=console.is_terminal,
            refresh_per_second=4,
            transient=True,
        )
        self.directories = 0
        self.found = 0
        self.failed = 0
        self.completed = 0
        self.counter_lock = Lock()
        self.discovery = self.add_task("发现目录", total=None, summary="遍历 0 · 仓库 0")
        self.checking = self.add_task("检查仓库", total=None, summary="完成 0/0 · 失败 0")

    def discovered(self, found: bool) -> None:
        """累计一个已遍历目录，以 found 标记是否发现仓库并批量刷新。"""
        with self.counter_lock:
            self.directories += 1
            self.found += found
            if found or self.directories % 128 == 0:
                self.update(self.discovery, summary=f"遍历 {self.directories} · 仓库 {self.found}")
            if found:
                self.update(self.checking, summary=f"完成 {self.completed}/{self.found} · 失败 {self.failed}")

    def finish_discovery(self) -> None:
        """发现结束后固定检查总数，显示实际完成比例。"""
        with self.counter_lock:
            self.update(
                self.discovery,
                total=self.directories,
                completed=self.directories,
                summary=f"遍历 {self.directories} · 仓库 {self.found}",
            )
            self.stop_task(self.discovery)
            self.update(
                self.checking, total=self.found, summary=f"完成 {self.completed}/{self.found} · 失败 {self.failed}"
            )

    def checked(self, failed: bool) -> None:
        """按任务完成顺序累计检查数量及失败数。"""
        with self.counter_lock:
            self.failed += failed
            self.completed += 1
            self.update(self.checking, advance=1, summary=f"完成 {self.completed}/{self.found} · 失败 {self.failed}")


@dataclass
class Repository:  # pylint: disable=too-many-instance-attributes
    """保存单个仓库目录的身份、远程及完整检查结果。"""

    path: str
    common_dir: str = ""
    remote_name: str = ""
    remote_url: str = ""
    branch: str = ""
    bare: bool = False
    worktree: bool = False
    issues: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GitScanError(RuntimeError):
    """表示 Git 命令失败或超时，避免单个仓库中断整次扫描。"""


@dataclass
class DirectoryScanError:
    """分别保存出错路径和原始原因，供目录扫描错误分组展示。"""

    path: str
    reason: str


@dataclass
class _ScanReport:
    """保存两种输出共用的已筛选仓库组、重复标记和全量统计。"""

    groups: dict[str, dict[str, list[Repository]]]
    duplicates: set[str]
    summary: dict[str, int]


def write_json_result(
    command: str,
    summary: dict[str, int],
    repositories: list[dict],
    errors: list[DirectoryScanError],
    options: dict[str, object],
) -> None:
    """将 command 的仓库、目录错误、统计及选项以版本化 JSON 写入 stdout。"""
    json.dump(
        {
            "schema_version": 1,
            "command": command,
            "options": options,
            "summary": summary,
            "repositories": repositories,
            "directory_errors": [asdict(error) for error in errors],
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")


def print_directory_errors(console: Console, errors: list[DirectoryScanError], *, compact: bool = False) -> None:
    """将 errors 按原因分组展示到 console，compact 精简边框；无错误时不输出。"""
    if not errors:
        return
    grouped: dict[str, list[str]] = defaultdict(list)
    for error in errors:
        grouped[error.reason].append(error.path)
    table = Table(
        title=Text("目录扫描错误", style="bold red"),
        caption=Text(f"{len(grouped)} 种原因 · {len(errors)} 个目录"),
        expand=True,
    )
    table.add_column("出错原因", ratio=1, overflow="fold", style="red")
    table.add_column("目录", ratio=3, overflow="fold")
    if compact:
        compact_table(table)
    for reason, paths in sorted(grouped.items()):
        for index, path in enumerate(sorted(paths)):
            table.add_row(
                Text(reason if index == 0 else ""), Text(path), end_section=not compact and index == len(paths) - 1
            )
    console.print(table)


def _git(path: str, *args: str, allowed_codes: tuple[int, ...] = (0,)) -> str:
    executable = shutil.which("git")
    if not executable:
        raise GitScanError("未找到 git 可执行文件")
    env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        result = subprocess.run(  # nosec B603
            [executable, "--no-optional-locks", "-c", "color.ui=false", *args],
            cwd=path,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitScanError(f"git {args[0]} 超时（{_GIT_TIMEOUT} 秒）") from exc
    except OSError as exc:
        raise GitScanError(f"无法执行 git {args[0]}：{exc.strerror}") from exc
    if result.returncode not in allowed_codes:
        raise GitScanError(f"git {args[0]} 失败（退出码 {result.returncode}）")
    return result.stdout


def walk_directories(
    paths: list[str], errors: list[DirectoryScanError], exclude: tuple[str, ...] = ()
) -> Generator[tuple[str, list[str], list[str]], None, None]:
    """遍历 paths 中不重复的目录并剪枝；按目录名排除 exclude，错误追加至 errors。"""
    visited: set[str] = set()

    def record_error(exc: OSError) -> None:
        errors.append(DirectoryScanError(str(exc.filename or "未知目录"), exc.strerror or str(exc)))

    for path in paths:
        try:
            base = Path(path).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            reason = (exc.strerror if isinstance(exc, OSError) else None) or str(exc)
            errors.append(DirectoryScanError(path, reason))
            continue
        if not base.is_dir():
            errors.append(DirectoryScanError(str(base), "扫描路径不是目录"))
            continue
        for root, dirs, files in os.walk(base, onerror=record_error):
            if root in visited:
                dirs.clear()
                continue
            visited.add(root)
            yield root, dirs, files
            dirs[:] = [name for name in dirs if name != ".git" and name not in exclude]


def iter_repositories(
    paths: list[str],
    errors: list[DirectoryScanError],
    exclude: tuple[str, ...] = (),
    progress: RepositoryProgress | None = None,
) -> Generator[str, None, None]:
    """遍历 paths，按目录名排除 exclude，逐个返回仓库路径。
    遍历错误追加至 errors，通过 progress 更新发现数量。
    """
    for root, dirs, files in walk_directories(paths, errors, exclude):
        found = ".git" in dirs or ".git" in files
        if not found and "HEAD" in files and "config" in files and "objects" in dirs:
            found = True
            dirs.clear()
        if progress is not None:
            progress.discovered(found)
        if found:
            yield root


def normalize_remote_url(url: str, repo_path: str) -> str:
    """规范化远程地址用于聚合；本地相对地址以 repo_path 解析，移除 URL 凭据。"""
    url = url.strip()
    if "://" in url:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        path = unquote(parsed.path).rstrip("/")
        if parsed.scheme == "file":
            if host and host != "localhost":
                return f"file://{host}{path}"
            return str(Path(path).resolve())
        if not host:
            raise ValueError("远程 URL 缺少主机名")
        port = parsed.port
        default_port = {"ssh": 22, "http": 80, "https": 443, "git": 9418}.get(parsed.scheme)
        if ":" in host:
            host = f"[{host}]"
        if port and port != default_port:
            host = f"{host}:{port}"
        return f"{host}/{path.removesuffix('.git').lstrip('/')}"
    scp = re.fullmatch(r"(?:[^/@:\s]+@)?(\[[^]]+\]|[^/:\s]+):(.+)", url)
    if scp:
        host, path = scp.groups()
        return f"{host.lower()}/{path.rstrip('/').removesuffix('.git').lstrip('/')}"
    local_path = Path(url).expanduser()
    if not local_path.is_absolute():
        local_path = Path(repo_path) / local_path
    # 本地路径保留 .git，避免将两个实际不同的目录错误合并。
    return str(local_path.resolve())


def _identify_repository(path: str) -> Repository:
    repo = Repository(path)
    try:
        bare, common, git_dir = _git(
            path, "rev-parse", "--is-bare-repository", "--git-common-dir", "--git-dir"
        ).splitlines()
        repo.bare = bare == "true"
        repo.common_dir = str((Path(path) / common).resolve())
        repo.worktree = str((Path(path) / git_dir).resolve()) != repo.common_dir
        remotes = _git(path, "remote").splitlines()
        if remotes:
            repo.remote_name = min(remotes, key=lambda name: (name != "upstream", name != "origin", name))
            url = _git(path, "remote", "get-url", repo.remote_name).strip()
            if not url:
                raise GitScanError(f"远程 {repo.remote_name} 未配置地址")
            repo.remote_url = normalize_remote_url(url, path)
        else:
            repo.issues.append("无远程")
    except GitScanError as exc:
        repo.errors.append(str(exc))
    except (OSError, RuntimeError, ValueError):
        repo.errors.append("无法解析仓库路径或远程地址")
    return repo


def _read_worktree(repo: Repository, stash: bool = True) -> None:
    output = _git(
        repo.path,
        "status",
        "--porcelain=v2",
        "--branch",
        *(("--show-stash",) if stash else ()),
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
    )
    counts = dict.fromkeys(("暂存", "未暂存", "未跟踪", "冲突"), 0)
    entries = iter(output.split("\0"))
    commit = ""
    for entry in entries:
        if not entry:
            continue
        if entry.startswith("# branch.oid "):
            commit = entry.removeprefix("# branch.oid ")[:7]
        elif entry.startswith("# branch.head "):
            repo.branch = entry.removeprefix("# branch.head ")
        elif entry.startswith("# stash ") and stash:
            repo.issues.append(f"stash {entry.removeprefix('# stash ')}")
        elif entry.startswith("? "):
            counts["未跟踪"] += 1
        elif entry.startswith("u "):
            counts["冲突"] += 1
        elif entry.startswith(("1 ", "2 ")):
            code = entry[2:4]
            counts["暂存"] += code[0] != "."
            counts["未暂存"] += code[1] != "."
        # -z 模式下重命名和复制另占一个原始路径，不能将其当作状态记录。
        if entry.startswith("2 "):
            next(entries, None)
    if repo.branch == "(detached)":
        repo.branch = f"HEAD@{commit}"
        repo.issues.append("游离 HEAD")
    repo.issues.extend(f"{label} {count}" for label, count in counts.items() if count)


def _read_branches(repo: Repository, output: str) -> None:
    if not output and not repo.branch.startswith("HEAD@"):
        repo.issues.append("尚无提交")
    for line in output.splitlines():
        name, upstream, upstream_name, tracking, remote = line.split("\0")
        if not upstream:
            repo.issues.append(f"{name}：无 upstream")
            continue
        if tracking == "gone":
            repo.issues.append(f"{name}：upstream 已失效（{upstream_name}）")
            continue
        if remote == ".":
            repo.issues.append(f"{name}：跟踪本地分支（{upstream_name}）")
        differences = re.findall(r"(ahead|behind) (\d+)", tracking)
        if differences:
            labels = {"ahead": "领先", "behind": "落后"}
            summary = "，".join(f"{labels[kind]} {count}" for kind, count in differences)
            repo.issues.append(f"{name} → {upstream_name}：{summary}")


def _read_bare_status(repo: Repository, stash: bool = True) -> None:
    repo.branch = _git(repo.path, "symbolic-ref", "--quiet", "--short", "HEAD", allowed_codes=(0, 1)).strip()
    if not repo.branch:
        repo.branch = f"HEAD@{_git(repo.path, 'rev-parse', '--short', 'HEAD').strip()}"
        repo.issues.append("游离 HEAD")
    # 裸仓库没有工作区，直接读取 stash 引用的 reflog。
    if stash and _git(repo.path, "rev-parse", "--verify", "--quiet", "refs/stash", allowed_codes=(0, 1)):
        stash_count = len(_git(repo.path, "reflog", "show", "--format=%gd", "refs/stash").splitlines())
        if stash_count:
            repo.issues.append(f"stash {stash_count}")


def _read_shared_refs(repo: Repository, fetch: bool) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    if fetch:
        try:
            # 同一仓库的多个 worktree 共用引用，远程更新只执行一次。
            _git(repo.path, "fetch", "--all", "--quiet", "--no-recurse-submodules")
        except GitScanError as exc:
            errors.append(f"远程更新失败，使用缓存：{exc}")
    try:
        return _git(repo.path, "for-each-ref", f"--format={_BRANCH_FORMAT}", "refs/heads/"), errors
    except GitScanError as exc:
        errors.append(str(exc))
        return None, errors


def _scan_repository(
    path: str,
    fetch: bool,
    shared: dict[str, Future[tuple[str | None, list[str]]]],
    lock: Lock,
    stash: bool = True,
) -> Repository:
    repo = _identify_repository(path)
    if not repo.common_dir:
        return repo
    with lock:
        owner = repo.common_dir not in shared
        future = shared.setdefault(repo.common_dir, Future())
    # 首个检查线程负责共用引用；其他 worktree 等待同一个结果，避免重复 fetch 和分支查询。
    if owner:
        try:
            future.set_result(_read_shared_refs(repo, fetch))
        except Exception as exc:
            future.set_exception(exc)
            raise
    branches, errors = future.result()
    repo.errors.extend(errors)
    try:
        if repo.bare:
            _read_bare_status(repo, stash)
        else:
            _read_worktree(repo, stash)
    except GitScanError as exc:
        repo.errors.append(str(exc))
    if branches is not None:
        _read_branches(repo, branches)
    return repo


def _duplicate_remotes(repos: list[Repository]) -> set[str]:
    identities: dict[str, set[str]] = defaultdict(set)
    for repo in repos:
        if repo.remote_url and repo.common_dir:
            identities[repo.remote_url].add(repo.common_dir)
    return {remote for remote, common_dirs in identities.items() if len(common_dirs) > 1}


def _remote_host(url: str) -> str:
    if not url:
        return "无远程 / 无法识别"
    if Path(url).is_absolute() or url.startswith("file://"):
        return "本地路径"
    try:
        return urlsplit(f"//{url}").hostname or url.partition("/")[0]
    except ValueError:
        return url.partition("/")[0]


def _group_repositories(repos: list[Repository], group_by: str) -> dict[str, dict[str, list[Repository]]]:
    grouped: dict[str, dict[str, list[Repository]]] = {}
    for repo in repos:
        host = _remote_host(repo.remote_url)
        key = Path(repo.path).name if group_by == "name" else repo.remote_url or repo.path
        grouped.setdefault(host, {}).setdefault(key, []).append(repo)
    return grouped


def _group_label(
    key: str, repos: list[Repository], group_by: str, duplicates: set[str], *, compact: bool = False
) -> Text:
    if group_by == "remote":
        key = key.removeprefix(f"{_remote_host(key)}/") if repos[0].remote_url else Path(key).name
    label = Text(key, style="bold cyan")
    if any(repo.remote_url in duplicates for repo in repos):
        label.append(" · 重复克隆" if compact else "\n重复克隆", style="yellow")
    if group_by == "name" and len({repo.remote_url for repo in repos if repo.remote_url}) > 1:
        label.append(" · 同名仓库（远程不同）" if compact else "\n同名仓库（远程不同）", style="yellow")
    return label


def _repository_cells(repo: Repository, group_by: str, *, compact: bool = False) -> tuple[Text, Text, Text, Text]:
    kind = "（裸仓库）" if repo.bare else "（worktree）" if repo.worktree else ""
    remote = repo.remote_name or "—"
    if group_by == "name" and repo.remote_url:
        separator = " · " if compact else "\n"
        remote = f"{remote}{separator}{repo.remote_url}"
    status = Text((" · " if compact else "\n").join(repo.issues), style="yellow")
    for error in repo.errors:
        if status:
            status.append("\n")
        status.append(f"检查失败：{error}", style="red")
    if not repo.issues and not repo.errors:
        clean = "工作区干净，与跟踪引用一致" if not repo.bare else "与跟踪引用一致"
        if compact:
            clean = "干净 / 跟踪一致" if not repo.bare else "跟踪一致"
        status.append(clean, style="green")
    return Text(f"{repo.path}{kind}"), Text(repo.branch or "—"), Text(remote), status


def _print_host_table(
    console: Console,
    host: str,
    groups: dict[str, list[Repository]],
    group_by: str,
    duplicates: set[str],
    *,
    compact: bool = False,
) -> None:
    repos = [repo for group in groups.values() for repo in group]
    identities = {repo.common_dir for repo in repos if repo.common_dir}
    caption = f"{len(groups)} 个仓库组 · {len(repos)} 个目录 · {len(identities)} 个独立仓库"
    table = Table(title=Text(host, style="bold cyan"), caption=Text(caption), expand=True)
    if compact:
        compact_table(table)
    table.add_column("仓库", ratio=2, overflow="fold")
    table.add_column("目录", ratio=3, overflow="fold")
    table.add_column("当前分支", min_width=8, max_width=20, overflow="fold")
    table.add_column(
        "远程",
        ratio=2 if group_by == "name" else None,
        max_width=None if group_by == "name" else 20,
        no_wrap=group_by == "remote" and not compact,
        overflow="fold" if group_by == "name" or compact else "ellipsis",
    )
    table.add_column("本地 / 跟踪状态", ratio=3, overflow="fold")
    for key, group in sorted(groups.items()):
        label = _group_label(key, group, group_by, duplicates, compact=compact)
        for index, repo in enumerate(sorted(group, key=lambda item: item.path)):
            # 组内留空仓库列形成纵向合并，紧凑模式取消组间横线以节省行数。
            table.add_row(
                label if index == 0 else Text(""),
                *_repository_cells(repo, group_by, compact=compact),
                end_section=not compact and index == len(group) - 1,
            )
    console.print(table)


def _collect_repositories(
    paths: list[str],
    errors: list[DirectoryScanError],
    fetch: bool,
    exclude: tuple[str, ...] = (),
    progress: RepositoryProgress | None = None,
    stash: bool = True,
) -> list[Repository]:
    repos: list[Repository] = []
    scan_repository = partial(_scan_repository, fetch=fetch, shared={}, lock=Lock(), stash=stash)

    def report(future: Future[Repository]) -> None:
        if progress is not None:
            progress.checked(future.exception() is not None or bool(future.result().errors))

    def collect(done: set[Future[Repository]]) -> None:
        repos.extend(future.result() for future in done)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        pending: set[Future[Repository]] = set()
        for path in iter_repositories(paths, errors, exclude, progress):
            future = pool.submit(scan_repository, path)
            future.add_done_callback(report)
            pending.add(future)
            done = {future for future in pending if future.done()}
            collect(done)
            pending.difference_update(done)
            # 对未完成任务施加上限，避免仓库很多时占用无界内存。
            if len(pending) >= _MAX_WORKERS * 2:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                collect(done)
        if progress is not None:
            progress.finish_discovery()
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            collect(done)
    return sorted(repos, key=lambda repo: repo.path)


def _build_scan_report(
    repos: list[Repository],
    errors: list[DirectoryScanError],
    group_by: str,
    duplicates_only: bool,
    host_filter: re.Pattern[str] | None,
) -> _ScanReport:
    grouped = _group_repositories(repos, group_by)
    duplicates = _duplicate_remotes(repos)
    selected = {}
    for host in sorted(grouped):
        if host_filter is not None and (
            host in ("本地路径", "无远程 / 无法识别") or host_filter.fullmatch(host) is None
        ):
            continue
        groups = {
            key: group
            for key, group in grouped[host].items()
            if not duplicates_only or any(repo.remote_url in duplicates for repo in group)
        }
        if groups:
            selected[host] = groups
    return _ScanReport(
        selected,
        duplicates,
        {
            "repository_count": len(repos),
            "shown_repository_count": sum(len(group) for groups in selected.values() for group in groups.values()),
            "independent_repository_count": len({repo.common_dir for repo in repos if repo.common_dir}),
            "group_count": sum(len(groups) for groups in grouped.values()),
            "shown_group_count": sum(len(groups) for groups in selected.values()),
            "duplicate_remote_count": len(duplicates),
            "issue_repository_count": sum(bool(repo.issues or repo.errors) for repo in repos),
            "failed_repository_count": sum(bool(repo.errors) for repo in repos),
            "directory_error_count": len(errors),
        },
    )


def _scan_json_repositories(report: _ScanReport) -> list[dict]:
    return [
        {
            **asdict(repo),
            "host": host,
            "group_key": key,
            "kind": "bare" if repo.bare else "worktree" if repo.worktree else "normal",
            "duplicate_clone": repo.remote_url in report.duplicates,
            "has_issues": bool(repo.issues or repo.errors),
            "failed": bool(repo.errors),
        }
        for host, groups in report.groups.items()
        for key, group in sorted(groups.items())
        for repo in sorted(group, key=lambda item: item.path)
    ]


def _print_scan_results(  # pylint: disable=too-many-arguments
    console: Console,
    repos: list[Repository],
    errors: list[DirectoryScanError],
    group_by: str,
    duplicates_only: bool,
    fetch: bool,
    host_filter: re.Pattern[str] | None = None,
    *,
    compact: bool = False,
) -> None:
    report = _build_scan_report(repos, errors, group_by, duplicates_only, host_filter)
    console.print(
        "已启用远程更新；更新失败的仓库按缓存检查。" if fetch else "远程差异依据本地缓存引用；使用 --fetch 可先更新。"
    )
    for host, groups in report.groups.items():
        _print_host_table(console, host, groups, group_by, report.duplicates, compact=compact)
    print_directory_errors(console, errors, compact=compact)
    summary = report.summary
    console.print(
        f"扫描 {summary['repository_count']} 个目录，{summary['independent_repository_count']} 个独立仓库；"
        f"展示 {summary['shown_group_count']}/{summary['group_count']} 个仓库组，"
        f"重复远程 {summary['duplicate_remote_count']} 组，异常仓库目录 {summary['issue_repository_count']} 个，"
        f"检查失败 {summary['failed_repository_count']} 个，扫描错误 {summary['directory_error_count']} 个。"
    )


def scan_projects(  # pylint: disable=too-many-arguments
    paths: list[str],
    group_by: str = "remote",
    duplicates_only: bool = False,
    fetch: bool = False,
    exclude: tuple[str, ...] = (),
    stash: bool = True,
    host_filter: re.Pattern[str] | None = None,
    *,
    json_output: bool = False,
    compact: bool = False,
) -> None:
    """扫描 paths，按 group_by 合并并用 host_filter 筛选展示主机。
    compact 精简表格；json_output 输出 JSON 时忽略展示选项。
    """
    console = Console()
    errors: list[DirectoryScanError] = []
    with RepositoryProgress(Console(stderr=True) if json_output else console) as progress:
        repos = _collect_repositories(paths, errors, fetch, exclude, progress, stash)
    if json_output:
        report = _build_scan_report(repos, errors, group_by, duplicates_only, host_filter)
        write_json_result(
            "scan",
            report.summary,
            _scan_json_repositories(report),
            errors,
            {
                "group_by": group_by,
                "duplicates_only": duplicates_only,
                "fetch": fetch,
                "stash_checked": stash,
            },
        )
        return
    _print_scan_results(console, repos, errors, group_by, duplicates_only, fetch, host_filter, compact=compact)


def _compile_host_glob(value: str) -> re.Pattern[str]:
    return re.compile("|".join(fnmatch.translate(pattern) for pattern in value.split("|")), re.IGNORECASE)


def _compile_host_regex(value: str) -> re.Pattern[str]:
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as exc:
        raise argparse.ArgumentTypeError(f"无效的主机正则表达式：{exc}") from exc


def add_scan_parser(parser: argparse.ArgumentParser) -> None:
    """为 parser 添加必选的 check、scan 子命令及各自参数，默认检查 stash。"""
    parser.description = "递归检查 Git 仓库状态，查找重复克隆和本地差异。"  # noqa
    parser.epilog = "示例：\n  gitrepo check -p ~/PythonProjects -d\n  gitrepo scan -p ~/PythonProjects --duplicates"
    subparsers = parser.add_subparsers(dest="command", required=True, title="子命令", metavar="{check,scan}")
    check = subparsers.add_parser(
        "check",
        help="检查有工作区修改、分支差异或 stash 的仓库",
        description="检查 Git 仓库，展示有工作区修改、分支差异、stash 或检查错误的仓库。",
        epilog="示例：\n  gitrepo check -p ~/PythonProjects -d\n  gitrepo check -p . --ignore-stash --json",
    )
    scan = subparsers.add_parser(
        "scan",
        help="扫描 Git 仓库，按远程主机分表并合并展示",
        description="扫描 Git 仓库，按远程主机分表，合并展示同一仓库的多个本地克隆。",
        epilog=(
            "示例：\n"
            "  gitrepo scan -p ~/PythonProjects --duplicates\n"
            "  gitrepo scan -p . --group-by name\n"
            "  gitrepo scan -p . --host '*.xxx.net|github.com'\n"
            "  gitrepo scan -p . --host-regex '.*\\.xxx\\.net|github\\.com' --json\n\n"
            "远程地址优先使用 upstream，其次 origin，其余按名称排序选取。\n"
            "默认只与本地缓存的远程跟踪引用比较，可用 --fetch 更新引用。"
        ),
    )
    for command in (check, scan):
        add_compact_argument(command)
        command.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            help="以 JSON 输出结果，默认使用表格；进度条写入标准错误",
        )
        command.add_argument(
            "--ignore-stash",
            dest="stash",
            action="store_false",
            default=True,
            help="跳过 stash 检查，默认检查 stash",
        )
        command.add_argument(
            "-p", "--path", nargs="+", default=[str(Path.home())], help="扫描目录，可指定多个；默认用户主目录"
        )
        command.add_argument(
            "--exclude", nargs="+", default=[], help="按目录名跳过子目录，例如 node_modules .venv；默认无额外排除目录"
        )
    check.add_argument(
        "-d", "--detail", action="store_true", help="显示工作区、分支差异及 stash 的详细信息，默认仅展示摘要"
    )
    scan.add_argument(
        "--group-by",
        choices=("remote", "name"),
        default="remote",
        help="表内仓库合并依据：remote 远程地址、name 目录名；默认 remote",
    )
    scan.add_argument("--duplicates", action="store_true", help="仅展示包含重复克隆的分组，默认展示全部分组")
    scan.add_argument("--fetch", action="store_true", help="先更新所有已配置远程的引用，再检查状态；默认不更新引用")
    hosts = scan.add_mutually_exclusive_group()
    hosts.add_argument(
        "--host",
        dest="host_filter",
        type=_compile_host_glob,
        help="按通配符筛选展示主机，多个模式用 | 分隔，例如 '*.xxx.net|github.com'；默认不筛选",
    )
    hosts.add_argument(
        "--host-regex",
        dest="host_filter",
        type=_compile_host_regex,
        help="按正则完整匹配展示主机，默认不筛选，与 --host 互斥；两种匹配均不区分大小写",
    )
