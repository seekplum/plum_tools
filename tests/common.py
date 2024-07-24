# -*- coding: utf-8 -*-

import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import Any, Callable, Generator, List

curr_path = os.path.dirname(os.path.abspath(__file__))
fixtures_path = os.path.join(curr_path, "fixtures")


class MockPool:
    def __init__(self, processes: int = 0) -> None:
        self.processes = processes

    def __call__(self, processes: int) -> None:
        assert processes == 100

    def map(self, func: Callable, targets: List[str]) -> list:
        assert callable(func)
        assert isinstance(targets, list)
        return [func(target) for target in targets]

    def __enter__(self) -> "MockPool":
        return self

    def __exit__(self, exc_type: Any, exc_val: Exception, exc_tb: Any) -> None:
        pass


@contextmanager
def make_temp_dir(prefix: str = "plum_tools_", clean: bool = True) -> Generator[str, None, None]:
    """
    创建临时文件夹
    clean: True 在with语句之后删除文件夹
    """
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    try:
        yield temp_dir
    finally:
        if clean:
            shutil.rmtree(temp_dir)


@contextmanager
def make_temp_file(suffix: str = "", prefix: str = "plum_tools_", clean: bool = True) -> Generator[str, None, None]:
    """
    创建临时文件
    clean: True 在with语句之后删除文件夹
    """
    temp_file = tempfile.mktemp(suffix=suffix, prefix=prefix)
    try:
        yield temp_file
    finally:
        if clean and os.path.isfile(temp_file):
            os.remove(temp_file)
