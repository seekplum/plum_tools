"""统一导出 Python 3.11 起提供的 TOML 解析器与字符串枚举。"""

import tomllib
from enum import StrEnum

# 保留公共导出，供使用报告与清理工具共用。
__all__ = ["StrEnum", "tomllib"]
