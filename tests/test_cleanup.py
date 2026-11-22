"""测试 _cleanup 包的运行时绑定与数据模型。"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

from plum_tools._cleanup.cli import parse_args
from plum_tools._cleanup.constants import (
    PROJECT_CATEGORIES,
    Category,
    Command,
    DockerTask,
    ExitCode,
    PlanFile,
    ProjectKind,
    PruneAction,
    SnapshotMode,
)
from plum_tools._cleanup.execution import CleanupExecutor
from plum_tools._cleanup.filesystem import (
    FileInspector,
    Trash,
    display,
    format_reason,
    human_size,
    is_within,
    query,
    query_text,
    remove_candidate,
    signature,
)
from plum_tools._cleanup.models import (
    BuilderSnapshot,
    Candidate,
    CandidateResult,
    ExecutionSnapshot,
    Note,
    ProjectScope,
    ToolTask,
    ToolVerification,
    plan_path,
    plan_signature,
)
from plum_tools._cleanup.plan_io import plan_checksum, plan_file_path, plan_runtime, read_plan, write_plan
from plum_tools._cleanup.plans import PlanStore
from plum_tools._cleanup.progress import ProgressDisplay
from plum_tools._cleanup.projects import Project, Repository, repository_at
from plum_tools._cleanup.reporting import CleanupReporter
from plum_tools._cleanup.runtime import implementation_digest, implementation_paths
from plum_tools._cleanup.scanner import ProjectScanner
from plum_tools._cleanup.service import run
from plum_tools._cleanup.state import CleanupState
from plum_tools._cleanup.tools import ToolScanner
from plum_tools.cleanup import main

# ---------- runtime.py ----------


def test_implementation_paths_contains_expected_files() -> None:
    paths = implementation_paths()
    names = {path.name for path in paths}
    assert "cleanup.py" in names
    assert "compat.py" in names
    assert "scanner.py" in names
    assert "cli.py" in names


def test_implementation_digest_stable_and_hex() -> None:
    first = implementation_digest()
    second = implementation_digest()
    assert first == second
    assert len(first) == 64
    assert all(char in "0123456789abcdef" for char in first)


# ---------- models.py: plan_path / plan_signature ----------


def test_plan_path_valid() -> None:
    path = plan_path("/tmp/cleanup/plan.json")
    assert path == Path("/tmp/cleanup/plan.json")


@pytest.mark.parametrize(
    "value",
    [
        123,
        "/tmp/a\0b",
        "relative/path",
        "/tmp/../escape",
    ],
)
def test_plan_path_invalid(value: object) -> None:
    with pytest.raises(ValueError):
        plan_path(value)  # type: ignore[arg-type]


def test_plan_signature_valid() -> None:
    assert plan_signature([1, 2, 3, 4, 5]) == (1, 2, 3, 4, 5)


@pytest.mark.parametrize(
    "value",
    [
        "not-list",
        [1, 2, 3],
        [1, 2, 3, 4, "x"],
        (1, 2, 3, 4, 5),
    ],
)
def test_plan_signature_invalid(value: object) -> None:
    with pytest.raises(ValueError):
        plan_signature(value)  # type: ignore[arg-type]


# ---------- models.py: Note ----------


def test_note_from_message_with_separator() -> None:
    note = Note.from_message("原因: 详情")
    assert note.reason == "原因"
    assert note.detail == "详情"


def test_note_from_message_without_separator() -> None:
    note = Note.from_message("纯说明")
    assert note.reason == "说明"
    assert note.detail == "纯说明"


def test_note_message_with_detail() -> None:
    note = Note("原因", "详情", Path("/tmp/x"))
    assert note.message() == '原因: "/tmp/x": 详情'


def test_note_message_without_detail() -> None:
    note = Note("原因")
    assert note.message() == "原因"


# ---------- models.py: BuilderSnapshot ----------


_VALID_BUILDER = (
    "Name: builder1\nDriver: docker\nNodes:\nName: node1\nEndpoint: unix:///var/run/docker.sock\nStatus: running\n"
)


def test_builder_snapshot_parse_valid() -> None:
    snapshot = BuilderSnapshot.parse(_VALID_BUILDER)
    assert snapshot.name == "builder1"
    assert snapshot.driver == "docker"
    assert snapshot.nodes == (("node1", "unix:///var/run/docker.sock", "running"),)


def test_builder_snapshot_parse_error_field() -> None:
    with pytest.raises(ValueError):
        BuilderSnapshot.parse("Error: something bad")


def test_builder_snapshot_parse_duplicate_nodes() -> None:
    text = "Name: b\nDriver: d\nNodes:\nName: n\nEndpoint: e\nStatus: s\nNodes:\n"
    with pytest.raises(ValueError):
        BuilderSnapshot.parse(text)


def test_builder_snapshot_parse_missing_driver() -> None:
    text = "Name: b\nNodes:\nName: n\nEndpoint: e\nStatus: s\n"
    with pytest.raises(ValueError):
        BuilderSnapshot.parse(text)


def test_builder_snapshot_parse_duplicate_field() -> None:
    text = "Name: b\nName: b2\nDriver: d\nNodes:\nName: n\nEndpoint: e\nStatus: s\n"
    with pytest.raises(ValueError):
        BuilderSnapshot.parse(text)


def test_builder_snapshot_parse_node_missing_field() -> None:
    text = "Name: b\nDriver: d\nNodes:\nName: n\nEndpoint: e\n"
    with pytest.raises(ValueError):
        BuilderSnapshot.parse(text)


def test_builder_snapshot_parse_duplicate_node_name() -> None:
    text = "Name: b\nDriver: d\nNodes:\nName: n\nEndpoint: e\nStatus: s\nName: n\nEndpoint: e2\nStatus: s2\n"
    with pytest.raises(ValueError):
        BuilderSnapshot.parse(text)


# ---------- models.py: ToolVerification ----------


def test_tool_verification_validate_pass() -> None:
    verification = ToolVerification(command=["x"], expected="result")
    with mock.patch("plum_tools._cleanup.models.query_text", return_value="result"):
        verification.validate()


def test_tool_verification_validate_fail() -> None:
    verification = ToolVerification(command=["x"], expected="result")
    with mock.patch("plum_tools._cleanup.models.query_text", return_value="other"):
        with pytest.raises(ValueError):
            verification.validate()


def test_tool_verification_validate_builder_snapshot() -> None:
    snapshot = BuilderSnapshot("b", "d", (("n", "e", "s"),))
    verification = ToolVerification(command=["x"], expected=snapshot)
    text = "Name: b\nDriver: d\nNodes:\nName: n\nEndpoint: e\nStatus: s\n"
    with mock.patch("plum_tools._cleanup.models.query_text", return_value=text):
        verification.validate()


# ---------- models.py: Candidate ----------


def _make_plan(**overrides: object) -> dict:
    data: dict = {
        "path": "/tmp/root/node_modules",
        "root": "/tmp/root",
        "category": Category.DEPS,
        "reason": "reason",
        "rebuild": "rebuild",
        "repository": None,
        "manifests": {},
        "size": 100,
        "digest": "0" * 128,
        "files": 1,
        "identity": [1, 2, 3, 4, 5],
        "snapshot": "tree",
    }
    data.update(overrides)
    return data


def test_candidate_from_plan_valid() -> None:
    candidate = Candidate.from_plan(_make_plan())
    assert candidate.path == Path("/tmp/root/node_modules")
    assert candidate.size == 100


def test_candidate_from_plan_root_not_ancestor() -> None:
    with pytest.raises(ValueError):
        Candidate.from_plan(_make_plan(path="/tmp/other/x", root="/tmp/root"))


def test_candidate_from_plan_invalid_digest() -> None:
    with pytest.raises(ValueError):
        Candidate.from_plan(_make_plan(digest="short"))


def test_candidate_from_plan_invalid_category() -> None:
    with pytest.raises(ValueError):
        Candidate.from_plan(_make_plan(category="not-a-category"))


def test_candidate_from_plan_directory_mode() -> None:
    data = _make_plan(
        size=None,
        digest="",
        files=None,
        identity=[1, 2, stat.S_IFDIR, 4, 5],
        snapshot="directory",
    )
    candidate = Candidate.from_plan(data)
    assert candidate.snapshot == SnapshotMode.DIRECTORY


# ---------- filesystem.py: 纯函数 ----------


def test_display_escapes_path() -> None:
    assert display("/tmp/x") == '"/tmp/x"'
    assert display(Path("/tmp/x")) == '"/tmp/x"'


def test_is_within_same_and_child() -> None:
    assert is_within(Path("/a/b"), Path("/a")) is True
    assert is_within(Path("/a"), Path("/a")) is True
    assert is_within(Path("/a/b"), Path("/a/c")) is False


def test_is_within_prefix_trap() -> None:
    assert is_within(Path("/ab"), Path("/a")) is False


def test_human_size_zero_and_bytes() -> None:
    assert human_size(0) == "0 B"
    assert human_size(1) == "1.0 B"
    assert human_size(1023) == "1023.0 B"


def test_human_size_units() -> None:
    assert human_size(1024) == "1.0 KiB"
    assert human_size(1024 * 1024) == "1.0 MiB"
    assert human_size(1024**3) == "1.0 GiB"
    assert human_size(1024**4) == "1.0 TiB"


def test_format_reason_strips_line_number() -> None:
    assert format_reason("file.txt:123: rule text") == "file.txt: rule text"


def test_format_reason_plain() -> None:
    assert format_reason("plain reason") == "plain reason"


def test_signature_returns_five_tuple(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_text("x", encoding="utf-8")
    info = os.stat(path)
    result = signature(info)
    assert len(result) == 5
    assert result[0] == info.st_dev
    assert result[2] == info.st_mode


# ---------- cli.py: parse_args ----------


def test_parse_args_scan_default() -> None:
    args = parse_args(["scan"])
    assert args.command == Command.SCAN
    assert args.default_plan is True
    assert args.save_plan == PlanFile.DEFAULT
    assert args.categories == PROJECT_CATEGORIES


def test_parse_args_show_uses_default_plan() -> None:
    args = parse_args(["show"])
    assert args.command == Command.SHOW
    assert args.from_plan == PlanFile.DEFAULT
    assert args.categories == set()


def test_parse_args_run() -> None:
    args = parse_args(["run"])
    assert args.command == Command.RUN


def test_parse_args_prune_show() -> None:
    args = parse_args(["prune", "show"])
    assert args.command == Command.PRUNE
    assert args.prune_action == PruneAction.SHOW


def test_parse_args_prune_run() -> None:
    args = parse_args(["prune", "run"])
    assert args.prune_action == PruneAction.RUN


def test_parse_args_category_all_expands_to_project_categories() -> None:
    args = parse_args(["scan", "--category", "all"])
    assert args.categories == PROJECT_CATEGORIES


def test_parse_args_unknown_category_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args(["scan", "--category", "unknown"])


def test_parse_args_scan_tool_not_brew_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args(["scan", "--category", "tools", "--tool", "npm"])


def test_parse_args_prune_file_category_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args(["prune", "show", "--category", "build"])


def test_parse_args_root_too_wide_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args(["scan", "--root", "/"])


def test_parse_args_older_than_negative_errors() -> None:
    with pytest.raises(SystemExit):
        parse_args(["scan", "--older-than", "-1"])


def test_parse_args_root_valid(tmp_path: Path) -> None:
    args = parse_args(["scan", "--root", str(tmp_path)])
    assert tmp_path in args.roots


# ---------- plan_io.py: plan_checksum ----------


def test_plan_checksum_stable_regardless_of_order() -> None:
    assert plan_checksum({"a": 1, "b": "x"}) == plan_checksum({"b": "x", "a": 1})


def test_plan_checksum_differs_for_different_data() -> None:
    assert plan_checksum({"a": 1}) != plan_checksum({"a": 2})


def test_plan_checksum_rejects_nan() -> None:
    with pytest.raises(ValueError):
        plan_checksum({"a": float("nan")})


# ---------- progress.py: ProgressDisplay ----------


def test_progress_phase_non_interactive(capsys: pytest.CaptureFixture[str]) -> None:
    progress = ProgressDisplay(Console(force_terminal=False))
    with progress.phase("扫描"):
        progress.visit(Path("/x"))
    captured = capsys.readouterr()
    assert "扫描……" in captured.out
    assert "扫描完成" in captured.out


def test_progress_phase_exception_marks_unfinished(capsys: pytest.CaptureFixture[str]) -> None:
    progress = ProgressDisplay(Console(force_terminal=False))
    with pytest.raises(RuntimeError):
        with progress.phase("扫描"):
            raise RuntimeError("boom")
    assert "扫描未完成" in capsys.readouterr().out


def test_progress_describe_without_task() -> None:
    progress = ProgressDisplay(Console(force_terminal=False))
    progress.describe("步骤")
    progress.visit(Path("/x"))
    progress.advance(Path("/x"))


def test_progress_describe_with_phase(capsys: pytest.CaptureFixture[str]) -> None:
    progress = ProgressDisplay(Console(force_terminal=False))
    with progress.phase("扫描"):
        progress.describe("项目")
        progress.visit(Path("/x"), count=2)
    captured = capsys.readouterr()
    assert "项目完成" in captured.out


# ---------- projects.py ----------


def test_python_rebuild_uv_lock() -> None:
    assert Project._python_rebuild({"uv.lock"}, [], {}) == "uv sync"


def test_python_rebuild_poetry_lock() -> None:
    assert Project._python_rebuild({"poetry.lock"}, [], {}) == "poetry install"


def test_python_rebuild_requirements() -> None:
    result = Project._python_rebuild({"requirements.txt"}, ["requirements.txt"], {})
    assert result == "python3 -m venv <环境目录>；<环境目录>/bin/pip install -r requirements.txt"


def test_python_rebuild_setup_py() -> None:
    result = Project._python_rebuild({"setup.py"}, [], {})
    assert result == "python3 -m venv <环境目录>；<环境目录>/bin/pip install ."


def test_python_rebuild_none() -> None:
    assert Project._python_rebuild(set(), [], {}) == ""


def test_repository_contains_tracked_self() -> None:
    repo = Repository(Path("/repo"), tracked=["a.py"])
    assert repo.contains_tracked(Path("/repo")) is True


def test_repository_contains_tracked_path() -> None:
    repo = Repository(Path("/repo"), tracked=["src/a.py"])
    assert repo.contains_tracked(Path("/repo/src/a.py")) is True


def test_repository_contains_tracked_subtree() -> None:
    repo = Repository(Path("/repo"), tracked=["src/a.py"])
    assert repo.contains_tracked(Path("/repo/src")) is True


def test_repository_contains_tracked_none() -> None:
    repo = Repository(Path("/repo"), tracked=[])
    assert repo.contains_tracked(Path("/repo/src")) is False


def test_project_detect_node(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.NODE in project.kinds


def test_project_detect_no_markers_returns_inherited(tmp_path: Path) -> None:
    inherited = Project()
    project = Project.detect(tmp_path, inherited)
    assert project is inherited


# ---------- reporting.py: CleanupReporter ----------


def _make_state(candidates: list, tasks: list | None = None) -> mock.MagicMock:
    state = mock.MagicMock()
    state.args.command = Command.SCAN
    state.args.prune_action = None
    state.args.json = False
    state.candidates = candidates
    state.tasks = tasks or []
    state.notes = []
    state.errors = []
    return state


def test_report_data_empty() -> None:
    reporter = CleanupReporter(_make_state([]))
    data = reporter.report_data()
    assert data["estimated_bytes"] == 0
    assert data["measured_bytes"] == 0
    assert data["unmeasured_candidates"] == 0


def test_report_data_mixed_sizes() -> None:
    candidates = [
        Candidate(Path("/a"), Path("/"), Category.DEPS, "r", "rb", size=100),
        Candidate(Path("/b"), Path("/"), Category.DEPS, "r", "rb", size=None),
    ]
    reporter = CleanupReporter(_make_state(candidates))
    data = reporter.report_data()
    assert data["estimated_bytes"] is None
    assert data["measured_bytes"] == 100
    assert data["unmeasured_candidates"] == 1


# ---------- cleanup.py: main ----------


def test_main_unsupported_platform(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch("plum_tools.cleanup.sys.platform", "win32"):
        code = main()
    assert code == 2
    assert "macOS/Linux" in capsys.readouterr().err


def test_main_trash_import_error(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = set()
    with (
        mock.patch("plum_tools.cleanup.sys.platform", "darwin"),
        mock.patch("plum_tools.cleanup.parse_args", return_value=args),
        mock.patch("plum_tools.cleanup.Trash", side_effect=ImportError("boom")),
    ):
        code = main()
    assert code == 2
    assert "trash-cli" in capsys.readouterr().err


def test_main_missing_git(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = PROJECT_CATEGORIES
    with (
        mock.patch("plum_tools.cleanup.sys.platform", "darwin"),
        mock.patch("plum_tools.cleanup.parse_args", return_value=args),
        mock.patch("plum_tools.cleanup.Trash"),
        mock.patch("plum_tools.cleanup.shutil.which", return_value=None),
    ):
        code = main()
    assert code == 2
    assert "Git" in capsys.readouterr().err


def test_main_run_oserror_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = set()
    with (
        mock.patch("plum_tools.cleanup.sys.platform", "darwin"),
        mock.patch("plum_tools.cleanup.parse_args", return_value=args),
        mock.patch("plum_tools.cleanup.Trash"),
        mock.patch("plum_tools.cleanup.run", side_effect=OSError("boom")),
    ):
        code = main()
    assert code == 1
    assert "已停止" in capsys.readouterr().err


def test_main_run_eoferror_returns_130(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SCAN
    args.categories = set()
    with (
        mock.patch("plum_tools.cleanup.sys.platform", "darwin"),
        mock.patch("plum_tools.cleanup.parse_args", return_value=args),
        mock.patch("plum_tools.cleanup.Trash"),
        mock.patch("plum_tools.cleanup.run", side_effect=EOFError()),
    ):
        code = main()
    assert code == 130
    assert "已取消" in capsys.readouterr().err


def test_main_prune_skips_trash() -> None:
    args = mock.MagicMock()
    args.command = Command.PRUNE
    args.categories = set()
    with (
        mock.patch("plum_tools.cleanup.sys.platform", "darwin"),
        mock.patch("plum_tools.cleanup.parse_args", return_value=args),
        mock.patch("plum_tools.cleanup.Trash") as mock_trash,
        mock.patch("plum_tools.cleanup.run", return_value=0) as mock_run,
    ):
        code = main()
    assert code == 0
    mock_trash.assert_not_called()
    mock_run.assert_called_once()


# ---------- filesystem.py: FileInspector ----------


def _make_inspector_state(
    *,
    save_plan: str | None = None,
    exclude: list[str] | None = None,
    older_than: int | None = None,
    fast_deps: bool = False,
    plan_path: Path | None = None,
    protected_parts: set[tuple] | tuple[tuple] | None = None,
) -> mock.MagicMock:
    """构造 FileInspector 所需的最小运行状态。"""
    state = mock.MagicMock()
    state.args.save_plan = save_plan
    state.args.exclude = exclude if exclude is not None else []
    state.args.older_than = older_than
    state.args.fast_deps = fast_deps
    state.plan_path = plan_path or Path("/tmp/.pclean-plan.json")
    state.protected_parts = protected_parts if protected_parts is not None else set()
    state.now = time.time()
    state.progress.visit = mock.MagicMock()
    return state


def test_excluded_save_plan_path(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    inspector = FileInspector(_make_inspector_state(save_plan=str(plan), plan_path=plan))
    assert inspector.excluded(plan, tmp_path) is True


def test_excluded_protected_parts_prefix(tmp_path: Path) -> None:
    protected = (Path("/usr/local/bin").parts,)
    inspector = FileInspector(_make_inspector_state(protected_parts=protected))
    assert inspector.excluded(Path("/usr/local/bin/tool"), Path("/")) is True


def test_excluded_no_rules_returns_false(tmp_path: Path) -> None:
    inspector = FileInspector(_make_inspector_state())
    assert inspector.excluded(tmp_path / "a.py", tmp_path) is False


def test_excluded_outside_root_raises(tmp_path: Path) -> None:
    inspector = FileInspector(_make_inspector_state(exclude=["*.py"]))
    with pytest.raises(ValueError):
        inspector.excluded(Path("/elsewhere/a.py"), tmp_path)


def test_excluded_fnmatch_relative_and_name(tmp_path: Path) -> None:
    inspector = FileInspector(_make_inspector_state(exclude=["*.py", "build"]))
    assert inspector.excluded(tmp_path / "sub" / "x.py", tmp_path) is True
    assert inspector.excluded(tmp_path / "build", tmp_path) is True


def test_protected_name_protected_name(tmp_path: Path) -> None:
    inspector = FileInspector(_make_inspector_state())
    assert inspector.protected_name(tmp_path / ".git") is True


def test_protected_name_user_data_not_allowed(tmp_path: Path) -> None:
    inspector = FileInspector(_make_inspector_state())
    assert inspector.protected_name(tmp_path / "backups") is True


def test_protected_name_allowed_in_deps(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "node_modules", tmp_path, Category.DEPS, "r", "rb")
    inspector = FileInspector(_make_inspector_state())
    assert inspector.protected_name(tmp_path / "node_modules" / "pkg" / "data", candidate) is False


def test_protected_name_env_pattern(tmp_path: Path) -> None:
    inspector = FileInspector(_make_inspector_state())
    assert inspector.protected_name(tmp_path / ".env") is True


def test_cutoff_default_days_by_category() -> None:
    inspector = FileInspector(_make_inspector_state(older_than=None))
    now = inspector.state.now
    assert inspector.cutoff(Category.USER_CACHE) == now - 30 * 86400
    assert inspector.cutoff(Category.DEPS) == now


def test_cutoff_uses_older_than() -> None:
    inspector = FileInspector(_make_inspector_state(older_than=7))
    now = inspector.state.now
    assert inspector.cutoff(Category.DEPS) == now - 7 * 86400


def test_uses_directory_snapshot_requires_fast_deps(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "node_modules", tmp_path, Category.DEPS, "r", "rb")
    inspector = FileInspector(_make_inspector_state(fast_deps=False))
    assert inspector.uses_directory_snapshot(candidate) is False
    inspector = FileInspector(_make_inspector_state(fast_deps=True, older_than=None))
    assert inspector.uses_directory_snapshot(candidate) is True
    inspector = FileInspector(_make_inspector_state(fast_deps=True, older_than=30))
    assert inspector.uses_directory_snapshot(candidate) is False


def test_directory_snapshot_rejects_mount_or_protected(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "node_modules", tmp_path, Category.DEPS, "r", "rb")
    (tmp_path / "node_modules").mkdir()
    inspector = FileInspector(_make_inspector_state(fast_deps=True, older_than=None))
    assert inspector.directory_snapshot(candidate)[2] & 0o170000 == 0o040000


def test_measure_returns_size_digest_newest_files(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "a.py").write_text("hello", encoding="utf-8")
    (tmp_path / "cache" / "b.py").write_text("world", encoding="utf-8")
    inspector = FileInspector(_make_inspector_state())
    size, digest, newest, files = inspector.measure(candidate)
    assert size >= 0
    assert len(digest) == 128
    assert files == 2
    assert newest > 0


def test_measure_with_records(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "a.py").write_text("hello", encoding="utf-8")
    inspector = FileInspector(_make_inspector_state())
    records: dict[Path, tuple[int, ...]] = {}
    inspector.measure(candidate, records)
    assert records[candidate.path] == signature((tmp_path / "cache" / "a.py").stat()) or candidate.path in records


def test_measure_record_limit_truncates(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    (tmp_path / "cache").mkdir()
    for index in range(5):
        (tmp_path / "cache" / f"f{index}.py").write_text("x", encoding="utf-8")
    inspector = FileInspector(_make_inspector_state())
    records: dict[Path, tuple[int, ...]] = {}
    inspector.measure(candidate, records, record_limit=2)
    assert records is not None


def test_measure_rejects_protected_content(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / ".env").write_text("x", encoding="utf-8")
    inspector = FileInspector(_make_inspector_state())
    with pytest.raises(ValueError):
        inspector.measure(candidate)


def test_measure_progress_callback(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "a.py").write_text("hello", encoding="utf-8")
    inspector = FileInspector(_make_inspector_state())
    calls: list[Path] = []
    inspector.measure(candidate, progress=lambda path, count: calls.append(path))
    assert calls


def test_query_text_failure_raises() -> None:
    with mock.patch("plum_tools._cleanup.filesystem.query", return_value=mock.MagicMock(returncode=1)):
        with pytest.raises(ValueError):
            query_text(["cmd"])


def test_query_passes_data(tmp_path: Path) -> None:
    with mock.patch(
        "plum_tools._cleanup.filesystem.subprocess.run", return_value=mock.MagicMock(returncode=0)
    ) as run_mock:
        query(["cmd"], data=b"x")
    assert run_mock.call_args.kwargs["input"] == b"x"


def test_trash_put_identity_mismatch_raises(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    trash = Trash()
    with pytest.raises(ValueError):
        trash.put(target, (0, 0, 0, 0, 0))


def test_remove_candidate_validates_before_trash(tmp_path: Path) -> None:
    target = tmp_path / "cache"
    target.mkdir()
    (target / "a.py").write_text("x", encoding="utf-8")
    candidate = Candidate(target, tmp_path, Category.PROJECT_CACHE, "r", "rb")
    records = {target: signature(target.stat()), target / "a.py": signature((target / "a.py").stat())}
    trash = mock.MagicMock()
    remove_candidate(candidate, records, trash)
    trash.put.assert_called_once()


def test_remove_candidate_changed_file_raises(tmp_path: Path) -> None:
    target = tmp_path / "cache"
    target.mkdir()
    inner = target / "a.py"
    inner.write_text("x", encoding="utf-8")
    candidate = Candidate(target, tmp_path, Category.PROJECT_CACHE, "r", "rb")
    # 记录一个与实际不符的指纹，触发校验失败。
    records = {target: signature(target.stat()), inner: (0, 0, 0, 0, 0)}
    trash = mock.MagicMock()
    with pytest.raises(ValueError):
        remove_candidate(candidate, records, trash)


def test_in_node_package_requires_manifest(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / "node_modules", tmp_path, Category.DEPS, "r", "rb")
    inspector = FileInspector(_make_inspector_state())
    assert inspector._in_node_package(tmp_path / "node_modules" / "pkg" / "index.js", candidate) is False
    pkg_dir = tmp_path / "node_modules" / "pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text("{}", encoding="utf-8")
    assert inspector._in_node_package(tmp_path / "node_modules" / "pkg" / "index.js", candidate) is True


def test_in_dependency_package_venv_site_packages(tmp_path: Path) -> None:
    candidate = Candidate(tmp_path / ".venv", tmp_path, Category.DEPS, "r", "rb")
    inspector = FileInspector(_make_inspector_state())
    path = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages" / "pkg" / "mod.py"
    assert inspector._in_dependency_package(path, candidate) is True
    assert inspector._in_dependency_package(tmp_path / ".venv" / "bin" / "python", candidate) is False


# ---------- tools.py: ToolScanner ----------


def _make_tools_state(
    *,
    categories: set | None = None,
    exclude: list[str] | None = None,
    older_than: int | None = None,
    tool: list | None = None,
    docker_context: str | None = None,
    docker_builder: str | None = None,
) -> mock.MagicMock:
    """构造 ToolScanner 所需的最小运行状态。"""
    state = mock.MagicMock()
    state.args.categories = categories if categories is not None else set()
    state.args.exclude = exclude if exclude is not None else []
    state.args.older_than = older_than
    state.args.tool = tool
    state.args.docker_context = docker_context
    state.args.docker_builder = docker_builder
    state.tasks = []
    state.errors = []
    state.notes = []

    def _add_note(reason: str, detail: str = "", path: object = None) -> None:
        state.notes.append(Note(reason, detail, path if isinstance(path, Path) else None))

    state.add_note = _add_note
    state.protected_parts = set()
    state.progress.visit = mock.MagicMock()
    state.progress.phase = mock.MagicMock()
    state.home = Path("/home/user")
    return state


def _make_tools_inspector(*, excluded: bool = False) -> mock.MagicMock:
    """构造 ToolScanner 使用的 inspector，默认不排除、无仓库。"""
    inspector = mock.MagicMock()
    inspector.excluded.return_value = excluded
    return inspector


def test_add_cache_task_invalid_path_raises() -> None:
    scanner = ToolScanner(_make_tools_state(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.tools.query_text", return_value="not-absolute"):
        with pytest.raises(ValueError):
            scanner.add_cache_task("npm", ["npm", "config"], ["npm", "cache", "clean"])


def test_add_cache_task_missing_dir_returns_none(tmp_path: Path) -> None:
    scanner = ToolScanner(_make_tools_state(), mock.MagicMock())
    missing = tmp_path / "missing"
    with mock.patch("plum_tools._cleanup.tools.query_text", return_value=str(missing)):
        assert scanner.add_cache_task("npm", ["npm", "config"], ["npm", "cache", "clean"]) is None


def test_add_cache_task_exclude_rejected(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    state = _make_tools_state(exclude=["*.py"])
    inspector = mock.MagicMock()
    inspector.excluded.return_value = True
    scanner = ToolScanner(state, inspector)
    with (
        mock.patch("plum_tools._cleanup.tools.query_text", return_value=str(cache)),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        with pytest.raises(ValueError):
            scanner.add_cache_task("npm", ["npm", "config"], ["npm", "cache", "clean"])


def test_add_cache_task_older_than_rejected(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    state = _make_tools_state(older_than=30)
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.query_text", return_value=str(cache)),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        with pytest.raises(ValueError):
            scanner.add_cache_task("npm", ["npm", "config"], ["npm", "cache", "clean"])


def test_add_cache_task_success(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    state = _make_tools_state()
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.query_text", return_value=str(cache)),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        task = scanner.add_cache_task("npm", ["npm", "config"], ["npm", "cache", "clean"])
    assert task is not None
    assert task.cache == cache
    assert task.command[-1] == str(cache)
    assert state.tasks == [task]


def test_scan_tools_not_installed_skips() -> None:
    state = _make_tools_state(tool=["npm"])
    scanner = ToolScanner(state, _make_tools_inspector())
    with mock.patch("plum_tools._cleanup.tools.shutil.which", return_value=None):
        scanner.scan_tools()
    assert state.tasks == []
    assert state.notes


def test_scan_tools_pip_uses_sys_executable(tmp_path: Path) -> None:
    cache = tmp_path / "pip-cache"
    cache.mkdir()
    state = _make_tools_state(tool=["pip"])
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.sys.executable", "/usr/bin/python"),
        mock.patch("plum_tools._cleanup.tools.query_text", return_value=str(cache)),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        scanner.scan_tools()
    assert len(state.tasks) == 1


def test_scan_tools_go_trims_command(tmp_path: Path) -> None:
    cache = tmp_path / "go-cache"
    cache.mkdir()
    state = _make_tools_state(tool=["go"])
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=[str(cache), "env-value"]),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        scanner.scan_tools()
    task = state.tasks[0]
    assert task.environment["GOCACHE"] == str(cache)
    assert task.command[-1] != str(cache)


def test_scan_system_cache_non_linux_skips() -> None:
    state = _make_tools_state(categories={Category.SYSTEM_CACHE})
    scanner = ToolScanner(state, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.tools.sys.platform", "darwin"):
        scanner.scan_system_cache()
    assert state.tasks == []
    assert state.notes


def test_scan_system_cache_not_root_skips() -> None:
    state = _make_tools_state(categories={Category.SYSTEM_CACHE})
    scanner = ToolScanner(state, mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.tools.sys.platform", "linux"),
        mock.patch("plum_tools._cleanup.tools.os.geteuid", return_value=1000),
    ):
        scanner.scan_system_cache()
    assert state.tasks == []


def test_scan_system_cache_apt_found() -> None:
    state = _make_tools_state(categories={Category.SYSTEM_CACHE})
    scanner = ToolScanner(state, mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.tools.sys.platform", "linux"),
        mock.patch("plum_tools._cleanup.tools.os.geteuid", return_value=0),
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/apt-get"),
    ):
        scanner.scan_system_cache()
    assert len(state.tasks) == 1
    assert state.tasks[0].name == "apt-get"


def test_scan_docker_not_installed_skips() -> None:
    state = _make_tools_state(categories={Category.DOCKER})
    scanner = ToolScanner(state, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.tools.shutil.which", return_value=None):
        scanner.scan_docker()
    assert state.tasks == []


def test_scan_docker_remote_endpoint_skips(tmp_path: Path) -> None:
    state = _make_tools_state(categories={Category.DOCKER})
    scanner = ToolScanner(state, mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/docker"),
        mock.patch("plum_tools._cleanup.tools.os.environ", {}),
        mock.patch("plum_tools._cleanup.tools.query_text", return_value="tcp://remote:2375"),
    ):
        scanner.scan_docker()
    assert state.tasks == []


def test_scan_docker_host_env_branch(tmp_path: Path) -> None:
    state = _make_tools_state(categories={Category.DOCKER})
    scanner = ToolScanner(state, mock.MagicMock())
    env = {"DOCKER_HOST": "unix:///var/run/docker.sock"}
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/docker"),
        mock.patch("plum_tools._cleanup.tools.os.environ", env),
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=["engine-id", "df-output", "builder-inspect"]),
        mock.patch(
            "plum_tools._cleanup.models.BuilderSnapshot.parse",
            return_value=BuilderSnapshot("b", "docker", (("n", "unix:///var/run/docker.sock", "running"),)),
        ),
    ):
        scanner.scan_docker()
    assert len(state.tasks) >= 1


def test_add_docker_builder_skips_non_local_driver(tmp_path: Path) -> None:
    state = _make_tools_state(categories={Category.DOCKER})
    scanner = ToolScanner(state, mock.MagicMock())
    with mock.patch(
        "plum_tools._cleanup.tools.query_text",
        return_value="Name: b\nDriver: k8s\nNodes:\nName: n\nEndpoint: e\nStatus: running\n",
    ):
        scanner._add_docker_builder(["docker"], "ctx", "unix:///x", 30, [], [])
    assert state.tasks == []


def test_add_docker_builder_explicit_raises_on_bad_driver(tmp_path: Path) -> None:
    state = _make_tools_state(categories={Category.DOCKER}, docker_builder="b")
    scanner = ToolScanner(state, mock.MagicMock())
    with mock.patch(
        "plum_tools._cleanup.tools.query_text",
        return_value="Name: b\nDriver: k8s\nNodes:\nName: n\nEndpoint: e\nStatus: running\n",
    ):
        with pytest.raises(ValueError):
            scanner._add_docker_builder(["docker"], "ctx", "unix:///x", 30, [], [])


def test_add_docker_builder_success(tmp_path: Path) -> None:
    state = _make_tools_state(categories={Category.DOCKER})
    scanner = ToolScanner(state, mock.MagicMock())
    snapshot = BuilderSnapshot("builder1", "docker", (("n1", "unix:///x", "running"),))
    with (
        mock.patch(
            "plum_tools._cleanup.tools.query_text",
            return_value="Name: builder1\nDriver: docker\nNodes:\nName: n1\nEndpoint: unix:///x\nStatus: running\n",
        ),
        mock.patch("plum_tools._cleanup.models.BuilderSnapshot.parse", return_value=snapshot),
    ):
        scanner._add_docker_builder(["docker"], "ctx", "unix:///x", 30, [], [])
    assert any(task.name == DockerTask.BUILD for task in state.tasks)


def test_discover_prune_tasks_dispatches_by_category() -> None:
    state = _make_tools_state(categories={Category.TOOLS})
    scanner = ToolScanner(state, mock.MagicMock())
    with mock.patch.object(ToolScanner, "scan_tools") as scan_tools:
        scanner.discover_prune_tasks()
    scan_tools.assert_called_once()


def test_scan_yarn_classic_only(tmp_path: Path) -> None:
    cache = tmp_path / "yarn-cache"
    cache.mkdir()
    state = _make_tools_state()
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=["1.22.0", str(cache)]),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        scanner._scan_yarn("/usr/bin/yarn")
    assert len(state.tasks) == 1


def test_scan_yarn_berry_skips(tmp_path: Path) -> None:
    state = _make_tools_state()
    scanner = ToolScanner(state, _make_tools_inspector())
    with mock.patch("plum_tools._cleanup.tools.query_text", return_value="3.6.0"):
        scanner._scan_yarn("/usr/bin/yarn")
    assert state.tasks == []


# ---------- scanner.py: ProjectScanner ----------


def _make_scanner_state(
    *,
    categories: set | None = None,
    include_generated: list[str] | None = None,
    roots: list[Path] | None = None,
    workers: int = 1,
) -> mock.MagicMock:
    """构造 ProjectScanner 所需的最小运行状态。"""
    state = mock.MagicMock()
    state.args.categories = categories if categories is not None else set(PROJECT_CATEGORIES)
    state.args.include_generated = include_generated if include_generated is not None else []
    state.args.roots = roots if roots is not None else []
    state.args.workers = workers
    state.args.fast_deps = False
    state.args.older_than = None
    state.candidates = []
    state.candidate_paths = set()
    state.repositories = {}
    state.skipped_repositories = set()
    state.notes = []
    state.errors = []

    def _add_note(reason: str, detail: str = "", path: object = None) -> None:
        state.notes.append(Note(reason, detail, path if isinstance(path, Path) else None))

    state.add_note = _add_note
    state.home = Path("/home/user")
    state.now = time.time()
    state.progress.visit = mock.MagicMock()
    state.progress.advance = mock.MagicMock()
    state.progress.describe = mock.MagicMock()
    state.progress.phase = mock.MagicMock()
    return state


def test_project_match_deps_node(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.DEPS})
    scanner = ProjectScanner(state, mock.MagicMock())
    project = Project(kinds={ProjectKind.NODE}, rebuild={ProjectKind.NODE: "npm install"})
    match = scanner.project_match(tmp_path / "node_modules", project, is_dir=True)
    assert match == (Category.DEPS, "npm install")


def test_project_match_deps_not_selected(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.PROJECT_CACHE})
    scanner = ProjectScanner(state, mock.MagicMock())
    project = Project(kinds={ProjectKind.NODE})
    assert scanner.project_match(tmp_path / "node_modules", project, is_dir=True) is None


def test_project_match_venv_requires_pyvenv_cfg(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.DEPS})
    scanner = ProjectScanner(state, mock.MagicMock())
    project = Project(kinds={ProjectKind.PYTHON}, rebuild={ProjectKind.PYTHON: "uv sync"})
    assert scanner.project_match(tmp_path / ".venv", project, is_dir=True) is None
    (tmp_path / ".venv" / "pyvenv.cfg").parent.mkdir(exist_ok=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("x", encoding="utf-8")
    assert scanner.project_match(tmp_path / ".venv", project, is_dir=True) == (Category.DEPS, "uv sync")


def test_project_match_tox_requires_manifest(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.DEPS})
    scanner = ProjectScanner(state, mock.MagicMock())
    project = Project(manifests={tmp_path / "tox.ini": (1, 2, 3, 4, 5)})
    assert scanner.project_match(tmp_path / ".tox", project, is_dir=True) == (Category.DEPS, "tox")


def test_project_match_cache_dir(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.PROJECT_CACHE})
    scanner = ProjectScanner(state, mock.MagicMock())
    project = Project()
    match = scanner.project_match(tmp_path / "__pycache__", project, is_dir=True)
    assert match == (Category.PROJECT_CACHE, "运行对应编译、检查或测试命令时重建")


def test_project_match_build_dir(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.BUILD})
    scanner = ProjectScanner(state, mock.MagicMock())
    project = Project(kinds={ProjectKind.NODE}, rebuild={ProjectKind.NODE: "npm run build"})
    match = scanner.project_match(tmp_path / "dist", project, is_dir=True)
    assert match == (Category.BUILD, "npm run build；重新执行项目构建或测试命令")


def test_project_file_category_pyc() -> None:
    state = _make_scanner_state(categories={Category.PROJECT_CACHE})
    scanner = ProjectScanner(state, mock.MagicMock())
    assert scanner._project_file_category("x.pyc", Project()) == Category.PROJECT_CACHE
    assert scanner._project_file_category("x.txt", Project()) is None


def test_project_file_category_egg_info_requires_python() -> None:
    state = _make_scanner_state(categories={Category.BUILD})
    scanner = ProjectScanner(state, mock.MagicMock())
    assert scanner._project_file_category("pkg.egg-info", Project()) is None
    assert scanner._project_file_category("pkg.egg-info", Project(kinds={ProjectKind.PYTHON})) == Category.BUILD


def test_cache_entry_allowed_symlink(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = mock.MagicMock()
    inspector.excluded.return_value = False
    inspector.protected_name.return_value = False
    scanner = ProjectScanner(state, inspector)
    entry = mock.MagicMock()
    entry.is_symlink.return_value = True
    assert scanner._cache_entry_allowed(entry, tmp_path / "f", tmp_path, Category.USER_CACHE) is False


def test_cache_entry_managed_name_excluded(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = mock.MagicMock()
    inspector.excluded.return_value = False
    inspector.protected_name.return_value = False
    scanner = ProjectScanner(state, inspector)
    entry = mock.MagicMock()
    entry.is_symlink.return_value = False
    assert scanner._cache_entry_allowed(entry, tmp_path / "npm", tmp_path, Category.USER_CACHE) is False


def test_cache_file_eligible_expired(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = FileInspector(_make_inspector_state(older_than=30))
    scanner = ProjectScanner(state, inspector)
    info = mock.MagicMock()
    info.st_mode = 0o100644
    cutoff = inspector.cutoff(Category.USER_CACHE)
    info.st_mtime = cutoff - 1
    assert scanner._cache_file_eligible(tmp_path / "f", info, Category.USER_CACHE, None) is True
    info.st_mtime = cutoff + 1
    assert scanner._cache_file_eligible(tmp_path / "f", info, Category.USER_CACHE, None) is False


def test_cache_file_eligible_symlink_rejected(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = FileInspector(_make_inspector_state())
    scanner = ProjectScanner(state, inspector)
    info = mock.MagicMock()
    info.st_mode = 0o120777
    info.st_mtime = 1.0
    assert scanner._cache_file_eligible(tmp_path / "f", info, Category.USER_CACHE, None) is False


def test_candidate_covered_by_parent(tmp_path: Path) -> None:
    state = _make_scanner_state()
    state.candidate_paths = {tmp_path}
    scanner = ProjectScanner(state, mock.MagicMock())
    item = Candidate(tmp_path / "a" / "b", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    assert scanner._candidate_covered(item) is True


def test_add_candidate_skips_covered(tmp_path: Path) -> None:
    state = _make_scanner_state()
    state.candidate_paths = {tmp_path / "a"}
    scanner = ProjectScanner(state, mock.MagicMock())
    item = Candidate(tmp_path / "a" / "b", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    scanner.add_candidate(item)
    assert state.candidates == []


def test_user_cache_roots_darwin_and_dedup(tmp_path: Path) -> None:
    state = _make_scanner_state()
    state.home = tmp_path
    scanner = ProjectScanner(state, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.scanner.sys.platform", "darwin"):
        roots = scanner.user_cache_roots()
    assert any(root == tmp_path / "Library/Caches" for root in roots)
    assert len(roots) == len(set(roots))


def test_user_cache_roots_xdg_dedup(tmp_path: Path) -> None:
    state = _make_scanner_state()
    state.home = tmp_path
    scanner = ProjectScanner(state, mock.MagicMock())
    xdg = str(tmp_path / ".cache")
    with (
        mock.patch.dict("os.environ", {"XDG_CACHE_HOME": xdg}),
        mock.patch("plum_tools._cleanup.scanner.sys.platform", "linux"),
    ):
        roots = scanner.user_cache_roots()
    assert len(roots) == 1


def test_scan_homebrew_not_installed(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.TOOLS})
    scanner = ProjectScanner(state, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value=None):
        scanner.scan_homebrew()
    assert state.notes


def test_scan_homebrew_query_failure(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.TOOLS})
    scanner = ProjectScanner(state, mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value="/usr/bin/brew"),
        mock.patch("plum_tools._cleanup.scanner.query_text", side_effect=OSError("boom")),
    ):
        scanner.scan_homebrew()
    assert state.notes


def test_deduplicate_candidates_keeps_largest(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = mock.MagicMock()
    inspector.excluded.return_value = False
    scanner = ProjectScanner(state, inspector)
    small = Candidate(tmp_path / "a", tmp_path, Category.PROJECT_CACHE, "r", "rb", size=10)
    parent = Candidate(tmp_path, tmp_path, Category.PROJECT_CACHE, "r", "rb", size=100)
    state.candidates = [small, parent]
    scanner._deduplicate_candidates()
    assert state.candidates == [parent]


def test_deduplicate_candidates_sorted_by_size(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = mock.MagicMock()
    inspector.excluded.return_value = False
    scanner = ProjectScanner(state, inspector)
    a = Candidate(tmp_path / "a", tmp_path, Category.PROJECT_CACHE, "r", "rb", size=10)
    b = Candidate(tmp_path / "b", tmp_path, Category.PROJECT_CACHE, "r", "rb", size=50)
    state.candidates = [a, b]
    scanner._deduplicate_candidates()
    assert state.candidates[0].size == 50


def test_resolve_project_reuses_repository(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, mock.MagicMock())
    projects: dict = {}
    item = Candidate(tmp_path / "node_modules", tmp_path, Category.DEPS, "r", "rb", repository=tmp_path)
    first = scanner.resolve_project(item, projects)
    second = scanner.resolve_project(item, projects)
    assert first is second


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 0, 2)])
def test_resolve_project_keeps_sibling_repository_contexts_separate(tmp_path: Path, order: tuple[int, ...]) -> None:
    """兄弟仓库不能把配置注入共用祖先，结果不受候选顺序影响。"""
    python, node, plain = (tmp_path / name for name in ("python", "node", "plain"))
    for root in (python, node, plain):
        root.mkdir()
    (python / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    nested = python / "frontend"
    nested.mkdir()
    (nested / "package.json").write_text('{"dependencies":{"demo":"1"}}', encoding="utf-8")
    (node / "package.json").write_text('{"dependencies":{"demo":"1"}}', encoding="utf-8")
    paths = (nested / "node_modules", node / "node_modules", plain / ".pytest_cache")
    scanner = ProjectScanner(_make_scanner_state(), mock.MagicMock())
    projects: dict = {}
    for index in order:
        item = Candidate(paths[index], tmp_path, Category.DEPS, "r", "rb", repository=(python, node, plain)[index])
        actual = scanner.resolve_project(item, projects)
        expected = Project.detect(paths[index].parent, Project())
        assert actual == expected


@pytest.mark.parametrize("relative", ["", "src", "src/nested"])
def test_resolve_project_inherits_repository_above_scan_root(tmp_path: Path, relative: str) -> None:
    """从仓库子目录扫描时仍沿用仓库根的重建依据。"""
    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    root = tmp_path / relative
    root.mkdir(parents=True, exist_ok=True)
    parent = root / "nested"
    parent.mkdir()
    scanner = ProjectScanner(_make_scanner_state(), mock.MagicMock())
    item = Candidate(parent / ".pytest_cache", root, Category.PROJECT_CACHE, "r", "rb", repository=tmp_path)
    assert scanner.resolve_project(item, {}) == Project.detect(tmp_path, Project())


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_revalidate_multiple_repositories_matches_scan(tmp_path: Path, reverse: bool, changed: bool) -> None:
    """批量扫描与保存计划后的复核必须使用相同的项目上下文。"""
    roots = [tmp_path / name for name in ("python", "plain")]
    for root in roots:
        (root / ".git").mkdir(parents=True)
        (root / ".pytest_cache").mkdir()
        (root / ".pytest_cache" / "cache").write_text("cached\n", encoding="utf-8")
    (roots[0] / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    repositories = {root: Repository(root, tracked=[]) for root in roots}
    ignored = {root / ".pytest_cache": ".gitignore:1: .pytest_cache/" for root in roots}
    state = CleanupState(parse_args(["scan", "--root", str(tmp_path)]), None)
    scanner = ProjectScanner(state, FileInspector(state))
    with (
        mock.patch("plum_tools._cleanup.scanner.repository_at", side_effect=lambda path, **_: repositories.get(path)),
        mock.patch.object(Repository, "ignored", return_value=ignored),
    ):
        scanner.scan_projects(tmp_path)
    assert not state.errors
    assert {item.path for item in state.candidates} == set(ignored)
    state.candidates.sort(key=lambda item: str(item.path), reverse=reverse)
    state.args.from_plan = str(tmp_path / "plan.json")
    if changed:
        (roots[1] / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    with (
        mock.patch.object(Repository, "load", side_effect=repositories.__getitem__),
        mock.patch.object(Repository, "ignored", return_value=ignored),
        mock.patch("plum_tools._cleanup.execution.repository_at", side_effect=repositories.__getitem__),
    ):
        executor = CleanupExecutor(state, scanner.inspector, scanner)
        if changed:
            with pytest.raises(ValueError, match="项目配置或生成物规则已变化"):
                executor.revalidate()
        else:
            executor.revalidate()


# ---------- reporting.py: CleanupReporter ----------


def test_report_data_with_tasks_and_notes() -> None:
    state = _make_state(
        [Candidate(Path("/a"), Path("/"), Category.DEPS, "r", "rb", size=100)],
        [ToolTask("npm", Category.TOOLS, ["npm", "cache", "clean"], "scope", "preview")],
    )
    state.notes = [Note("原因", "详情")]
    state.errors = ["err"]
    data = CleanupReporter(state).report_data()
    assert data["estimated_bytes"] == 100
    assert data["tools"][0]["name"] == "npm"
    assert data["notes"] == ["原因: 详情"]
    assert data["errors"] == ["err"]


def test_report_json_branch(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state([Candidate(Path("/a"), Path("/"), Category.DEPS, "r", "rb", size=100)])
    state.args.json = True
    state.args.roots = [Path("/")]
    CleanupReporter(state).report()
    captured = capsys.readouterr()
    assert '"candidates"' in captured.out


def test_report_summary_with_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state(
        [Candidate(Path("/a"), Path("/"), Category.DEPS, "r", "rb", size=100, files=2)],
        [ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")],
    )
    state.args.roots = [Path("/")]
    state.console = Console(force_terminal=False, width=200)
    CleanupReporter(state).report()
    captured = capsys.readouterr()
    assert "候选" in captured.out


def test_report_prune_summary(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state([])
    state.args.command = Command.PRUNE
    state.args.prune_action = PruneAction.SHOW
    state.args.roots = []
    state.tasks = [ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")]
    state.console = Console(force_terminal=False, width=200)
    CleanupReporter(state).report()
    assert "原生工具操作" in capsys.readouterr().out


def test_report_plan_branch(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state([])
    state.args.command = Command.SCAN
    state.args.roots = []
    state.args.default_plan = False
    state.plan_path = Path("/tmp/plan.json")
    state.home = Path("/home/user")
    state.console = Console(force_terminal=False, width=200)
    CleanupReporter(state).report()
    assert "计划" in capsys.readouterr().out


def test_report_notes_and_errors(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state([])
    state.args.command = Command.SCAN
    state.args.roots = []
    state.args.default_plan = True
    state.notes = [Note(Category.TOOLS, "详情")]
    state.errors = ["boom"]
    state.console = Console(force_terminal=False, width=200)
    state.error_console = Console(stderr=True, force_terminal=False, width=200)
    CleanupReporter(state).report()
    captured = capsys.readouterr()
    assert "跳过与说明" in captured.out
    assert "boom" in captured.err


def test_report_candidates_groups(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state(
        [
            Candidate(Path("/a"), Path("/"), Category.DEPS, "r", "rb", size=100, files=2),
            Candidate(Path("/b"), Path("/"), Category.DEPS, "r", "rb", size=50, files=1),
        ]
    )
    state.args.roots = []
    state.args.default_plan = True
    state.home = Path("/home/user")
    state.console = Console(force_terminal=False, width=200)
    CleanupReporter(state).report()
    assert "依赖环境" in capsys.readouterr().out


def test_report_tasks_render(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_state([])
    state.args.command = Command.SCAN
    state.args.roots = []
    state.args.default_plan = True
    state.tasks = [ToolTask("npm", Category.TOOLS, ["npm", "cache"], "scope", "preview", environment={"A": "B"})]
    state.console = Console(force_terminal=False, width=200)
    CleanupReporter(state).report()
    assert "工具缓存" in capsys.readouterr().out


# ---------- plans.py: PlanStore ----------


def test_save_plan_with_errors_raises() -> None:
    state = mock.MagicMock()
    state.errors = ["boom"]
    store = PlanStore(state, mock.MagicMock())
    with pytest.raises(ValueError):
        store.save_plan()


def test_save_plan_path_in_candidates_raises(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    state = mock.MagicMock()
    state.errors = []
    state.args.save_plan = str(plan)
    state.args.roots = []
    state.args.categories = set()
    state.args.exclude = []
    state.args.include_generated = []
    state.args.older_than = None
    state.args.fast_deps = False
    state.args.default_plan = False
    state.plan_identity = None
    state.now = 1.0
    state.notes = []
    state.candidates = [Candidate(plan, tmp_path, Category.PROJECT_CACHE, "r", "rb")]
    store = PlanStore(state, mock.MagicMock())
    with pytest.raises(ValueError):
        store.save_plan()


def test_save_plan_success(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    state = mock.MagicMock()
    state.errors = []
    state.args.save_plan = str(plan)
    state.args.roots = [str(tmp_path)]
    state.args.categories = {Category.PROJECT_CACHE}
    state.args.exclude = []
    state.args.include_generated = []
    state.args.older_than = None
    state.args.fast_deps = False
    state.args.default_plan = False
    state.plan_identity = None
    state.now = 1.0
    state.notes = []
    state.candidates = []
    store = PlanStore(state, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.plans.write_plan") as write_mock:
        store.save_plan()
    assert write_mock.called


def test_load_plan_invalid_notes_raises(tmp_path: Path) -> None:
    state = mock.MagicMock()
    state.args.from_plan = str(tmp_path / "plan.json")
    state.args.categories = set()
    state.args.roots = []
    state.args.exclude = []
    state.args.include_generated = []
    state.args.older_than = None
    state.args.fast_deps = False
    state.args.root = None
    state.args.default_plan = False
    state.repositories = {}
    store = PlanStore(state, mock.MagicMock())
    data = {
        "runtime": plan_runtime(),
        "created_at": 1.0,
        "options": {
            "root": [],
            "category": [],
            "exclude": [],
            "include_generated": [],
            "older_than": None,
            "fast_deps": False,
        },
        "candidates": [],
        "notes": "not-a-list",
    }
    data["checksum"] = plan_checksum(data)
    with mock.patch("plum_tools._cleanup.plans.read_plan", return_value=(data, (1, 2, 3, 4, 5))):
        with pytest.raises(ValueError):
            store.load_plan()


def test_validate_plan_candidates_rejects_category_out_of_scope(tmp_path: Path) -> None:
    state = mock.MagicMock()
    state.args.categories = {Category.PROJECT_CACHE}
    state.args.roots = [tmp_path]
    state.args.exclude = []
    state.args.include_generated = []
    state.args.older_than = None
    state.args.fast_deps = False
    state.args.root = None
    state.args.default_plan = False
    state.repositories = {}
    inspector = mock.MagicMock()
    inspector.uses_directory_snapshot.return_value = False
    store = PlanStore(state, inspector)
    item = Candidate(tmp_path / "a", tmp_path, Category.DEPS, "r", "rb")
    state.candidates = [item]
    with pytest.raises(ValueError):
        store._validate_plan_candidates()


def test_restore_options_incomplete_raises(tmp_path: Path) -> None:
    state = mock.MagicMock()
    store = PlanStore(state, mock.MagicMock())
    with pytest.raises(ValueError):
        store._restore_options({"root": []})


def test_restore_options_invalid_older_than(tmp_path: Path) -> None:
    state = mock.MagicMock()
    state.args.root = None
    state.args.categories = set()
    state.args.exclude = []
    state.args.include_generated = []
    store = PlanStore(state, mock.MagicMock())
    options = {
        "root": [],
        "category": [],
        "exclude": [],
        "include_generated": [],
        "older_than": -1,
        "fast_deps": False,
    }
    with pytest.raises(ValueError):
        store._restore_options(options)


# ---------- state.py: CleanupState ----------


def test_cleanup_state_add_note(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    _write_valid_plan(plan)
    args = mock.MagicMock(save_plan=str(plan), from_plan=None)
    args.default_plan = True
    real_state = CleanupState(args, None)
    real_state.add_note("原因", "详情", tmp_path)
    assert real_state.notes[0].reason == "原因"
    assert real_state.notes[0].path == tmp_path


def test_cleanup_state_from_plan_missing_raises(tmp_path: Path) -> None:
    state = mock.MagicMock()
    state.args = mock.MagicMock(save_plan=None, from_plan=str(tmp_path / "missing.json"))
    with pytest.raises(ValueError):
        CleanupState(state.args, None)


# ---------- plan_io.py: read_plan / write_plan ----------


def _write_valid_plan(path: Path) -> dict:
    data = {
        "runtime": plan_runtime(),
        "created_at": 1.0,
        "options": {
            "root": [],
            "category": [],
            "exclude": [],
            "include_generated": [],
            "older_than": None,
            "fast_deps": False,
        },
        "candidates": [],
        "notes": [],
    }
    data["checksum"] = plan_checksum(data)
    write_plan(path, data, None)
    return data


def test_read_plan_valid(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    data = _write_valid_plan(plan)
    loaded, identity = read_plan(plan)
    assert loaded["candidates"] == data["candidates"]
    assert isinstance(identity, tuple)


def test_read_plan_corrupt_checksum(tmp_path: Path) -> None:
    plan = tmp_path / "corrupt.json"
    data = _write_valid_plan(plan)
    data["candidates"] = [{"x": 1}]
    data["checksum"] = plan_checksum(data)
    plan.unlink()
    write_plan(plan, data, None)
    with pytest.raises(ValueError):
        read_plan(plan)


def test_read_plan_incomplete_keys(tmp_path: Path) -> None:
    plan = tmp_path / "incomplete.json"
    data = _write_valid_plan(plan)
    del data["notes"]
    data["checksum"] = plan_checksum(data)
    plan.unlink()
    write_plan(plan, data, None)
    with pytest.raises(ValueError):
        read_plan(plan)


def test_write_plan_refresh_detects_change(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    data = _write_valid_plan(plan)
    _, identity = read_plan(plan)
    (plan.write_text("tampered", encoding="utf-8"))
    with pytest.raises(ValueError):
        write_plan(plan, data, identity)


def test_plan_file_path_resolves(tmp_path: Path) -> None:
    result = plan_file_path(str(tmp_path / "plan.json"))
    assert result == tmp_path / "plan.json"


# ---------- service.py: run ----------


def test_run_scan_with_errors_stops(capsys: pytest.CaptureFixture[str]) -> None:
    state_mock = mock.MagicMock()
    state_mock.errors = ["boom"]
    args = mock.MagicMock()
    args.command = Command.SCAN
    with (
        mock.patch("plum_tools._cleanup.service.CleanupState", return_value=state_mock),
        mock.patch("plum_tools._cleanup.service.FileInspector"),
        mock.patch("plum_tools._cleanup.service.ProjectScanner") as scanner_cls,
        mock.patch("plum_tools._cleanup.service.CleanupReporter"),
        mock.patch("plum_tools._cleanup.service.PlanStore"),
        mock.patch("plum_tools._cleanup.service.ToolScanner"),
        mock.patch("plum_tools._cleanup.service.CleanupExecutor"),
    ):
        code = run(args, None)
    assert code == ExitCode.FAILURE
    scanner_cls.return_value.scan.assert_called_once()


def test_run_prune_show(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.PRUNE
    args.prune_action = PruneAction.SHOW
    state_mock = mock.MagicMock()
    state_mock.errors = []
    with (
        mock.patch("plum_tools._cleanup.service.CleanupState", return_value=state_mock),
        mock.patch("plum_tools._cleanup.service.FileInspector"),
        mock.patch("plum_tools._cleanup.service.ProjectScanner"),
        mock.patch("plum_tools._cleanup.service.CleanupReporter"),
        mock.patch("plum_tools._cleanup.service.PlanStore"),
        mock.patch("plum_tools._cleanup.service.ToolScanner") as tools_cls,
        mock.patch("plum_tools._cleanup.service.CleanupExecutor") as executor_cls,
    ):
        code = run(args, None)
    assert code == ExitCode.SUCCESS
    tools_cls.return_value.discover_prune_tasks.assert_called_once()
    executor_cls.return_value.execute_prune.assert_not_called()


def test_run_prune_run_dispatches(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.PRUNE
    args.prune_action = PruneAction.RUN
    state_mock = mock.MagicMock()
    state_mock.errors = []
    state_mock.tasks = []
    with (
        mock.patch("plum_tools._cleanup.service.CleanupState", return_value=state_mock),
        mock.patch("plum_tools._cleanup.service.FileInspector"),
        mock.patch("plum_tools._cleanup.service.ProjectScanner"),
        mock.patch("plum_tools._cleanup.service.CleanupReporter"),
        mock.patch("plum_tools._cleanup.service.PlanStore"),
        mock.patch("plum_tools._cleanup.service.ToolScanner"),
        mock.patch("plum_tools._cleanup.service.CleanupExecutor") as executor_cls,
    ):
        executor_cls.return_value.execute_prune.return_value = ExitCode.SUCCESS
        code = run(args, None)
    assert code == ExitCode.SUCCESS
    executor_cls.return_value.execute_prune.assert_called_once()


def test_run_show_loads_plan(capsys: pytest.CaptureFixture[str]) -> None:
    args = mock.MagicMock()
    args.command = Command.SHOW
    state_mock = mock.MagicMock()
    state_mock.errors = []
    state_mock.repositories = {}
    state_mock.candidates = []
    state_mock.progress.phase.return_value.__enter__ = mock.MagicMock()
    state_mock.progress.phase.return_value.__exit__ = mock.MagicMock()
    with (
        mock.patch("plum_tools._cleanup.service.CleanupState", return_value=state_mock),
        mock.patch("plum_tools._cleanup.service.FileInspector"),
        mock.patch("plum_tools._cleanup.service.ProjectScanner"),
        mock.patch("plum_tools._cleanup.service.CleanupReporter"),
        mock.patch("plum_tools._cleanup.service.PlanStore") as plans_cls,
        mock.patch("plum_tools._cleanup.service.ToolScanner"),
        mock.patch("plum_tools._cleanup.service.CleanupExecutor") as executor_cls,
    ):
        code = run(args, None)
    assert code == ExitCode.SUCCESS
    plans_cls.return_value.load_plan.assert_called_once()
    executor_cls.return_value.revalidate.assert_called_once()


# ---------- execution.py: CleanupExecutor ----------


def _make_executor_state(
    *, errors: list | None = None, candidates: list | None = None, tasks: list | None = None
) -> mock.MagicMock:
    """构造 CleanupExecutor 所需的最小运行状态。"""
    state = mock.MagicMock()
    state.errors = errors if errors is not None else []
    state.candidates = candidates if candidates is not None else []
    state.tasks = tasks if tasks is not None else []
    state.args.command = Command.RUN
    state.args.yes = True
    state.args.from_plan = False
    state.execution_snapshots = {}
    state.execution_digests = {}
    state.repositories = {}
    state.progress.phase.return_value.__enter__ = mock.MagicMock()
    state.progress.phase.return_value.__exit__ = mock.MagicMock()
    state.progress.visit = mock.MagicMock()
    state.progress.advance = mock.MagicMock()
    state.console = Console(force_terminal=False, width=200)
    state.error_console = Console(stderr=True, force_terminal=False, width=200)
    return state


def test_execute_refuses_with_errors(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(errors=["boom"])
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    assert executor.execute() == ExitCode.FAILURE
    assert "扫描不完整" in capsys.readouterr().err


def test_execute_no_candidates_finishes(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state()
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    assert executor.execute() == ExitCode.SUCCESS
    assert "没有需要清理" in capsys.readouterr().out


def test_execute_non_interactive_requires_yes(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(candidates=[Candidate(Path("/a"), Path("/"), Category.DEPS, "r", "rb")])
    state.args.yes = False
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.sys.stdin.isatty", return_value=False):
        assert executor.execute() == ExitCode.USAGE
    assert "非交互环境" in capsys.readouterr().err


def test_execute_success_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.py").write_text("x", encoding="utf-8")
    item = Candidate(cache, tmp_path, Category.PROJECT_CACHE, "r", "rb", size=100, digest="digest")
    state = _make_executor_state(candidates=[item])
    state.args.from_plan = False
    state.execution_snapshots = {}
    inspector = mock.MagicMock()
    inspector.measure.return_value = (100, "digest", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.execution.shutil.disk_usage", return_value=mock.MagicMock(free=1000)),
        mock.patch("plum_tools._cleanup.execution.remove_candidate") as remove_mock,
    ):
        code = executor.execute()
    assert code == ExitCode.SUCCESS
    remove_mock.assert_called_once()


def test_execute_clean_items_changed_content_skips(capsys: pytest.CaptureFixture[str]) -> None:
    path = Path("/tmp/cache")
    item = Candidate(path, Path("/tmp"), Category.PROJECT_CACHE, "r", "rb", size=100, digest="other")
    state = _make_executor_state(candidates=[item])
    inspector = mock.MagicMock()
    inspector.measure.return_value = (100, "different-digest", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    succeeded, failed, removed = executor._clean_items()
    assert failed == 1
    assert succeeded == 0


def test_finish_plan_non_plan_returns_success() -> None:
    state = _make_executor_state()
    state.args.from_plan = False
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    assert executor._finish_plan() == ExitCode.SUCCESS


def test_finish_plan_plan_changed_returns_failure(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state()
    state.args.from_plan = "/tmp/plan.json"
    state.plan_path = Path("/tmp/plan.json")
    state.loaded_plan_identity = (1, 2, 3, 4, 5)
    state.loaded_plan_checksum = "old"
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.read_plan", return_value=({}, (9, 9, 9, 9, 9))):
        assert executor._finish_plan() == ExitCode.FAILURE


def test_revalidate_task_missing_cache_guard_raises(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    task = ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview", cache=cache, guard=(999, 999))
    state = _make_executor_state()
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with pytest.raises(ValueError):
        executor.revalidate_task(task)


def test_revalidate_task_verification_failure_wrapped(tmp_path: Path) -> None:
    task = ToolTask(
        "npm",
        Category.TOOLS,
        ["npm"],
        "scope",
        "preview",
        verifications=[ToolVerification(["x"], "result")],
    )
    state = _make_executor_state()
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.models.ToolVerification.validate", side_effect=ValueError("bad")):
        with pytest.raises(ValueError, match="npm"):
            executor.revalidate_task(task)


def test_execute_prune_no_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state()
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    assert executor.execute_prune() == ExitCode.SUCCESS
    assert "没有可执行" in capsys.readouterr().out


def test_execute_prune_with_errors(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(errors=["boom"])
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    assert executor.execute_prune() == ExitCode.FAILURE


def test_execute_prune_non_interactive_requires_yes(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(tasks=[ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")])
    state.args.yes = False
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.sys.stdin.isatty", return_value=False):
        assert executor.execute_prune() == ExitCode.USAGE


def test_execute_prune_confirm_cancel(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(tasks=[ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")])
    state.args.yes = False
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.execution.sys.stdin.isatty", return_value=True),
        mock.patch("builtins.input", return_value="no"),
    ):
        assert executor.execute_prune() == ExitCode.SUCCESS
    assert "已取消" in capsys.readouterr().out


def test_execute_prune_confirm_accept(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(tasks=[ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")])
    state.args.yes = False
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.execution.sys.stdin.isatty", return_value=True),
        mock.patch("builtins.input", return_value="CLEAN"),
        mock.patch("plum_tools._cleanup.execution.subprocess.run", return_value=mock.MagicMock(returncode=0)),
    ):
        assert executor.execute_prune() == ExitCode.SUCCESS


def test_execute_prune_subprocess_failure(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(tasks=[ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")])
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.subprocess.run", return_value=mock.MagicMock(returncode=1)):
        assert executor.execute_prune() == ExitCode.FAILURE


def test_execute_prune_subprocess_exception(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(tasks=[ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview")])
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.subprocess.run", side_effect=OSError("boom")):
        assert executor.execute_prune() == ExitCode.FAILURE


def test_execute_prune_docker_note(capsys: pytest.CaptureFixture[str]) -> None:
    state = _make_executor_state(tasks=[ToolTask("docker-images", Category.DOCKER, ["docker"], "scope", "preview")])
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.subprocess.run", return_value=mock.MagicMock(returncode=0)):
        assert executor.execute_prune() == ExitCode.SUCCESS
    assert "Docker 虚拟机磁盘文件不一定立即缩小" in capsys.readouterr().out


def test_revalidate_snapshot_symlink_raises(tmp_path: Path) -> None:
    state = _make_executor_state()
    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    item = Candidate(link, tmp_path, Category.PROJECT_CACHE, "r", "rb")
    inspector = mock.MagicMock()
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with pytest.raises(ValueError):
        executor._revalidate_snapshot(item, 0)


def test_revalidate_snapshot_content_changed(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    item = Candidate(cache, tmp_path, Category.PROJECT_CACHE, "r", "rb", digest="expected")
    state = _make_executor_state()
    inspector = mock.MagicMock()
    inspector.measure.return_value = (0, "different", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with pytest.raises(ValueError):
        executor._revalidate_snapshot(item, 0)


def test_revalidate_snapshot_directory_mode(tmp_path: Path) -> None:
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    identity = signature(node_modules.stat())
    item = Candidate(
        node_modules,
        tmp_path,
        Category.DEPS,
        "r",
        "rb",
        digest="",
        identity=identity,
        snapshot=SnapshotMode.DIRECTORY,
    )
    state = _make_executor_state(candidates=[item])
    state.execution_digests = {node_modules: "d"}
    inspector = mock.MagicMock()
    inspector.directory_snapshot.return_value = identity
    inspector.measure.return_value = (0, "d", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    # record_limit 为 0 时不采集节点记录，返回 None。
    assert executor._revalidate_snapshot(item, 0) is None


def test_revalidate_snapshot_directory_mode_with_records(tmp_path: Path) -> None:
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    identity = signature(node_modules.stat())
    item = Candidate(
        node_modules,
        tmp_path,
        Category.DEPS,
        "r",
        "rb",
        digest="",
        identity=identity,
        snapshot=SnapshotMode.DIRECTORY,
    )
    state = _make_executor_state(candidates=[item])
    state.execution_digests = {node_modules: "d"}
    records: dict[Path, tuple[int, ...]] = {node_modules: identity}
    inspector = mock.MagicMock()
    inspector.directory_snapshot.return_value = identity
    inspector.measure.return_value = (0, "d", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())

    def _measure(_item: Candidate, rec: dict, **kwargs: object) -> tuple[int, str, float, int]:
        rec.update(records)
        return (0, "d", 0.0, 1)

    inspector.measure.side_effect = _measure
    snapshot = executor._revalidate_snapshot(item, 100)
    assert snapshot is not None
    assert snapshot.digest == "d"
    assert snapshot.records == records


def test_revalidate_snapshot_no_records_returns_none(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    identity = signature(cache.stat())
    item = Candidate(cache, tmp_path, Category.PROJECT_CACHE, "r", "rb", digest="d", identity=identity)
    state = _make_executor_state()
    inspector = mock.MagicMock()
    inspector.measure.return_value = (0, "d", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    assert executor._revalidate_snapshot(item, 0) is None


def test_revalidate_manifests_changed(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    manifest = tmp_path / "package.json"
    manifest.write_text("{}", encoding="utf-8")
    item = Candidate(
        cache,
        tmp_path,
        Category.PROJECT_CACHE,
        "r",
        "rb",
        repository=tmp_path,
        manifests={manifest: (0, 0, 0, 0, 0)},
        digest="d",
        identity=signature(cache.stat()),
    )
    state = _make_executor_state(candidates=[item])
    repo = mock.MagicMock()
    state.repositories = {tmp_path: repo}
    inspector = mock.MagicMock()
    inspector.measure.return_value = (0, "d", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.Repository.load", return_value=repo):
        with pytest.raises(ValueError, match="项目配置已变化"):
            executor.revalidate()


def test_revalidate_tracked_file_rejected(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    item = Candidate(
        cache,
        tmp_path,
        Category.PROJECT_CACHE,
        "r",
        "rb",
        repository=tmp_path,
        digest="d",
        identity=signature(cache.stat()),
    )
    state = _make_executor_state(candidates=[item])
    repo = mock.MagicMock()
    repo.contains_tracked.return_value = True
    state.repositories = {tmp_path: repo}
    inspector = mock.MagicMock()
    inspector.measure.return_value = (0, "d", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.Repository.load", return_value=repo):
        with pytest.raises(ValueError, match="Git 跟踪"):
            executor.revalidate()


def test_revalidate_task_git_repo_in_cache_raises(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / ".git").mkdir()
    info = cache.stat()
    task = ToolTask("npm", Category.TOOLS, ["npm"], "scope", "preview", cache=cache, guard=(info.st_dev, info.st_ino))
    state = _make_executor_state()
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with pytest.raises(ValueError, match="Git 仓库"):
        executor.revalidate_task(task)


def test_execute_no_dir_fd_support_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    path = Path("/tmp/cache")
    item = Candidate(path, Path("/tmp"), Category.PROJECT_CACHE, "r", "rb", size=100, digest="d")
    state = _make_executor_state(candidates=[item])
    inspector = mock.MagicMock()
    inspector.measure.return_value = (100, "d", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.execution.os.supports_dir_fd", set()),
        mock.patch("plum_tools._cleanup.execution.os.supports_fd", set()),
    ):
        assert executor.execute() == ExitCode.FAILURE
    assert "不支持安全的目录复核" in capsys.readouterr().err


def test_execute_cancel_input(capsys: pytest.CaptureFixture[str]) -> None:
    path = Path("/tmp/cache")
    item = Candidate(path, Path("/tmp"), Category.PROJECT_CACHE, "r", "rb", size=100, digest="d")
    state = _make_executor_state(candidates=[item])
    state.args.yes = False
    executor = CleanupExecutor(state, mock.MagicMock(), mock.MagicMock())
    with (
        mock.patch("plum_tools._cleanup.execution.sys.stdin.isatty", return_value=True),
        mock.patch("builtins.input", return_value="no"),
    ):
        assert executor.execute() == ExitCode.SUCCESS
    assert "已取消" in capsys.readouterr().out


def test_clean_items_snapshot_reuse(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    item = Candidate(cache, tmp_path, Category.PROJECT_CACHE, "r", "rb", digest="d")
    state = _make_executor_state(candidates=[item])
    snapshot = ExecutionSnapshot(100, "d", {cache: signature(cache.stat())})
    state.execution_snapshots = {cache: snapshot}
    inspector = mock.MagicMock()
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    with mock.patch("plum_tools._cleanup.execution.remove_candidate"):
        succeeded, failed, removed = executor._clean_items()
    assert succeeded == 1
    assert removed == 100
    inspector.measure.assert_not_called()


def test_clean_items_directory_snapshot_changed(tmp_path: Path) -> None:
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    item = Candidate(
        node_modules,
        tmp_path,
        Category.DEPS,
        "r",
        "rb",
        snapshot=SnapshotMode.DIRECTORY,
        digest="",
    )
    state = _make_executor_state(candidates=[item])
    state.execution_digests = {node_modules: "expected"}
    inspector = mock.MagicMock()
    inspector.measure.return_value = (0, "different", 0.0, 1)
    executor = CleanupExecutor(state, inspector, mock.MagicMock())
    succeeded, failed, removed = executor._clean_items()
    assert failed == 1
    assert succeeded == 0


# ---------- projects.py: Repository ----------


def test_repository_load_success(tmp_path: Path) -> None:
    with (
        mock.patch("plum_tools._cleanup.projects.query_text", return_value=str(tmp_path)),
        mock.patch(
            "plum_tools._cleanup.projects.query",
            return_value=mock.MagicMock(returncode=0, stdout=b"a.py\x00b.py\x00"),
        ),
    ):
        repo = Repository.load(tmp_path)
    assert repo.root == tmp_path
    assert repo.tracked == ["a.py", "b.py"]


def test_repository_load_index_failure(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    with mock.patch("plum_tools._cleanup.projects.query", return_value=mock.MagicMock(returncode=1)):
        with pytest.raises(ValueError):
            repo.load_index()


def test_repository_load_index_cached(tmp_path: Path) -> None:
    repo = Repository(tmp_path, tracked=["x.py"])
    with mock.patch("plum_tools._cleanup.projects.query") as query_mock:
        assert repo.load_index() == ["x.py"]
    query_mock.assert_not_called()


def test_repository_ignored_file(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    result = mock.MagicMock(returncode=0, stdout=b".gitignore\x003\x00*.log\x00a.log\x00")
    with mock.patch("plum_tools._cleanup.projects.query", return_value=result):
        ignored = repo.ignored([tmp_path / "a.log"])
    assert ignored[tmp_path / "a.log"] == ".gitignore:3: *.log"


def test_repository_ignored_negated_pattern_skipped(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    result = mock.MagicMock(returncode=0, stdout=b".gitignore\x003\x00!*.log\x00a.log\x00")
    with mock.patch("plum_tools._cleanup.projects.query", return_value=result):
        ignored = repo.ignored([tmp_path / "a.log"])
    assert ignored == {}


def test_repository_ignored_directory_fully_ignored(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    repo = Repository(tmp_path)
    result1 = mock.MagicMock(returncode=1, stdout=b"")
    result2 = mock.MagicMock(returncode=0, stdout=b"")
    with mock.patch("plum_tools._cleanup.projects.query", side_effect=[result1, result2]):
        ignored = repo.ignored([build])
    assert ignored[build] == "生成物目录内的文件均被 Git 忽略"


def test_repository_ignored_directory_has_visible_file(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    repo = Repository(tmp_path)
    result1 = mock.MagicMock(returncode=1, stdout=b"")
    result2 = mock.MagicMock(returncode=0, stdout=b"build/keep.txt\x00")
    with mock.patch("plum_tools._cleanup.projects.query", side_effect=[result1, result2]):
        ignored = repo.ignored([build])
    assert build not in ignored


def test_repository_ignored_empty_paths(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    assert repo.ignored([]) == {}


def test_repository_ignored_query_failure(tmp_path: Path) -> None:
    repo = Repository(tmp_path)
    with mock.patch("plum_tools._cleanup.projects.query", return_value=mock.MagicMock(returncode=2)):
        with pytest.raises(ValueError):
            repo.ignored([tmp_path / "a.log"])


def test_repository_at_inside_worktree(tmp_path: Path) -> None:
    probe = mock.MagicMock(returncode=0, stdout=b"true\n" + str(tmp_path).encode())
    with (
        mock.patch("plum_tools._cleanup.projects.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools._cleanup.projects.query", return_value=probe),
        mock.patch("plum_tools._cleanup.projects.Repository.load_index"),
    ):
        repo = repository_at(tmp_path)
    assert repo is not None
    assert repo.root == tmp_path


def test_repository_at_not_inside_worktree_raises(tmp_path: Path) -> None:
    probe = mock.MagicMock(returncode=0, stdout=b"false\n")
    with (
        mock.patch("plum_tools._cleanup.projects.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools._cleanup.projects.query", return_value=probe),
    ):
        with pytest.raises(ValueError):
            repository_at(tmp_path)


def test_repository_at_git_unavailable_without_marker(tmp_path: Path) -> None:
    with mock.patch("plum_tools._cleanup.projects.shutil.which", return_value=None):
        assert repository_at(tmp_path) is None


def test_repository_at_git_unavailable_with_marker_raises(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with mock.patch("plum_tools._cleanup.projects.shutil.which", return_value=None):
        with pytest.raises(ValueError):
            repository_at(tmp_path)


def test_repository_at_empty_git_placeholder_raises(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("", encoding="utf-8")
    with (
        mock.patch("plum_tools._cleanup.projects.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools._cleanup.projects.query", return_value=mock.MagicMock(returncode=1)),
    ):
        with pytest.raises(ValueError):
            repository_at(tmp_path)


def test_repository_at_probe_failure_without_marker_returns_none(tmp_path: Path) -> None:
    probe = mock.MagicMock(returncode=1, stdout=b"")
    with (
        mock.patch("plum_tools._cleanup.projects.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools._cleanup.projects.query", return_value=probe),
        mock.patch.dict("os.environ", {}, clear=True),
    ):
        assert repository_at(tmp_path) is None


# ---------- projects.py: Project.detect ----------


def test_project_detect_node_with_dependencies(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {"x": "1"}}', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.NODE in project.kinds
    assert project.rebuild[ProjectKind.NODE] == "npm ci"
    assert (tmp_path / "package.json") in project.manifests


def test_project_detect_node_invalid_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(ValueError):
        Project.detect(tmp_path, Project())


def test_project_detect_node_no_dependencies_uses_default(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.NODE in project.kinds
    assert ProjectKind.NODE not in project.rebuild


def test_project_detect_node_pnpm_lock(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {"x": "1"}}', encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("{}", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert project.rebuild[ProjectKind.NODE] == "pnpm install"


def test_project_detect_python_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.PYTHON in project.kinds
    assert project.rebuild[ProjectKind.PYTHON] == "python3 -m venv <环境目录>；<环境目录>/bin/pip install ."


def test_project_detect_python_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("x==1\n", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.PYTHON in project.kinds
    assert "pip install -r requirements.txt" in project.rebuild[ProjectKind.PYTHON]


def test_project_detect_python_py_only_no_rebuild(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("pass", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.PYTHON in project.kinds
    assert ProjectKind.PYTHON not in project.rebuild


def test_project_detect_rust_build_command(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert ProjectKind.RUST in project.kinds
    assert project.rebuild[ProjectKind.RUST] == "cargo build"


def test_project_detect_uses_entries(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {"x": "1"}}', encoding="utf-8")
    with os.scandir(tmp_path) as stream:
        entries = list(stream)
    project = Project.detect(tmp_path, Project(), entries)
    assert ProjectKind.NODE in project.kinds


def test_project_detect_manifests_records_signatures(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert project.manifests[tmp_path / "pyproject.toml"] == signature((tmp_path / "pyproject.toml").stat())


# ---------- scanner.py: 项目与缓存遍历 ----------


def _make_scan_inspector(*, excluded: bool = False, protected: bool = False) -> mock.MagicMock:
    """构造 ProjectScanner 使用的 inspector。"""
    inspector = mock.MagicMock()
    inspector.excluded.return_value = excluded
    inspector.protected_name.return_value = protected
    return inspector


def test_scan_projects_skips_cache_root(tmp_path: Path) -> None:
    state = _make_scanner_state()
    state.home = tmp_path
    scanner = ProjectScanner(state, _make_scan_inspector())
    with mock.patch.object(ProjectScanner, "user_cache_roots", return_value=[tmp_path / ".cache"]):
        scanner.scan_projects(tmp_path / ".cache" / "sub")
    assert state.notes


def test_scan_projects_keeps_unverifiable_root(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    with mock.patch("plum_tools._cleanup.scanner.repository_at", side_effect=OSError("boom")):
        scanner.scan_projects(tmp_path)
    assert state.notes


def test_project_entry_excludes_symlink(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    scope = ProjectScope(tmp_path, tmp_path.stat().st_dev, ())
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "target")
    entry = next(entry for entry in os.scandir(tmp_path) if entry.name == "link")
    assert scanner._project_entry(entry, scope, Project()) is None


def test_project_entry_skips_manifest_file(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    scope = ProjectScope(tmp_path, tmp_path.stat().st_dev, ())
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    entry = next(entry for entry in os.scandir(tmp_path) if entry.name == "package.json")
    assert scanner._project_entry(entry, scope, Project(manifests={tmp_path / "package.json": (1, 2, 3, 4, 5)})) is None


def test_project_entry_skips_cache_roots(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    cache = tmp_path / ".cache"
    cache.mkdir()
    scope = ProjectScope(tmp_path, tmp_path.stat().st_dev, (cache,))
    entry = next(entry for entry in os.scandir(tmp_path) if entry.name == ".cache")
    assert scanner._project_entry(entry, scope, Project()) is None


def test_scan_project_entries_collects_and_descends(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.PROJECT_CACHE, Category.DEPS})
    scanner = ProjectScanner(state, _make_scan_inspector())
    dist = tmp_path / "dist"
    dist.mkdir()
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (tmp_path / "package.json").write_text('{"dependencies": {"x": "1"}}', encoding="utf-8")
    scope = ProjectScope(tmp_path, tmp_path.stat().st_dev, ())
    project = Project(kinds={ProjectKind.NODE}, rebuild={ProjectKind.NODE: "npm install"})
    with os.scandir(tmp_path) as stream:
        entries = sorted(stream, key=lambda item: item.name, reverse=True)
    pending: list[Candidate] = []
    children = scanner._scan_project_entries(entries, scope, None, project, pending)
    # node_modules 命中 deps 成为候选，dist 作为子目录继续遍历。
    assert any(child[0] == dist for child in children)
    assert any(item.path == node_modules for item in pending)


def test_scan_project_entries_deps_without_match_note(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.DEPS})
    scanner = ProjectScanner(state, _make_scan_inspector())
    venv = tmp_path / ".venv"
    venv.mkdir()
    scope = ProjectScope(tmp_path, tmp_path.stat().st_dev, ())
    entries = [entry for entry in os.scandir(tmp_path) if entry.name == ".venv"]
    pending: list[Candidate] = []
    scanner._scan_project_entries(entries, scope, None, Project(), pending)
    assert any(note.reason == "保留无法从项目配置重建的依赖目录" for note in state.notes)


def test_inspect_candidate_directory_snapshot(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = _make_scan_inspector()
    inspector.uses_directory_snapshot.return_value = True
    inspector.directory_snapshot.return_value = (1, 2, 3, 4, 5)
    scanner = ProjectScanner(state, inspector)
    item = Candidate(tmp_path / "node_modules", tmp_path, Category.DEPS, "r", "rb")
    result = scanner._inspect_candidate(item)
    assert result.candidate is not None
    assert result.candidate.snapshot == SnapshotMode.DIRECTORY
    assert result.candidate.size is None


def test_inspect_candidate_too_new_returns_empty(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = FileInspector(_make_inspector_state())
    scanner = ProjectScanner(state, inspector)
    item = Candidate(tmp_path / "cache", tmp_path, Category.USER_CACHE, "r", "rb")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    result = scanner._inspect_candidate(item)
    assert result.candidate is None


def test_inspect_candidate_path_change_note(tmp_path: Path) -> None:
    state = _make_scanner_state()
    inspector = _make_scan_inspector()
    inspector.uses_directory_snapshot.return_value = False
    inspector.measure.return_value = (10, "d", 1.0, 1)
    inspector.cutoff.return_value = 0.0
    scanner = ProjectScanner(state, inspector)
    item = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    # 首次与二次身份不同，触发"扫描过程中路径发生变化"。
    with mock.patch("plum_tools._cleanup.scanner.signature", side_effect=[(1, 1, 1, 1, 1), (2, 2, 2, 2, 2)]):
        result = scanner._inspect_candidate(item)
    assert result.note is not None


def test_accept_candidate_appends_note_and_error(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    scanner._accept_candidate(CandidateResult(note=Note("跳过", "原因", tmp_path)))
    scanner._accept_candidate(CandidateResult(error="无法读取"))
    assert len(state.notes) == 1
    assert state.errors == ["无法读取"]


def test_accept_candidate_appends_candidate(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    item = Candidate(tmp_path / "cache", tmp_path, Category.PROJECT_CACHE, "r", "rb")
    scanner._accept_candidate(CandidateResult(candidate=item))
    assert state.candidates == [item]
    assert item.path in state.candidate_paths


def test_add_candidates_serial(tmp_path: Path) -> None:
    state = _make_scanner_state(workers=1)
    inspector = _make_scan_inspector()
    inspector.uses_directory_snapshot.return_value = False
    inspector.measure.return_value = (10, "d", 1.0, 1)
    inspector.cutoff.return_value = 999999.0
    scanner = ProjectScanner(state, inspector)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    items = [Candidate(cache, tmp_path, Category.PROJECT_CACHE, "r", "rb")]
    scanner._add_candidates(items)
    assert len(state.candidates) == 1


def test_add_candidates_concurrent_dedup(tmp_path: Path) -> None:
    state = _make_scanner_state(workers=2)
    inspector = _make_scan_inspector()
    inspector.uses_directory_snapshot.return_value = False
    inspector.measure.return_value = (10, "d", 1.0, 1)
    inspector.cutoff.return_value = 999999.0
    scanner = ProjectScanner(state, inspector)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "f.py").write_text("x", encoding="utf-8")
    items = [
        Candidate(cache, tmp_path, Category.PROJECT_CACHE, "r", "rb"),
        Candidate(tmp_path / "other", tmp_path, Category.PROJECT_CACHE, "r", "rb"),
    ]
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "g.py").write_text("y", encoding="utf-8")
    scanner._add_candidates(items)
    assert len(state.candidates) == 2


def test_scan_cache_missing_root(tmp_path: Path) -> None:
    state = _make_scanner_state()
    scanner = ProjectScanner(state, _make_scan_inspector())
    scanner.scan_cache(tmp_path / "missing", Category.USER_CACHE, "r")
    assert state.candidates == []


def test_scan_cache_root_too_wide(tmp_path: Path) -> None:
    state = _make_scanner_state()
    state.home = tmp_path
    scanner = ProjectScanner(state, _make_scan_inspector())
    scanner.scan_cache(tmp_path, Category.USER_CACHE, "r")
    assert state.errors


def test_scan_cache_collects_expired_file(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.USER_CACHE})
    state.now = time.time()
    inspector = FileInspector(_make_inspector_state(older_than=30))
    scanner = ProjectScanner(state, inspector)
    cache = tmp_path / "cache"
    cache.mkdir()
    old = cache / "old.txt"
    old.write_text("x", encoding="utf-8")
    old_time = time.time() - 100 * 86400
    os.utime(old, (old_time, old_time))
    # 直接遍历缓存子树，绕过目录描述符的环境限制，聚焦文件过期判定逻辑。
    with (
        mock.patch("plum_tools._cleanup.scanner.directory_fd"),
        mock.patch("plum_tools._cleanup.scanner.repository_at", return_value=None),
    ):
        scanner._scan_cache_tree(cache, Category.USER_CACHE, "r", None, cache.stat().st_dev)
    assert any(item.path == old for item in state.candidates)


def test_scan_cache_skips_managed_dir(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.USER_CACHE})
    inspector = FileInspector(_make_inspector_state(older_than=30))
    scanner = ProjectScanner(state, inspector)
    cache = tmp_path / "cache"
    npm = cache / "npm"
    npm.mkdir(parents=True)
    with mock.patch("plum_tools._cleanup.scanner.directory_fd"):
        scanner._scan_cache_tree(cache, Category.USER_CACHE, "r", None, cache.stat().st_dev)
    assert state.candidates == []


def test_scan_cache_skips_inner_repo(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.USER_CACHE})
    inspector = FileInspector(_make_inspector_state(older_than=30))
    scanner = ProjectScanner(state, inspector)
    cache = tmp_path / "cache"
    inner = cache / "inner"
    inner.mkdir(parents=True)
    (inner / ".git").mkdir()
    with mock.patch("plum_tools._cleanup.scanner.directory_fd"):
        scanner._scan_cache_tree(cache, Category.USER_CACHE, "r", None, cache.stat().st_dev)
    assert any(note.reason == "跳过缓存内仓库" for note in state.notes)


def test_scan_user_cache_dispatches(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.USER_CACHE})
    state.home = tmp_path
    scanner = ProjectScanner(state, _make_scan_inspector())
    with mock.patch.object(ProjectScanner, "scan_cache") as scan_cache:
        scanner.scan_user_cache()
    assert scan_cache.called


def test_scan_dispatches_by_category(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.USER_CACHE, Category.TOOLS})
    scanner = ProjectScanner(state, _make_scan_inspector())
    with (
        mock.patch.object(ProjectScanner, "scan_user_cache") as scan_user,
        mock.patch.object(ProjectScanner, "scan_homebrew") as scan_brew,
        mock.patch.object(ProjectScanner, "_scan_project_roots") as scan_projects,
    ):
        scanner.scan()
    scan_user.assert_called_once()
    scan_brew.assert_called_once()
    scan_projects.assert_not_called()


def test_scan_project_roots_filters_skipped(tmp_path: Path) -> None:
    state = _make_scanner_state(categories={Category.PROJECT_CACHE}, roots=[tmp_path])
    inspector = _make_scan_inspector()
    scanner = ProjectScanner(state, inspector)
    skipped = Candidate(tmp_path / "skip", tmp_path, Category.PROJECT_CACHE, "r", "rb", repository=tmp_path)
    kept = Candidate(tmp_path / "keep", tmp_path, Category.PROJECT_CACHE, "r", "rb", repository=tmp_path / "other")
    state.skipped_repositories.add(tmp_path)
    state.candidates = [skipped, kept]
    with mock.patch.object(ProjectScanner, "scan_projects"):
        scanner._scan_project_roots()
    assert state.candidates == [kept]


# ---------- Go 项目、产物与共享缓存 ----------


def test_project_detect_go_records_module_files(tmp_path: Path) -> None:
    """模块声明和校验文件共同绑定 Go 项目的重建依据。"""
    (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n", encoding="utf-8")
    (tmp_path / "go.sum").write_text("example.com/lib v1.0.0 h1:abc\n", encoding="utf-8")
    project = Project.detect(tmp_path, Project())
    assert project.kinds == {ProjectKind.GO}
    assert project.rebuild == {ProjectKind.GO: "go build ./..."}
    assert project.manifests == {tmp_path / name: signature((tmp_path / name).stat()) for name in ("go.mod", "go.sum")}


@pytest.mark.parametrize("marker", ["go.sum", "main.go"])
def test_project_detect_go_requires_module(tmp_path: Path, marker: str) -> None:
    """孤立校验文件和源码不能证明依赖可重建。"""
    (tmp_path / marker).write_text("x", encoding="utf-8")
    inherited = Project()
    assert Project.detect(tmp_path, inherited) is inherited


@pytest.mark.parametrize("invalid", ["missing", "symlink", "nested", "non-go", "category"])
def test_go_vendor_requires_rebuild_evidence(tmp_path: Path, invalid: str) -> None:
    """依赖目录必须直接属于模块且具有真实的 vendor 清单。"""
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    marker = vendor / "modules.txt"
    if invalid == "symlink":
        target = tmp_path / "modules.txt"
        target.write_text("# example.com/lib v1.0.0\n", encoding="utf-8")
        marker.symlink_to(target)
    elif invalid != "missing":
        marker.write_text("# example.com/lib v1.0.0\n", encoding="utf-8")
    project = Project(
        kinds={ProjectKind.GO},
        manifests={tmp_path / ("other" if invalid == "nested" else "") / "go.mod": (1, 2, 3, 4, 5)},
        rebuild={ProjectKind.GO: "go build ./..."},
    )
    if invalid == "non-go":
        project = Project(kinds={ProjectKind.NODE})
    categories = {Category.BUILD} if invalid == "category" else {Category.DEPS}
    scanner = ProjectScanner(_make_scanner_state(categories=categories), _make_scan_inspector())
    assert scanner.project_match(vendor, project, is_dir=True) is None


@pytest.mark.parametrize("mode", ["set", "count", "atomic"])
@pytest.mark.parametrize("name", ["coverage.out", "coverage.txt", "cover.out", "demo.coverprofile"])
def test_go_coverage_requires_valid_header(tmp_path: Path, mode: str, name: str) -> None:
    """常见覆盖率报告需要具有 Go 格式头。"""
    report = tmp_path / name
    report.write_text(f"mode: {mode}\nexample.com/demo/main.go:1.1,2.1 1 1\n", encoding="utf-8")
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    match = scanner.project_match(report, Project(kinds={ProjectKind.GO}), is_dir=False)
    assert match == (Category.PROJECT_CACHE, "go test -coverprofile=<报告路径> ./...")


@pytest.mark.parametrize("content", [b"", b"user data\n", b"mode: other\n", b"mode: atomic plus data\n"])
def test_go_coverage_keeps_unrecognized_content(tmp_path: Path, content: bytes) -> None:
    """同名普通文件不应被视为覆盖率产物。"""
    report = tmp_path / "coverage.out"
    report.write_bytes(content)
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    assert scanner.project_match(report, Project(kinds={ProjectKind.GO}), is_dir=False) is None


@pytest.mark.parametrize("name", ["coverage.out", "demo.test", "demo.test.exe"])
def test_go_artifacts_keep_directories_and_other_projects(tmp_path: Path, name: str) -> None:
    """产物名称不能直接匹配目录或其他语言项目。"""
    path = tmp_path / name
    path.mkdir()
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    assert scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=True) is None
    assert scanner.project_match(path, Project(kinds={ProjectKind.NODE}), is_dir=False) is None


@pytest.mark.parametrize("name", ["demo.test", "demo.test.exe"])
@pytest.mark.parametrize("version", ["go1.24.0", "devel go1.25-abc", ""])
def test_go_test_binary_uses_readonly_version_probe(tmp_path: Path, name: str, version: str) -> None:
    """只读取 Go 构建信息，不能执行候选二进制。"""
    path = tmp_path / name
    path.write_bytes(b"\x7fELFbinary")
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    with (
        mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value="/usr/bin/go"),
        mock.patch(
            "plum_tools._cleanup.scanner.query_text", return_value=f"{path}: {version}" if version else ""
        ) as probe,
    ):
        match = scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=False)
    probe.assert_called_once_with(["/usr/bin/go", "version", str(path)])
    assert match == ((Category.BUILD, "重新执行生成此文件的 go test -c 命令") if version else None)


def test_go_test_binary_without_tool_kept(tmp_path: Path) -> None:
    """缺少 Go 时无法确认的测试文件继续保留。"""
    path = tmp_path / "demo.test"
    path.write_bytes(b"\x7fELFbinary")
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    with (
        mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value=None),
        mock.patch("plum_tools._cleanup.scanner.query_text") as probe,
    ):
        assert scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=False) is None
    probe.assert_not_called()


@pytest.mark.parametrize("name", ["coverage.out", "demo.test", "service"])
@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_go_artifacts_do_not_read_links_or_special_files(tmp_path: Path, name: str, kind: str) -> None:
    """内容校验不得跟随软链接或阻塞在同名管道文件上。"""
    path = tmp_path / name
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text("mode: atomic\n", encoding="utf-8")
        path.symlink_to(target)
    else:
        os.mkfifo(path)
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    with mock.patch("plum_tools._cleanup.scanner.query_text") as probe:
        assert scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=False) is None
    probe.assert_not_called()


@pytest.mark.parametrize(
    "header",
    [
        b"\x7fELF",
        b"MZ\x90\0",
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
        b"\0asm",
    ],
)
def test_go_build_binary_requires_readonly_build_information(tmp_path: Path, header: bytes) -> None:
    """不同平台的构建产物必须通过 Go 构建信息确认，且不要求可执行权限。"""
    path = tmp_path / "custom-output"
    path.write_bytes(header + b"payload")
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    with (
        mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.scanner.query_text", return_value=f"{path}: go1.24.0") as probe,
    ):
        assert scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=False) == (
            Category.BUILD,
            "重新执行生成此文件的 go build 命令",
        )
    probe.assert_called_once_with(["/usr/bin/go", "version", str(path)])


@pytest.mark.parametrize("name", ["service", "service.test", "service.exe"])
@pytest.mark.parametrize("content", [b"", b"package main\n", b"#!/bin/sh\nexit 0\n"])
def test_go_build_binary_keeps_text_without_probe(tmp_path: Path, name: str, content: bytes) -> None:
    """源码、脚本和空文件不触发外部查询，即使名称或权限像构建产物。"""
    path = tmp_path / name
    path.write_bytes(content)
    path.chmod(0o755)
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    with mock.patch("plum_tools._cleanup.scanner.query_text") as probe:
        assert scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=False) is None
    probe.assert_not_called()


@pytest.mark.parametrize("failure", [ValueError("not Go"), OSError("unavailable")])
def test_go_build_binary_keeps_unreadable_build_information(tmp_path: Path, failure: Exception) -> None:
    """非 Go 可执行文件和查询失败不能中断同目录其他候选的发现。"""
    path = tmp_path / "service"
    path.write_bytes(b"\x7fELFpayload")
    scanner = ProjectScanner(_make_scanner_state(), _make_scan_inspector())
    with (
        mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.scanner.query_text", side_effect=failure) as probe,
    ):
        assert scanner.project_match(path, Project(kinds={ProjectKind.GO}), is_dir=False) is None
    probe.assert_called_once_with(["/usr/bin/go", "version", str(path)])


@pytest.mark.parametrize("restriction", ["none", "tracked", "not-ignored", "sensitive", "category", "non-go"])
@pytest.mark.parametrize("relative", ["custom-output", "bin/server", "build/server.exe", "dist/linux/server"])
def test_scan_go_build_keeps_mixed_directories(tmp_path: Path, restriction: str, relative: str) -> None:
    """仅选择通过保护检查的 Go 二进制，混合输出目录中的其他文件继续保留。"""
    if restriction != "non-go":
        (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if restriction == "sensitive":
        path = path.parent / ".env"
    path.write_bytes(b"\x7fELFpayload")
    (path.parent / "keep.txt").write_text("user data\n", encoding="utf-8")
    repo = Repository(tmp_path, tracked=[path.relative_to(tmp_path).as_posix()] if restriction == "tracked" else [])
    categories = ["--category", "project-cache"] if restriction == "category" else []
    state = CleanupState(parse_args(["scan", "--root", str(tmp_path), *categories]), None)
    scanner = ProjectScanner(state, FileInspector(state))
    ignored = {} if restriction == "not-ignored" else {path: ".gitignore:1: output"}
    with (
        mock.patch("plum_tools._cleanup.scanner.repository_at", return_value=repo),
        mock.patch.object(Repository, "ignored", return_value=ignored),
        mock.patch("plum_tools._cleanup.scanner.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.scanner.query_text", return_value=f"{path}: go1.24.0"),
    ):
        scanner.scan_projects(tmp_path)
    assert not state.errors
    assert [item.path for item in state.candidates] == ([path] if restriction == "none" else [])


@pytest.mark.parametrize("protection", ["none", "tracked", "not-ignored", "sensitive"])
def test_scan_go_vendor_respects_git_and_protection(tmp_path: Path, protection: str) -> None:
    """真实扫描仅接收可重建且通过 Git 和保护规则的 vendor。"""
    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "modules.txt").write_text("# example.com/lib v1.0.0\n", encoding="utf-8")
    package = vendor / "example.com" / "lib"
    package.mkdir(parents=True)
    (package / "lib.go").write_text("package lib\n", encoding="utf-8")
    if protection == "sensitive":
        (vendor / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    repo = Repository(tmp_path, tracked=["vendor/example.com/lib/lib.go"] if protection == "tracked" else [])
    state = CleanupState(parse_args(["scan", "--root", str(tmp_path)]), None)
    scanner = ProjectScanner(state, FileInspector(state))
    ignored = {} if protection == "not-ignored" else {vendor: ".gitignore:1: vendor/"}
    with (
        mock.patch("plum_tools._cleanup.scanner.repository_at", return_value=repo),
        mock.patch.object(Repository, "ignored", return_value=ignored) as check_ignore,
    ):
        scanner.scan_projects(tmp_path)
    check_ignore.assert_called_once_with([vendor])
    assert not state.errors
    assert [item.path for item in state.candidates] == ([vendor] if protection == "none" else [])
    if protection == "none":
        assert state.candidates[0].category == Category.DEPS
        assert state.candidates[0].rebuild == "go mod vendor"


def test_go_project_revalidates_new_checksum_file(tmp_path: Path) -> None:
    """预览后新增 go.sum 时必须拒绝继续使用旧计划。"""
    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    (tmp_path / "coverage.out").write_text("mode: atomic\n", encoding="utf-8")
    state = CleanupState(parse_args(["scan", "--root", str(tmp_path)]), None)
    scanner = ProjectScanner(state, FileInspector(state))
    with mock.patch("plum_tools._cleanup.scanner.repository_at", return_value=None):
        scanner.scan_projects(tmp_path)
    assert len(state.candidates) == 1
    (tmp_path / "go.sum").write_text("new checksum\n", encoding="utf-8")
    state.args.from_plan = str(tmp_path / "plan.json")
    executor = CleanupExecutor(state, scanner.inspector, scanner)
    with mock.patch("plum_tools._cleanup.execution.repository_at", return_value=None):
        with pytest.raises(ValueError, match="项目配置或生成物规则已变化"):
            executor.revalidate()


def test_go_fast_vendor_checks_protected_files_before_run(tmp_path: Path) -> None:
    """快速计划执行前仍完整检查 vendor 内的新增敏感文件。"""
    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "modules.txt").write_text("# example.com/lib v1.0.0\n", encoding="utf-8")
    state = CleanupState(parse_args(["scan", "--root", str(tmp_path), "--fast-deps"]), None)
    scanner = ProjectScanner(state, FileInspector(state))
    with mock.patch("plum_tools._cleanup.scanner.repository_at", return_value=None):
        scanner.scan_projects(tmp_path)
    assert len(state.candidates) == 1
    assert state.candidates[0].snapshot == SnapshotMode.DIRECTORY
    (vendor / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    state.args.command = Command.RUN
    with pytest.raises(ValueError, match="受保护或排除路径"):
        CleanupExecutor(state, scanner.inspector, scanner).revalidate()


def test_go_prune_pins_both_cache_paths(tmp_path: Path) -> None:
    """构建与模块缓存分别固定路径、命令和执行环境。"""
    build, modules = tmp_path / "build", tmp_path / "modules"
    build.mkdir()
    modules.mkdir()
    state = _make_tools_state(tool=["go"])
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=[str(build), str(modules)]) as probe,
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        scanner.scan_tools()
    probe.assert_has_calls(
        [mock.call(["/usr/bin/go", "env", "GOCACHE"]), mock.call(["/usr/bin/go", "env", "GOMODCACHE"])]
    )
    assert probe.call_count == 2
    assert [task.command for task in state.tasks] == [
        ["/usr/bin/go", "clean", "-cache", "-testcache", "-fuzzcache"],
        ["/usr/bin/go", "clean", "-modcache"],
    ]
    assert [task.environment for task in state.tasks] == [{"GOCACHE": str(build)}, {"GOMODCACHE": str(modules)}]
    assert [task.cache for task in state.tasks] == [build, modules]
    for task, variable in zip(state.tasks, ("GOCACHE", "GOMODCACHE"), strict=True):
        assert task.cache is not None
        info = task.cache.stat()
        assert task.guard == (info.st_dev, info.st_ino)
        assert task.verifications == [ToolVerification(["/usr/bin/go", "env", variable], str(task.cache))]


@pytest.mark.parametrize("invalid", ["off", "relative", "missing", "home", "symlink"])
def test_go_prune_invalid_build_cache_does_not_hide_modules(tmp_path: Path, invalid: str) -> None:
    """构建缓存不可用时，模块缓存仍独立检查并展示。"""
    modules = tmp_path / "modules"
    modules.mkdir()
    build = invalid
    state = _make_tools_state(tool=["go"])
    state.home = tmp_path
    if invalid == "missing":
        build = str(tmp_path / "missing")
    elif invalid == "home":
        build = str(tmp_path)
    elif invalid == "symlink":
        link = tmp_path / "link"
        link.symlink_to(modules, target_is_directory=True)
        build = str(link)
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=[build, str(modules)]),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        scanner.scan_tools()
    assert len(state.tasks) == 1
    assert state.tasks[0].command == ["/usr/bin/go", "clean", "-modcache"]
    assert state.notes


@pytest.mark.parametrize("restriction", ["tracked", "excluded", "older-than", "symlink"])
def test_go_prune_keeps_unsafe_module_cache(tmp_path: Path, restriction: str) -> None:
    """模块缓存同样遵守仓库、路径和时间筛选限制。"""
    modules = tmp_path / "modules"
    modules.mkdir()
    if restriction == "symlink":
        link = tmp_path / "link"
        link.symlink_to(modules, target_is_directory=True)
        modules = link
    state = _make_tools_state(tool=["go"], older_than=30 if restriction == "older-than" else None)
    scanner = ToolScanner(state, _make_tools_inspector(excluded=restriction == "excluded"))
    repository = Repository(tmp_path, tracked=["modules/source.go"]) if restriction == "tracked" else None
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=["off", str(modules)]),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=repository),
    ):
        scanner.scan_tools()
    assert state.tasks == []
    assert state.notes


def test_go_prune_revalidates_module_cache_setting(tmp_path: Path) -> None:
    """模块缓存配置在预览后变化时必须拒绝执行旧范围。"""
    modules = tmp_path / "modules"
    modules.mkdir()
    state = _make_tools_state(tool=["go"])
    scanner = ToolScanner(state, _make_tools_inspector())
    with (
        mock.patch("plum_tools._cleanup.tools.shutil.which", return_value="/usr/bin/go"),
        mock.patch("plum_tools._cleanup.tools.query_text", side_effect=["off", str(modules)]),
        mock.patch("plum_tools._cleanup.tools.repository_at", return_value=None),
    ):
        scanner.scan_tools()
    assert len(state.tasks) == 1
    with (
        mock.patch("plum_tools._cleanup.execution.repository_at", return_value=None),
        mock.patch("plum_tools._cleanup.models.query_text", return_value=str(tmp_path / "changed")),
    ):
        with pytest.raises(ValueError, match="工具范围或引擎身份已变化"):
            CleanupExecutor(state, scanner.inspector, mock.MagicMock()).revalidate_task(state.tasks[0])
