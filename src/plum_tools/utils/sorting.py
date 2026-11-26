"""统一列表命令的排序参数和稳定多字段排序。"""

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

# 保留排序列表中条目的具体类型。
_T = TypeVar("_T")


@dataclass(frozen=True)
class SortField:
    """记录字段名和方向，省略方向时默认降序。"""

    name: str
    descending: bool = True


class _SortAction(argparse.Action):
    """解析重复选项与逗号分隔字段，并在扫描前校验。"""

    def __init__(self, *args: Any, fields: Mapping[str, str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields = fields

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        fields = list(getattr(namespace, self.dest) or [])
        for value in values.split(","):
            name, separator, direction = value.strip().partition(":")
            if name not in self.fields or (separator and direction not in ("asc", "desc")):
                parser.error(
                    f"无效排序 {value!r}；格式为 字段[:asc|desc]，省略方向默认 desc；可用字段：{', '.join(self.fields)}"
                )
            if any(field.name == name for field in fields):
                parser.error(f"排序字段重复：{name}；可用字段：{', '.join(self.fields)}")
            fields.append(SortField(name, direction != "asc"))
        setattr(namespace, self.dest, fields)


def add_sort_argument(parser: argparse.ArgumentParser, fields: Mapping[str, str]) -> None:
    """注册字段及中文说明，返回参数中的 sort 为字段列表或 None。"""
    parser.add_argument(
        "--sort",
        action=_SortAction,
        fields=fields,
        metavar="字段[:方向],...",
        help="按字段优先级排序，可重复传入；方向 asc 升序、desc 降序，省略方向默认 desc；"
        "空值排最后；未指定时保留原顺序。字段：" + "、".join(f"{name}（{label}）" for name, label in fields.items()),
    )


def sort_items(
    items: Iterable[_T],
    fields: Sequence[SortField] | None,
    keys: Mapping[str, Callable[[_T], Any]],
) -> list[_T]:
    """按 fields 稳定排序并返回新列表，空值始终排最后，不修改输入。"""
    result = list(items)
    # 从次要字段逐次稳定排序，使各字段可独立指定方向，且不反转空值位置。
    for field in reversed(fields or ()):
        values = [(keys[field.name](item), item) for item in result]
        present = [(value, item) for value, item in values if value is not None and value != ""]
        missing = [item for value, item in values if value is None or value == ""]
        result = [item for _, item in sorted(present, key=lambda pair: pair[0], reverse=field.descending)] + missing
    return result
