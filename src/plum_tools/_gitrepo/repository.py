"""读取单个仓库的身份、工作区状态及共用引用。"""

import os
import re
import shutil
import subprocess
from concurrent.futures import Future
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlsplit

from plum_tools._gitrepo.constants import Status
from plum_tools._gitrepo.models import GitScanError, Repository
from plum_tools.utils.cli import run_process

# 单个 Git 命令的超时秒数，也约束网络更新等待时间。
_GIT_TIMEOUT = 30


# porcelain v2 的 S 标记表示子模块；删除或类型变更时还需检查前三个模式字段中的 gitlink。
_SUBMODULE_RECORD = re.compile(r"[12u] .. (?:S|N\.\.\. (?:[0-7]{6} ){0,2}160000 )")


# 一次读取所有本地分支的跟踪状态，供共用 Git 数据的目录复用。
_BRANCH_FORMAT = (
    "%(refname:short)%00%(upstream)%00%(upstream:short)%00%(upstream:track,nobracket)%00%(upstream:remotename)"
    "%00%(committerdate:unix)"
)


def _git(path: str, *args: str, allowed_codes: tuple[int, ...] = (0,), local_history: bool = False) -> str:
    executable = shutil.which("git")
    if not executable:
        raise GitScanError("未找到 git 可执行文件")
    env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    options = ["--no-optional-locks", "-c", "color.ui=false"]
    if local_history:
        env.update(GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_NO_REPLACE_OBJECTS="1")
        options.append("--no-replace-objects")
    if args[0] == "status":
        # 父仓库的 --untracked-files 不传入子模块，进程级配置可让嵌套的 status 也扫描未跟踪文件。
        options.extend(("-c", "status.showUntrackedFiles=all"))
    try:
        result = run_process(
            [executable, *options, *args],
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


def _normalize_remote_urls(repo: Repository, name: str, output: str) -> list[str]:
    urls = []
    for value in output.splitlines():
        try:
            if not value.strip():
                raise ValueError("远程地址为空")
            urls.append(normalize_remote_url(value, repo.path))
        except (OSError, RuntimeError, ValueError):
            repo.errors.append(f"无法解析远程 {name} 的地址")
    return urls


def _read_remotes(repo: Repository, names: list[str]) -> None:
    for name in sorted(names, key=lambda item: (item != "upstream", item != "origin", item)):
        urls: list[str] = []
        for options in (("--all",), ("--push", "--all")):
            try:
                output = _git(repo.path, "remote", "get-url", *options, name)
                if not output.strip():
                    raise GitScanError(f"远程 {name} 未配置地址")
            except GitScanError as exc:
                repo.errors.append(str(exc))
                continue
            urls.extend(_normalize_remote_urls(repo, name, output))
        if urls:
            repo.remotes[name] = list(dict.fromkeys(urls))
            if not repo.remote_url:
                repo.remote_name, repo.remote_url = name, urls[0]


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
            _read_remotes(repo, remotes)
        else:
            repo.issues.append(Status.NO_REMOTE.desc)
            repo.statuses.append(Status.NO_REMOTE)
    except GitScanError as exc:
        repo.errors.append(str(exc))
    except (OSError, RuntimeError, ValueError):
        repo.errors.append("无法解析仓库路径或远程地址")
    return repo


def _submodule_detail(fields: list[str]) -> str:
    kind, flags = fields[0], fields[2]
    reasons = []
    # 指针暂存后 C 标记会消失，此时要比较 HEAD 和索引记录的 gitlink。
    if "C" in flags or (kind in ("1", "2") and fields[3:5] == ["160000", "160000"] and fields[6] != fields[7]):
        reasons.append("提交指针变更")
    if "M" in flags:
        reasons.append("已跟踪文件修改")
    if "U" in flags:
        reasons.append("含未跟踪文件")
    return f"子模块（{'、'.join(reasons)}）" if reasons else "子模块"


def _worktree_change(entry: str, original_path: str, submodule: bool) -> dict[str, str]:
    kind = entry[0]
    fields = entry.split(" ", {"1": 8, "2": 9, "u": 10, "?": 1}[kind])
    change = {"status": "??" if kind == "?" else fields[1], "path": fields[-1]}
    if submodule:
        change["submodule"] = _submodule_detail(fields)
    if kind == "2":
        change["original_path"] = original_path
    return change


def _without_worktree_pointer(entry: str) -> str:
    # C 比较子模块 HEAD 与父仓库索引；索引中已暂存的指针仍由 HEAD/索引的 gitlink 判定。
    if not entry.startswith(("1 ", "2 ")) or not entry.startswith("SC", 5) or entry[3] != "M":
        return entry
    kind, code, flags, remaining = entry.split(" ", 3)
    if flags == "SC..":
        if code == ".M":
            return ""
        code = code[0] + "."
    return f"{kind} {code} S.{flags[2:]} {remaining}"


def _set_detached_head(repo: Repository, commit: str, ignored_statuses: tuple[str, ...]) -> None:
    repo.branch = f"HEAD@{commit}"
    if "detached" not in ignored_statuses:
        repo.issues.append("游离 HEAD")
        repo.statuses.append("detached")


def _read_worktree(
    repo: Repository, stash: bool = True, *, detail: bool = False, ignored_statuses: tuple[str, ...] = ()
) -> None:
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
    file_statuses = (Status.STAGED, Status.UNSTAGED, Status.UNTRACKED, Status.CONFLICT)
    counts = dict.fromkeys(file_statuses, 0)
    submodules = 0
    repo.counts.update({"stash": 0} if stash else {})
    entries = iter(output.split("\0"))
    commit = ""
    for record in entries:
        # -z 模式下原路径另占一项，即使忽略变更也必须先消费。
        original_path = next(entries, "") if record.startswith("2 ") else ""
        entry = _without_worktree_pointer(record) if "submodule-pointer" in ignored_statuses else record
        if not entry:
            continue
        if entry.startswith("# branch.oid "):
            repo.commit = entry.removeprefix("# branch.oid ")
            repo.commit = "" if repo.commit == "(initial)" else repo.commit
            commit = repo.commit[:7]
        elif entry.startswith("# branch.head "):
            repo.branch = entry.removeprefix("# branch.head ")
        elif entry.startswith("# stash ") and stash:
            stash_count = int(entry.removeprefix("# stash "))
            repo.counts["stash"] = stash_count
            repo.issues.append(f"{Status.STASH.desc} {stash_count}")
            repo.statuses.append(Status.STASH)
        elif entry.startswith("? "):
            counts[Status.UNTRACKED] += 1
        elif entry.startswith("u "):
            counts[Status.CONFLICT] += 1
        elif entry.startswith(("1 ", "2 ")):
            code = entry[2:4]
            counts[Status.STAGED] += code[0] != "."
            counts[Status.UNSTAGED] += code[1] != "."
        submodule = _SUBMODULE_RECORD.match(entry) is not None
        submodules += submodule
        if detail and entry.startswith(("1 ", "2 ", "u ", "? ")):
            repo.changes.append(_worktree_change(entry, original_path, submodule))
    if repo.branch == "(detached)":
        _set_detached_head(repo, commit, ignored_statuses)
    repo.issues.extend(f"{status.desc} {count}" for status, count in counts.items() if count)
    if submodules:
        repo.issues.append(f"其中子模块 {submodules}")
        repo.statuses.append("submodule")
    repo.counts.update({status.value: count for status, count in counts.items()})
    repo.statuses.extend(status.value for status, count in counts.items() if count)


def _read_branches(repo: Repository, output: str, ignored_statuses: tuple[str, ...] = ()) -> None:
    repo.counts.update(ahead=0, behind=0)
    if not output and not repo.branch.startswith("HEAD@"):
        repo.issues.append("尚无提交")
        repo.statuses.append("unborn")
    for line in output.splitlines():
        name, upstream, upstream_name, tracking, remote, timestamp = line.split("\0")
        if name == repo.branch and timestamp:
            repo.commit_time = int(timestamp)
        if not upstream:
            repo.issues.append(f"{name}：无 upstream")
            repo.statuses.append("no-upstream")
            continue
        if tracking == "gone":
            repo.issues.append(f"{name}：upstream 已失效（{upstream_name}）")
            repo.statuses.append("gone")
            continue
        if remote == ".":
            repo.issues.append(f"{name}：跟踪本地分支（{upstream_name}）")
            repo.statuses.append("local-upstream")
        differences = [
            (kind, n) for kind, n in re.findall(r"(ahead|behind) (\d+)", tracking) if kind not in ignored_statuses
        ]
        for kind, count in differences:
            repo.counts[kind] += int(count)
        if differences:
            labels = {"ahead": "领先", "behind": "落后"}
            summary = "，".join(f"{labels[kind]} {count}" for kind, count in differences)
            repo.issues.append(f"{name} → {upstream_name}：{summary}")
            repo.statuses.extend(kind for kind, _ in differences)


def _read_bare_status(repo: Repository, stash: bool = True, ignored_statuses: tuple[str, ...] = ()) -> None:
    repo.counts.update(staged=0, unstaged=0, untracked=0, conflict=0)
    repo.branch = _git(repo.path, "symbolic-ref", "--quiet", "--short", "HEAD", allowed_codes=(0, 1)).strip()
    if not repo.branch:
        _set_detached_head(repo, _git(repo.path, "rev-parse", "--short", "HEAD").strip(), ignored_statuses)
    # 裸仓库没有工作区，直接读取 stash 引用的 reflog。
    if stash:
        exists = _git(repo.path, "rev-parse", "--verify", "--quiet", "refs/stash", allowed_codes=(0, 1))
        stash_count = len(_git(repo.path, "reflog", "show", "--format=%gd", "refs/stash").splitlines()) if exists else 0
        repo.counts["stash"] = stash_count
        if stash_count:
            repo.issues.append(f"{Status.STASH.desc} {stash_count}")
            repo.statuses.append(Status.STASH)


def _read_shared_refs(
    repo: Repository, fetch: bool, *, stash_details: bool = False
) -> tuple[str | None, list[str], list[str]]:
    errors: list[str] = []
    stashes: list[str] = []
    branches = None
    if fetch:
        try:
            # 同一仓库的多个 worktree 共用引用，远程更新只执行一次。
            _git(repo.path, "fetch", "--all", "--quiet", "--no-recurse-submodules")
        except GitScanError as exc:
            errors.append(f"远程更新失败，使用缓存：{exc}")
    try:
        branches = _git(repo.path, "for-each-ref", f"--format={_BRANCH_FORMAT}", "refs/heads/")
    except GitScanError as exc:
        errors.append(str(exc))
    if stash_details:
        try:
            stashes = _git(repo.path, "stash", "list").splitlines()
        except GitScanError as exc:
            errors.append(str(exc))
    return branches, stashes, errors


def _scan_repository(
    path: str,
    fetch: bool,
    shared: dict[str, Future[tuple[str | None, list[str], list[str]]]],
    lock: Lock,
    stash: bool = True,
    detail: bool = False,
    ignored_statuses: tuple[str, ...] = (),
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
            future.set_result(_read_shared_refs(repo, fetch, stash_details=stash and detail))
        except Exception as exc:
            future.set_exception(exc)
            raise
    branches, stashes, errors = future.result()
    repo.stashes = list(stashes)
    repo.errors.extend(errors)
    try:
        if repo.bare:
            _read_bare_status(repo, stash, ignored_statuses)
        else:
            _read_worktree(repo, stash, detail=detail, ignored_statuses=ignored_statuses)
        if repo.branch.startswith("HEAD@"):
            repo.commit_time = int(_git(path, "show", "-s", "--format=%ct", "HEAD").strip())
    except GitScanError as exc:
        repo.errors.append(str(exc))
    if branches is not None:
        _read_branches(repo, branches, ignored_statuses)
    return repo
