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

from plum_tools.utils import print_warn
from plum_tools.utils import print_error
from plum_tools.utils import run_cmd


def check_is_git_repository(path):
    """检查目录是否为git 仓库

    :param path 要被检查的目录
    :type path str
    :example path /tmp/git/

    >>> check_is_git_repository("/tmp")
    False

    :rtype bool
    :return
        True `path`目录是一个git仓库
        False `path`目录不是一个git仓库
    """
    git_path = os.path.join(path, ".git")
    if os.path.exists(git_path) and os.path.isdir(git_path):
        return True
    return False


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
    cmd = 'find {} -name ".git"'.format(path)
    output = run_cmd(cmd)
    for git_path in output.splitlines():
        yield os.path.dirname(git_path)


def check_repository_status(repo_path):
    """检查仓库是否有文件修改

    :param repo_path 仓库路径
    :type repo_path str
    :example repo_path /tmp/git

    :rtype result bool
    :return result 检查结果
        True 仓库有文件进行了修改未提交
        False 仓库没有文件进行了修改

    >>> check_repository_status("`pwd`")#doctest: +ELLIPSIS
    (True, '...')

    :rtype output str
    :return output 命令输出
    """
    cmd = "cd {} && git status".format(repo_path)
    output = run_cmd(cmd)

    sort_cmd = "cd {} && git status -s".format(repo_path)
    result = False

    # 检查是否落后、超前远程分支
    # 检查本地是否还有文件未提交
    if '"git pull"' in output or '"git push"' in output or run_cmd(sort_cmd):
        result = True
    return result, output


def check_repository_stash(repo_path):
    """检查仓库是否在储藏区

    :param repo_path 仓库路径
    :type repo_path str
    :example repo_path /tmp/git

    :rtype result bool
    :return result 检查结果
        True 仓库有文件在储藏区
        False 仓库中储藏区是干净的

    >>> check_repository_stash("`pwd`")
    (False, '')

    :rtype output str
    :return output 命令输出
    """
    cmd = "cd {} && git stash list".format(repo_path)
    output = run_cmd(cmd)
    result = False
    if output:
        result = True
    return result, output


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
            status_result, status_out = check_repository_status(path)

            # 仓库中文件没有被改动而且没有文件被储藏了
            if not (stash_result or status_result):
                continue
            print_warn(path)

            # 打印详细错误信息
            if not detail:
                continue
            if status_result:
                print_error("[status] {}".format(status_out))
            if stash_result:
                print_error("[stash] {}".format(stash_out))


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
