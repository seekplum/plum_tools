import argparse
from unittest import mock

import pytest

from plum_tools.utils.parser import add_extra_argument, get_base_parser
from plum_tools.utils.printer import get_green


def test_get_base_parser() -> None:
    parser = get_base_parser()
    assert [a._get_kwargs() for a in parser._actions] == [  # pylint: disable=protected-access
        argparse._HelpAction(  # pylint: disable=protected-access
            option_strings=["-h", "--help"],
            dest="help",
            default=argparse.SUPPRESS,
            help="显示帮助信息并退出",
        )._get_kwargs(),
        argparse._VersionAction(  # pylint: disable=protected-access
            option_strings=["-v", "--version"],
            dest="version",
            default="==SUPPRESS==",
            help="显示版本、发布日期及构建提交并退出",
        )._get_kwargs(),
    ]


@pytest.mark.parametrize("option", ["--version", "-v"])
@pytest.mark.parametrize(("release_date", "display_date"), [("", "开发版"), ("2030-01-02", "2030-01-02")])
@pytest.mark.parametrize("commit_id", ["", "0123456789abcdef0123456789abcdef01234567"])
def test_version_prints_release_date_and_handles_unrecorded_versions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    option: str,
    release_date: str,
    display_date: str,
    commit_id: str,
) -> None:
    monkeypatch.setattr("sys.argv", ["example"])
    monkeypatch.setattr("plum_tools.utils.parser.VERSION", "1.2.3")
    monkeypatch.setattr("plum_tools.utils.parser.RELEASE_DATE", release_date)
    monkeypatch.setattr("plum_tools.utils.parser.COMMIT_ID", commit_id)

    with pytest.raises(SystemExit) as error:
        get_base_parser().parse_args([option])

    captured = capsys.readouterr()
    assert error.value.code == 0
    expected = f"example 版本: 1.2.3（{display_date}）"
    if commit_id:
        expected += " 提交: 0123456789ab"
    assert captured.out.strip() == get_green(expected)
    assert captured.err == ""


def test_add_extra_argument_parses_key_value_pairs() -> None:
    parser = argparse.ArgumentParser()

    add_extra_argument(parser)
    args = parser.parse_args(["--extra", "foo=bar", "--extra", "hello=world"])

    assert args.extra == {"foo": "bar", "hello": "world"}


@pytest.mark.parametrize("value", ["foo", "foo=bar=baz"])
def test_add_extra_argument_rejects_invalid_string_format(value: str) -> None:
    parser = argparse.ArgumentParser()

    add_extra_argument(parser)

    with mock.patch.object(parser, "error", side_effect=ValueError("invalid")) as mock_error:
        with pytest.raises(ValueError, match="invalid"):
            parser.parse_args(["--extra", value])

    mock_error.assert_called_once()


def test_add_extra_argument_rejects_non_string_value() -> None:
    parser = argparse.ArgumentParser()

    add_extra_argument(parser)
    action = next(action for action in parser._actions if action.dest == "extra")  # pylint: disable=protected-access
    namespace = argparse.Namespace(extra={})

    with mock.patch.object(parser, "error", side_effect=ValueError("invalid")) as mock_error:
        with pytest.raises(ValueError, match="invalid"):
            action(parser, namespace, ["foo", "bar"], "--extra")

    mock_error.assert_called_once()


def test_extra_action_returns_after_non_string_error() -> None:
    """验证 ExtraAction 在非字符串值时调用 error 后直接返回。"""
    from plum_tools.utils.parser import ExtraAction

    parser = argparse.ArgumentParser()
    namespace = argparse.Namespace(extra={})
    action = ExtraAction(option_strings=["--extra"], dest="extra")

    with mock.patch.object(parser, "error") as mock_error:
        # 传递非字符串值，应调用 error 并返回，不抛出异常
        action(parser, namespace, ["foo", "bar"], "--extra")

        mock_error.assert_called_once()
        # namespace 不应被修改
        assert namespace.extra == {}


def test_extra_action_returns_after_invalid_format() -> None:
    """验证 ExtraAction 在无效格式时调用 error 后直接返回。"""
    from plum_tools.utils.parser import ExtraAction

    parser = argparse.ArgumentParser()
    namespace = argparse.Namespace(extra={})
    action = ExtraAction(option_strings=["--extra"], dest="extra")

    with mock.patch.object(parser, "error") as mock_error:
        # 传递无效格式（没有 =），应调用 error 并返回，不抛出异常
        action(parser, namespace, "foo", "--extra")

        mock_error.assert_called_once()
        # namespace 不应被修改
        assert namespace.extra == {}
