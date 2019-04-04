#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function
import os
import sys

import pytest

from tests.common import curr_path


def main():
    print("测试目录: {}".format(curr_path))

    file_path = os.path.join(curr_path, "utils", "test_git.py::test_check_repository_stash")
    if len(sys.argv) > 1:
        args = [sys.argv[1:]]
    elif (file_path.endswith(".py") and os.path.exists(file_path)) or (not file_path.endswith(".py")):
        args = [file_path]
    else:
        args = [curr_path]
    print("*" * 100)
    print("测试文件: ", args)
    print("*" * 100)

    pytest.main(args)


if __name__ == '__main__':
    main()