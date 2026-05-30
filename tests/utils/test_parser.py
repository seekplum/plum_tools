import argparse
from unittest import mock

import pytest

from plum_tools.utils.parser import add_extra_argument, get_base_parser


def test_get_base_parser() -> None:
    parser = get_base_parser()
    assert [a._get_kwargs() for a in parser._actions] == [  # pylint: disable=protected-access
        argparse._HelpAction(  # pylint: disable=protected-access
            option_strings=["-h", "--help"],
            dest="help",
            default=argparse.SUPPRESS,
            help="show this help message and exit",
        )._get_kwargs(),
        argparse._VersionAction(  # pylint: disable=protected-access
            option_strings=["-v", "--version"],
            dest="version",
            default="==SUPPRESS==",
            help="Show program's version number and exit.",
        )._get_kwargs(),
    ]


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
