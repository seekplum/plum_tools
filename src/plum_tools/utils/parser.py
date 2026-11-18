import argparse
import typing as t

from plum_tools._version import COMMIT_ID, RELEASE_DATE, VERSION

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
    """创建包含版本、发布日期及构建提交选项的公共参数解析器。"""
    _parser = argparse.ArgumentParser()
    version = f"%(prog)s Version: {VERSION} ({RELEASE_DATE or 'development'})"
    if COMMIT_ID:
        version += f" Commit: {COMMIT_ID[:12]}"
    _parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=get_green(version),
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
