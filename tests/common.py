# -*- coding: utf-8 -*-

import os
import shutil
import tempfile
from contextlib import contextmanager

curr_path = os.path.dirname(os.path.abspath(__file__))
fixtures_path = os.path.join(curr_path, "fixtures")


class MockPool(object):
    def __call__(self, processes):
        assert processes == 100

    def map(self, func, targets):
        assert callable(func)
        assert isinstance(targets, list)
        return [func(target) for target in targets]


@contextmanager
def make_temp_dir(prefix="plum_tools_", clean=True):
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
def make_temp_file(suffix="", prefix="plum_tools_", clean=True):
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
