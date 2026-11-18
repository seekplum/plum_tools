"""扫描 Git 仓库，按远程地址或目录名聚合展示本地状态。"""

import argparse
import os
import re
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Generator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

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
    paths: list[str], errors: list[str], exclude: tuple[str, ...] = ()
) -> Generator[tuple[str, list[str], list[str]], None, None]:
    """遍历 paths 中不重复的目录并剪枝；按目录名排除 exclude，错误追加至 errors。"""
    visited: set[str] = set()

    def record_error(exc: OSError) -> None:
        errors.append(f"无法扫描 {exc.filename}：{exc.strerror}")

    for path in paths:
        try:
            base = Path(path).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            errors.append(f"无法解析扫描路径 {path}：{exc}")
            continue
        if not base.is_dir():
            errors.append(f"扫描路径不是目录：{base}")
            continue
        for root, dirs, files in os.walk(base, onerror=record_error):
            if root in visited:
                dirs.clear()
                continue
            visited.add(root)
            yield root, dirs, files
            dirs[:] = [name for name in dirs if name != ".git" and name not in exclude]


def iter_repositories(
    paths: list[str], errors: list[str], exclude: tuple[str, ...] = (), progress: RepositoryProgress | None = None
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


def _read_worktree(repo: Repository) -> None:
    output = _git(
        repo.path,
        "status",
        "--porcelain=v2",
        "--branch",
        "--show-stash",
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
        elif entry.startswith("# stash "):
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


def _read_bare_status(repo: Repository) -> None:
    repo.branch = _git(repo.path, "symbolic-ref", "--quiet", "--short", "HEAD", allowed_codes=(0, 1)).strip()
    if not repo.branch:
        repo.branch = f"HEAD@{_git(repo.path, 'rev-parse', '--short', 'HEAD').strip()}"
        repo.issues.append("游离 HEAD")
    # 裸仓库没有工作区，直接读取 stash 引用的 reflog。
    if _git(repo.path, "rev-parse", "--verify", "--quiet", "refs/stash", allowed_codes=(0, 1)):
        stash = len(_git(repo.path, "reflog", "show", "--format=%gd", "refs/stash").splitlines())
        if stash:
            repo.issues.append(f"stash {stash}")


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
    path: str, fetch: bool, shared: dict[str, Future[tuple[str | None, list[str]]]], lock: Lock
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
            _read_bare_status(repo)
        else:
            _read_worktree(repo)
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


def _group_label(key: str, repos: list[Repository], group_by: str, duplicates: set[str]) -> Text:
    if group_by == "remote":
        key = key.removeprefix(f"{_remote_host(key)}/") if repos[0].remote_url else Path(key).name
    label = Text(key, style="bold cyan")
    if any(repo.remote_url in duplicates for repo in repos):
        label.append("\n重复克隆", style="yellow")
    if group_by == "name" and len({repo.remote_url for repo in repos if repo.remote_url}) > 1:
        label.append("\n同名仓库（远程不同）", style="yellow")
    return label


def _repository_cells(repo: Repository, group_by: str) -> tuple[Text, Text, Text, Text]:
    kind = "（裸仓库）" if repo.bare else "（worktree）" if repo.worktree else ""
    remote = repo.remote_name or "—"
    if group_by == "name" and repo.remote_url:
        remote = f"{remote}\n{repo.remote_url}"
    status = Text("\n".join(repo.issues), style="yellow")
    for error in repo.errors:
        if status:
            status.append("\n")
        status.append(f"检查失败：{error}", style="red")
    if not repo.issues and not repo.errors:
        status.append("工作区干净，与跟踪引用一致" if not repo.bare else "与跟踪引用一致", style="green")
    return Text(f"{repo.path}{kind}"), Text(repo.branch or "—"), Text(remote), status


def _print_host_table(
    console: Console, host: str, groups: dict[str, list[Repository]], group_by: str, duplicates: set[str]
) -> None:
    repos = [repo for group in groups.values() for repo in group]
    identities = {repo.common_dir for repo in repos if repo.common_dir}
    caption = f"{len(groups)} 个仓库组 · {len(repos)} 个目录 · {len(identities)} 个独立仓库"
    table = Table(title=Text(host, style="bold cyan"), caption=Text(caption), expand=True)
    table.add_column("仓库", ratio=2, overflow="fold")
    table.add_column("目录", ratio=3, overflow="fold")
    table.add_column("当前分支", min_width=8, max_width=20, overflow="fold")
    table.add_column(
        "远程",
        ratio=2 if group_by == "name" else None,
        max_width=None if group_by == "name" else 20,
        no_wrap=group_by == "remote",
        overflow="fold" if group_by == "name" else "ellipsis",
    )
    table.add_column("本地 / 跟踪状态", ratio=3, overflow="fold")
    for key, group in sorted(groups.items()):
        label = _group_label(key, group, group_by, duplicates)
        for index, repo in enumerate(sorted(group, key=lambda item: item.path)):
            # 组内留空仓库列且不加横线，只在仓库组末尾分隔，形成纵向合并效果。
            table.add_row(
                label if index == 0 else Text(""),
                *_repository_cells(repo, group_by),
                end_section=index == len(group) - 1,
            )
    console.print(table)


def _collect_repositories(
    paths: list[str],
    errors: list[str],
    fetch: bool,
    exclude: tuple[str, ...] = (),
    progress: RepositoryProgress | None = None,
) -> list[Repository]:
    repos: list[Repository] = []
    shared: dict[str, Future[tuple[str | None, list[str]]]] = {}
    lock = Lock()

    def report(future: Future[Repository]) -> None:
        if progress is not None:
            progress.checked(future.exception() is not None or bool(future.result().errors))

    def collect(done: set[Future[Repository]]) -> None:
        repos.extend(future.result() for future in done)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        pending: set[Future[Repository]] = set()
        for path in iter_repositories(paths, errors, exclude, progress):
            future = pool.submit(_scan_repository, path, fetch, shared, lock)
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


def _print_scan_results(
    console: Console,
    repos: list[Repository],
    errors: list[str],
    group_by: str,
    duplicates_only: bool,
    fetch: bool,
) -> None:
    grouped = _group_repositories(repos, group_by)
    duplicates = _duplicate_remotes(repos)
    console.print(
        "已启用远程更新；更新失败的仓库按缓存检查。" if fetch else "远程差异依据本地缓存引用；使用 --fetch 可先更新。"
    )
    shown = 0
    for host in sorted(grouped):
        selected = {
            key: group
            for key, group in grouped[host].items()
            if not duplicates_only or any(repo.remote_url in duplicates for repo in group)
        }
        if not selected:
            continue
        _print_host_table(console, host, selected, group_by, duplicates)
        shown += len(selected)
    for error in errors:
        console.print(Text(error, style="red"))
    console.print(
        f"扫描 {len(repos)} 个目录，{len({repo.common_dir for repo in repos if repo.common_dir})} 个独立仓库；"
        f"展示 {shown}/{sum(len(groups) for groups in grouped.values())} 个仓库组，重复远程 {len(duplicates)} 组，"
        f"异常仓库目录 {sum(bool(repo.issues or repo.errors) for repo in repos)} 个，"
        f"检查失败 {sum(bool(repo.errors) for repo in repos)} 个，扫描错误 {len(errors)} 个。"
    )


def scan_projects(
    paths: list[str],
    group_by: str = "remote",
    duplicates_only: bool = False,
    fetch: bool = False,
    exclude: tuple[str, ...] = (),
) -> None:
    """扫描 paths，按远程主机分表、group_by 合并展示；可筛选重复克隆或先 fetch。"""
    console = Console()
    errors: list[str] = []
    with RepositoryProgress(console) as progress:
        repos = _collect_repositories(paths, errors, fetch, exclude, progress)
    _print_scan_results(console, repos, errors, group_by, duplicates_only, fetch)


def add_scan_parser(parser: argparse.ArgumentParser) -> None:
    """添加默认 check 和聚合 scan 子命令，子命令参数不覆盖已提供的全局选项。"""
    subparsers = parser.add_subparsers(dest="command")
    parser.set_defaults(command="check")
    check = subparsers.add_parser("check", help="检查有修改的仓库（默认，兼容原命令）")
    scan = subparsers.add_parser("scan", help="扫描 Git 仓库，按远程主机分表并合并展示")
    for command in (check, scan):
        command.add_argument("-p", "--path", nargs="+", default=argparse.SUPPRESS, help="扫描目录，可指定多个")
        command.add_argument(
            "--exclude", nargs="+", default=argparse.SUPPRESS, help="按目录名跳过子目录，例如 node_modules .venv"
        )
    check.add_argument("-d", "--detail", action="store_true", default=argparse.SUPPRESS, help="显示详细修改信息")
    check.add_argument("-s", "--stash", action="store_true", default=argparse.SUPPRESS, help="检查 stash")
    scan.add_argument(
        "--group-by",
        choices=("remote", "name"),
        default="remote",
        help="表内仓库合并依据：远程地址或目录名，默认 remote",
    )
    scan.add_argument("--duplicates", action="store_true", help="仅展示包含重复克隆的分组")
    scan.add_argument("--fetch", action="store_true", help="先更新所有已配置远程的引用，再检查状态")
