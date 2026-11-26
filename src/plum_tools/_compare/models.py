"""定义报告使用的数据结构与枚举。"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from plum_tools._compare.remote import Entry
from plum_tools.utils.enums import DocIntEnum, DocStrEnum


class CompareExitCode(DocIntEnum):
    """本地比较命令的退出状态。"""

    IDENTICAL = 0, "内容一致"
    DIFFERENT = 1, "存在差异"
    ERROR = 2, "输入或读取失败"


class ShowMode(DocStrEnum):
    """比较报告的条目展示范围。"""

    ALL = "all", "全部"
    IDENTICAL = "identical", "仅一致项"
    DIFFERENT = "different", "仅不一致项"


class CompareResult(StrEnum):
    """条目比较状态及报告汇总结果。"""

    IDENTICAL = "一致"
    DIFFERENT = "不一致"
    MISSING = "缺失"
    TYPE_DIFFERENT = "类型不同"
    CHILDREN_DIFFERENT = "子项不同"
    LINK_TARGET_DIFFERENT = "链接目标不同"
    SIZE_DIFFERENT = "大小不同"
    CONTENT_DIFFERENT = "内容不同"


@dataclass(frozen=True)
class Comparison:
    """保存一个相对路径在所有输入中的条目、内容分组及比较结果。"""

    path: Path
    entries: tuple[Entry | None, ...]
    groups: tuple[int, ...]
    result: str
