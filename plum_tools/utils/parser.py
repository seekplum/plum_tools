import argparse

from plum_tools.conf import VERSION

from .printer import get_green


def get_base_parser() -> argparse.ArgumentParser:
    _parser = argparse.ArgumentParser()
    _parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=get_green(f"%(prog)s Version: {VERSION}"),
        help="Show program's version number and exit.",
    )
    return _parser
