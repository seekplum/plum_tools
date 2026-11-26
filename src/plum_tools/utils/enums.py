"""提供成员值和说明一起定义的整数、字符串枚举。"""

import inspect
from enum import IntEnum, StrEnum
from typing import Self


class DocIntEnum(IntEnum):
    """带成员说明的整数枚举。"""

    def __new__(cls, value: int, doc: str) -> Self:
        member = int.__new__(cls, value)
        member._value_ = value
        member.__doc__ = doc
        return member

    @property
    def desc(self) -> str:
        """返回当前枚举成员的说明。"""
        return inspect.getdoc(self) or ""


class DocStrEnum(StrEnum):
    """带成员说明的字符串枚举。"""

    def __new__(cls, value: str, doc: str) -> Self:
        member = str.__new__(cls, value)
        member._value_ = value
        member.__doc__ = doc
        return member

    @property
    def desc(self) -> str:
        """返回当前枚举成员的说明。"""
        return inspect.getdoc(self) or ""
