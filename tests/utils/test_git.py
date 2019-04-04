#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_git
#         Desc: 测试git相关操作函数
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-03 23:28
#=============================================================================
"""

import mock
import pytest

from plum_tools.utils.git import get_current_branch_name


@pytest.mark.parametrize("mock_data, data", [
    ("release-1.0.0", "release-1.0.0")
])
def test_get_current_branch_name(mock_data, data):
    with mock.patch("plum_tools.utils.git.run_cmd", return_value=mock_data) as m:
        assert get_current_branch_name() == data
        m.assert_called_with("git rev-parse --abbrev-ref HEAD")
