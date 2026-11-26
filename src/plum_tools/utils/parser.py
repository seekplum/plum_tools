import argparse
import re
import sys
import typing as t

from plum_tools._version import COMMIT_ID, RELEASE_DATE, VERSION
from plum_tools.utils.printer import get_green

# 仅翻译 argparse 的消息模板，保留参数名、用户输入及外部诊断原文。
_ERROR_TRANSLATIONS = (
    (r"the following arguments are required: (.*)", "缺少必填参数：{0}"),
    (r"unrecognized arguments: (.*)", "无法识别的参数：{0}"),
    (r"invalid choice: (.*) \(choose from (.*)\)", "无效的选项值：{0}（可选值：{1}）"),
    (r"invalid int value: (.*)", "无效的整数：{0}"),
    (r"invalid float value: (.*)", "无效的浮点数：{0}"),
    (r"invalid (\S+) value: (.*)", "无效的 {0} 类型值：{1}"),
    (r"not allowed with argument (.*)", "不能与参数 {0} 同时使用"),
    (r"expected one argument", "需要一个参数值"),
    (r"expected at least one argument", "至少需要一个参数值"),
    (r"expected at most one argument", "最多接受一个参数值"),
    (r"expected (\d+) arguments?", "需要 {0} 个参数值"),
    (r"one of the arguments (.*) is required", "必须提供以下参数之一：{0}"),
    (r"ambiguous option: (.*) could match (.*)", "参数缩写不明确：{0}，可能匹配：{1}"),
    (r"ignored explicit argument (.*)", "此选项不接受参数值：{0}"),
    (r"can't open (.*)", "无法打开 {0}"),
)


def _translate_error(message: str) -> str:
    if message.startswith("argument "):
        argument, separator, reason = message.removeprefix("argument ").partition(": ")
        if separator:
            return f"参数 {argument}：{_translate_error(reason)}"
    for pattern, translation in _ERROR_TRANSLATIONS:
        match = re.fullmatch(pattern, message, flags=re.DOTALL)
        if match:
            return translation.format(*match.groups())
    return message


class ChineseHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """使用中文用法标题，并保留示例命令的换行。"""

    def add_usage(
        self,
        usage: str | None,
        actions: t.Iterable[argparse.Action],
        groups: t.Iterable[t.Any],
        prefix: str | None = None,
    ) -> None:
        """添加用法说明，默认使用中文前缀。"""
        super().add_usage(usage, actions, groups, prefix if prefix is not None else "用法： ")


class ChineseArgumentParser(argparse.ArgumentParser):
    """统一命令及子命令的中文帮助和参数错误。"""

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        """保留解析行为，设置中文标题、帮助提示及示例格式。"""
        kwargs.setdefault("formatter_class", ChineseHelpFormatter)
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"
        for action in self._actions:
            if action.dest == "help" and action.help == "show this help message and exit":
                action.help = "显示帮助信息并退出"

    def error(self, message: str) -> t.NoReturn:
        """将参数错误写入标准错误并以状态码 2 退出。"""
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}：错误：{_translate_error(message)}\n")


class ExtraAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: t.Union[str, t.Sequence[t.Any], None],
        option_string: t.Optional[str] = None,
    ) -> None:
        def _parser_error() -> None:
            parser.error(f"{option_string} 的格式无效：'{values}'，应为 'key=value'。")

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
    _parser = ChineseArgumentParser()
    version = f"%(prog)s 版本: {VERSION}（{RELEASE_DATE or '开发版'}）"
    if COMMIT_ID:
        version += f" 提交: {COMMIT_ID[:12]}"
    _parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=get_green(version),
        help="显示版本、发布日期及构建提交并退出",
    )
    return _parser


def add_extra_argument(parser: argparse.ArgumentParser) -> None:
    """添加可重复传入的 key=value 映射参数，默认无额外映射。"""
    parser.add_argument(
        "--extra",
        "-e",
        default={},
        action=ExtraAction,
        required=False,
        help="补充导入名到包名的映射，格式为 key=value；可重复传入，默认无额外映射",
    )


def add_compact_argument(parser: argparse.ArgumentParser) -> None:
    """为支持紧凑展示的命令注册 --compact，默认关闭。"""
    parser.add_argument("--compact", action="store_true", help="紧凑展示结果，减少占用行数，默认关闭")
