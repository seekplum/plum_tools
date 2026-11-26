"""验证 reporting 的相关行为。"""

from io import StringIO
from pathlib import Path

from rich.console import Console

from plum_tools._compare.comparison import (
    compare_paths,
)
from plum_tools._compare.reporting import print_report


def test_report_separates_identical_and_different_entries(tmp_path: Path) -> None:
    roots = [tmp_path / "first[red]", tmp_path / "second"]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "same[bold].txt").write_bytes(b"same")
        (root / "different.txt").write_bytes(b"left" if index == 0 else b"next")
        (root / "link").symlink_to("absent[red]")
    (roots[0] / "missing").mkdir()
    output = StringIO()

    print_report(roots, compare_paths(roots), Console(file=output, width=180, color_system=None))

    rendered = output.getvalue()
    same, different = rendered.split("不一致的目录 / 文件", maxsplit=1)
    assert "一致的目录 / 文件（2）" in same
    assert "same[bold].txt" in same
    assert "same[bold].txt" not in different
    assert "different.txt" in different
    assert "different.txt" not in same
    assert "（3）" in different
    assert "缺失" in different
    assert "链接 · 组1 → absent[red]" in same
    assert f"[1] {roots[0]}" in rendered
    assert "整体不一致：一致 2 项，不一致 3 项。" in rendered


def test_report_table_compact_mode(tmp_path: Path) -> None:
    """验证 _report_table 在紧凑模式下调用 compact_table。"""
    from plum_tools._compare.models import Comparison
    from plum_tools._compare.remote import Entry
    from plum_tools._compare.reporting import _report_table

    rows = []
    # 创建一个不一致的比较结果
    entry1 = Entry(path=tmp_path, kind="目录")
    entry2 = Entry(path=tmp_path, kind="目录")
    comparison = Comparison(Path("."), (entry1, entry2), (1, 2), "不一致")
    rows.append(comparison)

    table = _report_table(rows, 2, identical=False, compact=True)

    # 紧凑模式下应设置表格属性
    assert table.box is None
    assert table.expand is True


def test_print_report_with_max_depth(tmp_path: Path) -> None:
    """验证 print_report 在 max_depth 不为 None 时打印范围信息。"""
    from plum_tools._compare.models import Comparison
    from plum_tools._compare.remote import Entry
    from plum_tools._compare.reporting import print_report

    output = StringIO()
    console = Console(file=output, width=200)

    entry = Entry(path=tmp_path, kind="目录")
    comparison = Comparison(Path("."), (entry, entry), (1, 1), "一致")

    print_report([str(tmp_path), str(tmp_path)], [comparison], console, max_depth=2)

    rendered = output.getvalue()
    # 应打印范围信息
    assert "比较范围：最多 2 层" in rendered
    assert "未检查更深层内容" in rendered
    assert "当前深度内" in rendered


def test_print_report_compact_mode(tmp_path: Path) -> None:
    """验证 print_report 在紧凑模式下使用紧凑表格。"""
    from plum_tools._compare.models import Comparison
    from plum_tools._compare.remote import Entry
    from plum_tools._compare.reporting import print_report

    output = StringIO()
    console = Console(file=output, width=200)

    entry = Entry(path=tmp_path, kind="目录")
    comparison = Comparison(Path("."), (entry, entry), (1, 1), "不一致")

    print_report([str(tmp_path), str(tmp_path)], [comparison], console, compact=True)

    rendered = output.getvalue()
    assert "不一致的目录 / 文件" in rendered
    assert "不一致" in rendered
