import argparse
import typing as t

from plum_tools.conf import VERSION

from .printer import get_green


class ExtraAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: t.Union[str, t.Sequence[t.Any], None],
        option_string: t.Optional[str] = None,
    ) -> None:
        def _parser_error() -> None:
            parser.error(f"Invalid format for {option_string}: '{values}'. Expected 'key=value'.")

        if not isinstance(values, str):
            _parser_error()
            return
        split_values = values.split("=")
        if len(split_values) != 2:
            _parser_error()
            return
        origin_dest = getattr(namespace, self.dest) or {}
        origin_dest[split_values[0]] = split_values[1]
        setattr(namespace, self.dest, origin_dest)


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


def add_extra_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--extra",
        "-e",
        default={},
        action=ExtraAction,
        required=False,
        help="Extra arguments in key=value format",
    )
