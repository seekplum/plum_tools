import argparse

from plum_tools.utils.parser import get_base_parser


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
