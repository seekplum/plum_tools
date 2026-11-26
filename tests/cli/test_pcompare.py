"""验证 pcompare 的相关行为。"""

from pathlib import Path

import pytest

from plum_tools.cli.pcompare import main


@pytest.mark.parametrize(("second_content", "exit_code"), [(b"same", 0), (b"diff", 1)])
def test_main_returns_comparison_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    second_content: bytes,
    exit_code: int,
) -> None:
    paths = [tmp_path / "first", tmp_path / "second"]
    paths[0].write_bytes(b"same")
    paths[1].write_bytes(second_content)
    monkeypatch.setattr("sys.argv", ["pcompare", *(str(path) for path in paths)])

    with pytest.raises(SystemExit) as error:
        main()

    captured = capsys.readouterr()
    assert error.value.code == exit_code
    assert ("整体一致" if exit_code == 0 else "整体不一致") in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("invalid_input", ["missing", "mixed", "single", "none"])
def test_main_reports_invalid_input_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], invalid_input: str
) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"data")
    paths = {
        "missing": [tmp_path / "absent", tmp_path],
        "mixed": [file_path, tmp_path],
        "single": [tmp_path],
        "none": [],
    }[invalid_input]
    monkeypatch.setattr("sys.argv", ["pcompare", *(str(path) for path in paths)])

    with pytest.raises(SystemExit) as error:
        main()

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert captured.out == ""
    assert ("比较失败" if invalid_input != "none" else "用法：") in captured.err


def test_main_version_includes_release_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pcompare", "--version"])
    monkeypatch.setattr("plum_tools.utils.parser.VERSION", "1.2.3")
    monkeypatch.setattr("plum_tools.utils.parser.RELEASE_DATE", "2030-01-02")

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert "pcompare 版本: 1.2.3（2030-01-02）" in capsys.readouterr().out
