#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_prn
#         Desc: 测试prn模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 16:24
#=============================================================================
"""
import mock
import pytest

from plum_tools.conf import PathConfig

from plum_tools.prn import get_project_conf


@pytest.mark.parametrize("project, src, dest, delete, exclude", [
    ("plum", "/tmp", "/tmp", 0, []),
    ("plum", "/tmp", "/tmp", 0, [".git"]),
    ("2", "/tmp", "/tmp", 1, [".git"]),
    ("1", "/tmp/1", "/tmp/2", 1, [".git", "*.pyc"]),
    ("1", "/tmp/1", "/tmp/2", None, [".git", "*.pyc"]),
    ("xxx", "/tmp/1", "/tmp/2", None, []),
])
def test_get_project_conf(project, src, dest, delete, exclude, ):
    with mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={
        "projects": {
            project: {
                "src": "/tmp",
                "dest": "/tmp",
                "delete": None,
                "exclude": [],
            }
        }
    }) as p, mock.patch("plum_tools.prn.get_file_abspath", return_value=src) as g:
        data = get_project_conf(project, src, dest, delete, exclude)
        assert data == {
            "exclude": exclude,
            "delete": delete,
            "src": src,
            "dest": dest,
        }
        p.assert_called_with(PathConfig.plum_yml_path)
        g.assert_called_with(src)
