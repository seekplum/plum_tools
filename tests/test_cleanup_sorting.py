"""验证 pclean 的展示排序和通用 Git 索引保护。"""

import json
import os
import subprocess
import time
from pathlib import Path
from unittest import mock

import pytest

from plum_tools._cleanup.cli import parse_args
from plum_tools._cleanup.constants import Category
from plum_tools._cleanup.execution import CleanupExecutor
from plum_tools._cleanup.filesystem import FileInspector
from plum_tools._cleanup.models import Candidate
from plum_tools._cleanup.plans import PlanStore
from plum_tools._cleanup.reporting import CleanupReporter
from plum_tools._cleanup.scanner import ProjectScanner
from plum_tools._cleanup.service import run
from plum_tools._cleanup.state import CleanupState


def _git(root: Path, *args: str) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "-C", str(root), *args], env=env, check=True, capture_output=True)  # nosec B603 B607


def _state(root: Path, *options: str) -> CleanupState:
    args = parse_args(["scan", "--root", str(root), "--save-plan", str(root / "plan.json"), *options])
    return CleanupState(args, None)


def _project_candidate(root: Path, name: str) -> tuple[Path, Path]:
    """创建现有规则可识别的项目候选，返回候选和可暂存文件。"""
    (root / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1.0"\n', encoding="utf-8")
    (root / "package.json").write_text('{"dependencies": {"example": "1.0"}}', encoding="utf-8")
    path = root / name
    if name == ".coverage":
        path.write_bytes(b"generated")
        return path, path
    path.mkdir()
    if name == ".venv":
        (path / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    content = path / "generated.bin"
    content.write_bytes(b"generated")
    return path, content


@pytest.mark.parametrize("name", [".venv", ".node_modules", "node_modules", "__pycache__", ".coverage"])
@pytest.mark.parametrize("tracking", ["outside", "untracked", "ignored", "staged", "staged-ignored"])
@pytest.mark.parametrize("fast_deps", [False, True])
def test_project_candidate_git_protection_and_explicit_notes(
    tmp_path: Path, name: str, tracking: str, fast_deps: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """文件和依赖目录统一保护暂存内容，完整与快速扫描均提示。"""
    root = tmp_path.resolve()
    path, content = _project_candidate(root, name)
    if tracking != "outside":
        _git(root, "init", "--quiet")
        if "ignored" in tracking:
            (root / ".gitignore").write_text(f"{name}\n", encoding="utf-8")
        if tracking.startswith("staged"):
            _git(root, "add", "--force", "--", str(content.relative_to(root)))
    state = _state(root, *(["--fast-deps"] if fast_deps else []))
    scanner = ProjectScanner(state, FileInspector(state))
    scanner.scan()
    assert state.errors == []
    protected = tracking.startswith("staged")
    eligible = tracking in {"outside", "ignored"}
    assert [item.path for item in state.candidates] == ([path] if eligible else [])
    notes = CleanupReporter(state).report_data()["notes"]
    if protected:
        assert len(notes) == 1
        assert "Git 已跟踪" in notes[0] and str(path) in notes[0]
        CleanupReporter(state).report()
        output = capsys.readouterr().out
        assert "Git 已跟踪" in output and name in output
    else:
        assert not any("Git 已跟踪" in note for note in notes)
        CleanupExecutor(state, scanner.inspector, scanner).revalidate()
    assert content.read_bytes() == b"generated"


def test_generated_directory_with_tracked_file_is_preserved(tmp_path: Path) -> None:
    """整个缓存目录含跟踪文件时保留目录，并报告候选路径。"""
    root = tmp_path.resolve()
    _git(root, "init", "--quiet")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "tracked.pyc").write_bytes(b"tracked")
    (cache / "untracked.pyc").write_bytes(b"cache")
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(root, "add", "--force", "--", "__pycache__/tracked.pyc")
    state = _state(root)
    ProjectScanner(state, FileInspector(state)).scan()
    assert state.candidates == []
    assert state.errors == []
    assert any(note.path == cache and "Git 已跟踪" in note.reason for note in state.notes)
    assert (cache / "tracked.pyc").read_bytes() == b"tracked"


@pytest.mark.parametrize("name", [".venv", ".node_modules", "node_modules", "__pycache__", ".coverage"])
@pytest.mark.parametrize("fast_deps", [False, True])
def test_saved_plan_refuses_files_added_to_git_after_scan(tmp_path: Path, name: str, fast_deps: bool) -> None:
    """旧计划执行前重新读取真实索引，任何回收动作开始前拒绝暂存文件。"""
    root = tmp_path.resolve()
    _git(root, "init", "--quiet")
    path, content = _project_candidate(root, name)
    (root / ".gitignore").write_text(f"{name}\n", encoding="utf-8")
    state = _state(root, *(["--fast-deps"] if fast_deps else []))
    scanner = ProjectScanner(state, FileInspector(state))
    scanner.scan()
    assert [item.path for item in state.candidates] == [path]
    PlanStore(state, scanner.inspector).save_plan()
    _git(root, "add", "--force", "--", str(content.relative_to(root)))
    args = parse_args(["run", "--from-plan", str(root / "plan.json"), "--yes"])
    with mock.patch("plum_tools._cleanup.execution.remove_candidate") as remove:
        with pytest.raises(ValueError, match="跟踪文件.*拒绝清理"):
            run(args, None)
    remove.assert_not_called()
    assert content.read_bytes() == b"generated"
    assert (root / "plan.json").is_file()


@pytest.mark.parametrize("repository", [False, True])
@pytest.mark.parametrize("project", [False, True])
@pytest.mark.parametrize("directory", [False, True])
def test_ds_store_example_does_not_add_a_cleanup_rule(
    tmp_path: Path, repository: bool, project: bool, directory: bool
) -> None:
    """举例的名称不扩展默认规则，有无项目或 Git 均保持既有识别范围。"""
    root = tmp_path.resolve()
    path = root / ".DS_Store"
    if directory:
        path.mkdir()
        (path / "keep.txt").write_text("keep", encoding="utf-8")
    else:
        path.write_bytes(b"metadata")
    if project:
        (root / "main.py").write_text("", encoding="utf-8")
    if repository:
        _git(root, "init", "--quiet")
        (root / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
    state = _state(root)
    ProjectScanner(state, FileInspector(state)).scan()
    assert state.candidates == []
    assert path.exists()


@pytest.mark.parametrize("option", ["exclude", "older-than"])
def test_project_candidate_respects_exclusion_and_age(tmp_path: Path, option: str) -> None:
    """Git 保护不改变用户的排除路径与保留时间。"""
    root = tmp_path.resolve()
    _project_candidate(root, ".coverage")
    state = _state(root, f"--{option}", ".coverage" if option == "exclude" else "30")
    ProjectScanner(state, FileInspector(state)).scan()
    assert state.candidates == []


@pytest.mark.parametrize("json_output", [False, True])
def test_cleanup_sort_preview_does_not_reorder_saved_plan(
    tmp_path: Path, json_output: bool, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """scan 和 show 均可排序，展示顺序不写回计划或改变执行清单。"""
    # 固定终端宽度，避免 rich 在窄宽度下折叠路径分割目录名导致断言失败。
    monkeypatch.setenv("COLUMNS", "200")
    root = tmp_path.resolve()
    (root / "main.py").write_text("", encoding="utf-8")
    for name, size in (("SORT_ALPHA", 2), ("SORT_BETA", 20000)):
        directory = root / name
        directory.mkdir()
        (directory / ".coverage").write_bytes(b"x" * size)
    scan_args = ["scan", "--root", str(root), "--save-plan", str(root / "plan.json"), "--sort", "path:asc"]
    if json_output:
        scan_args.append("--json")
    assert run(parse_args(scan_args), None) == 0
    scan_output = capsys.readouterr().out
    saved = (root / "plan.json").read_bytes()
    assert "SORT_BETA" in json.loads(saved)["candidates"][0]["path"]
    show_args = ["show", "--from-plan", str(root / "plan.json"), "--sort", "path:asc"]
    if json_output:
        show_args.append("--json")
    assert run(parse_args(show_args), None) == 0
    show_output = capsys.readouterr().out
    for output in (scan_output, show_output):
        if json_output:
            paths = [row["path"] for row in json.loads(output)["candidates"]]
            assert "SORT_ALPHA" in paths[0] and "SORT_BETA" in paths[1]
        else:
            assert output.index("SORT_ALPHA") < output.index("SORT_BETA")
    assert (root / "plan.json").read_bytes() == saved


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_cleanup_multifield_sort_keeps_unmeasured_last(tmp_path: Path, direction: str) -> None:
    """快速依赖的未知占用始终置后，多字段排序保持状态清单不变。"""
    root = tmp_path.resolve()
    state = _state(root, "--sort", f"size:{direction},path:asc")
    state.candidates = [
        Candidate(root / name, root, Category.PROJECT_CACHE, "缓存", "重建", size=size)
        for name, size in (("unknown", None), ("ten", 10), ("two-b", 2), ("two-a", 2))
    ]
    original = list(state.candidates)
    paths = [Path(row["path"]).name for row in CleanupReporter(state).report_data()["candidates"]]
    assert paths == (
        ["ten", "two-a", "two-b", "unknown"] if direction == "desc" else ["two-a", "two-b", "ten", "unknown"]
    )
    assert state.candidates == original


def test_user_cache_tracked_file_is_preserved_and_reported(tmp_path: Path) -> None:
    """用户缓存路径中的过期跟踪文件同样保留并提示。"""
    root = tmp_path.resolve()
    _git(root, "init", "--quiet")
    cache = root / "cache"
    cache.mkdir()
    path = cache / "old.cache"
    path.write_bytes(b"tracked")
    old = time.time() - 60 * 86400
    os.utime(path, (old, old))
    _git(root, "add", "--", "cache/old.cache")
    state = _state(root)
    ProjectScanner(state, FileInspector(state)).scan_cache(cache, Category.USER_CACHE, "用户缓存")
    assert state.candidates == []
    assert any(note.path == path and "Git 已跟踪" in note.reason for note in state.notes)


@pytest.mark.parametrize("command", ["scan", "show", "run"])
def test_cleanup_rejects_invalid_sort_before_loading_or_scanning(command: str) -> None:
    """文件计划命令均在参数解析时拒绝未知排序字段。"""
    with pytest.raises(SystemExit) as error:
        parse_args([command, "--sort", "unknown"])
    assert error.value.code == 2
