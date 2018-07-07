#!/usr/bin/env python
# -*- coding:UTF-8
"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: exceptions
#         Desc: 查找指定路径下所有被改动的git仓库
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-05 22:02
#=============================================================================
"""
import os
import argparse

from plum_tools import conf

from plum_tools.utils import print_warn
from plum_tools.utils import print_error
from plum_tools.utils import run_cmd
from plum_tools.utils import check_is_git_repository
from plum_tools.utils import check_repository_modify_status
from plum_tools.utils import check_repository_stash


def find_git_project_for_python(path):
    """查找目录下所有的 git仓库

    :param path 要被检查的目录
    :type path str
    :example path "/tmp/git"

    >>> for path in find_git_project_for_python("/tmp"):
    ...    print path


    """
    # 当前路径非目录
    if not os.path.isdir(path):
        return
    if check_is_git_repository(path):
        yield path
    else:
        for file_name in os.listdir(path):
            # 忽略隐藏文件
            if file_name.startswith("."):
                continue

            # 文件名需要拼接上当前路径
            for repository in find_git_project_for_python(os.path.join(path, file_name)):
                yield repository


def find_git_project_for_shell(path):
    """查找目录下所有的 git仓库

    :param path 要被检查的目录
    :type path str
    :example path "/tmp/git"

    >>> for path in find_git_project_for_shell("/tmp"):
    ...    print path


    """
    cmd = conf.find_command % path
    output = run_cmd(cmd)
    for git_path in output.splitlines():
        yield os.path.dirname(git_path)


def check_projects(projects, detail):
    """检查指导目录下所有的仓库是否有修改

    当仓库中有内容被修改时，打印黄色警告信息

    :param projects 需要检查的目录列表
    :type projects list
    :example ["/tmp"]

    :param detail 是否显示详细错误信息
    :type detail bool
    :example False
    """
    for project_path in projects:
        for path in find_git_project_for_shell(project_path):
            stash_result, stash_out = check_repository_stash(path)
            status_result, status_out = check_repository_modify_status(path)

            # 仓库中文件没有被改动而且没有文件被储藏了
            if not (stash_result or status_result):
                continue
            print_warn(path)

            # 打印详细错误信息
            if not detail:
                continue
            if status_result:
                print_error("[status] %s" % status_out)
            if stash_result:
                print_error("[stash] %s" % stash_out)


def main():
    """主函数
    """
    parser = argparse.ArgumentParser()

    parser.add_argument("-p" "--path",
                        action="store",
                        required=False,
                        dest="path",
                        nargs="+",
                        default=[os.environ["HOME"]],
                        help="The directory path to check")
    parser.add_argument("-d" "--detail",
                        action="store_true",
                        required=False,
                        dest="detail",
                        default=False,
                        help="display error details")
    parser.add_argument("-t" "--test",
                        action="store_true",
                        required=False,
                        dest="test",
                        default=False,
                        help="run the test function")
    args = parser.parse_args()
    check_projects(args.path, args.detail)
