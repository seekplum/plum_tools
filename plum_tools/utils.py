#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: utils
#         Desc: 项目中工具包
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-05 22:02
#=============================================================================
"""
import os
import sys
import subprocess

from plum_tools import conf
from plum_tools.exceptions import RunCmdError

import yaml

from functools32 import lru_cache
from schema import Schema
from schema import SchemaError
from schema import Optional


class cd(object):
    """进入目录执行对应操作后回到目录
    """

    def __init__(self, new_path):
        """初始化

        :param new_path: 目标目录
        :type new_path str
        :example new_path "/tmp"

        >>> with cd("/tmp"):
        ...     print run_cmd("pwd")
        "/tmp"
        """
        self._new_path = new_path

    def __enter__(self):
        self._current_path = os.getcwd()
        os.chdir(self._new_path)

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.chdir(self._current_path)


def get_color(c, s):
    """获取带背景色的字符串

    :param c 前背景色
    :type c int
    :example c 1

    :param s 需要获取背景色的字符串
    :type s basestring
    :example s ok

    :rtype str
    :return: 带颜色的字符串
    """
    return "\033[3%sm%s\033[0m" % (c, s)


def get_red(s):
    """获取红颜色字符串

    :param s 需要获取背景色的字符串
    :type s basestring
    :example s ok

    :rtype str
    :return: 红色的字符串
    """
    return get_color(1, s)


def get_green(s):
    """获取绿颜色字符串

    :param s 需要获取背景色的字符串
    :type s basestring
    :example s ok

    :rtype str
    :return: 绿色的字符串
    """
    return get_color(2, s)


def get_yellow(s):
    """获取黄颜色字符串

    :param s 需要获取背景色的字符串
    :type s basestring
    :example s ok

    :rtype str
    :return: 黄色的字符串
    """
    return get_color(3, s)


def print_text(text):
    """打印普通信息

    :param text 要打印的信息
    :type text basestring
    :example text "ok"
    """
    print text


def print_ok(text):
    """打印正确信息,绿色

    :param text 要打印的信息
    :type text basestring
    :example text "ok"
    """
    fmt = get_green(text)
    print fmt


def print_warn(text):
    """打印警告信息,黄色

    :param text 要打印的信息
    :type text basestring
    :example text "warn"
    """
    fmt = get_yellow(text)
    print fmt


def print_error(text):
    """打印错误信息,红色

    :param text 要打印的信息
    :type text basestring
    :example text "error"
    """
    fmt = get_red(text)
    print fmt


def run_cmd(cmd):
    """执行系统命令

    :param cmd 系统命令
    :type cmd str
    :example cmd hostname

    >>> run_cmd("echo 1")
    '1\\n'

    >>> run_cmd("ls -l /tmp") #doctest: +ELLIPSIS
    'lrwxr-xr-x@ 1 root  wheel...'

    >>> run_cmd("aaa")
    Traceback (most recent call last):
    RunCmdError: run `aaa` fail

    >>> run_cmd("bbb")
    Traceback (innermost last):
    RunCmdError: run `bbb` fail

    :rtype str
    :return 命令执行结果
    :example hostname

    :raise RunCmdError 命令执行失败
    """
    p = subprocess.Popen(cmd, shell=True, close_fds=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_msg = p.stdout.read()
    err_msg = p.stderr.read()
    exit_code = p.wait()
    if exit_code != 0:
        message = "run `%s` fail" % cmd
        raise RunCmdError(message, out_msg=out_msg, err_msg=err_msg)
    return out_msg


@lru_cache(5)
def parse_config_yml(yml_path):
    """解析配置程序依赖的配置yml文件

    :param yml_path 项目依赖的yml配置文件路径
    :type yml_path str
    :example yml_path ~/.plum_tools.yml

    :rtype dict
    :return
    """
    yml_schema = Schema({
        "default_ssh_conf": {
            "user": str,
            "port": int,
            "identityfile": str
        },
        Optional("ipmi_interval"): int,
        Optional(lambda x: x.startswith("host_type_")): str,
        Optional("projects"): {
            str: {
                "src": str,
                "dest": str,
                Optional("exclude"): list,
                Optional("delete"): int,
            }
        }
    })
    try:
        with open(yml_path) as f:
            try:
                data = yml_schema.validate(yaml.load(f.read()))
            except SchemaError as e:
                print_error("yml文件: %s 格式错误, %s, 请参照以下格式进行修改" % (conf.plum_yml_path, e.message))
                with open(os.path.join(conf.root, conf.plum_yml_name)) as fp:
                    text = fp.read()
                print_text(text)
                sys.exit(1)
            else:
                return data
    except IOError:
        print_error("yml文件: %s 不存在" % conf.plum_yml_path)
        sys.exit(1)


def get_prefix_host_ip(host_type):
    """查询不同类型的前三段IP

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type str
    :example host_type default

    :rtype prefix_host str
    :return prefix_host IP前三段值
    :example prefix_host 10.10.100.
    """
    type_key = "host_type_%s" % host_type
    try:
        yml_config = parse_config_yml(conf.plum_yml_path)
        prefix_host = yml_config[type_key]
    except KeyError:
        print_error("yml文件: %s 中缺少key: %s" % (conf.plum_yml_path, type_key))
        sys.exit(1)

    mark = "."

    if prefix_host and not prefix_host.endswith(mark):
        prefix_host += mark
    return prefix_host


def get_host_ip(host, host_type):
    """查询主机的ip

    :param host: ip的简写
    :type host str
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type str
    :example host_type default

    :rtype str
    :return 完整的主机ip
    """
    prefix_host = get_prefix_host_ip(host_type)
    mark = "."
    # 处理输入的前两位的情况
    point_count = host.count(mark)
    # 标准ip中点的数量
    normal_point = 3
    if point_count < normal_point:
        prefix_host = mark.join(prefix_host.split(mark)[:(normal_point - point_count)])
        host = "%s.%s" % (prefix_host, host)
    return host


def get_file_abspath(path):
    """文件的相对路径

    :param path 文件路径
    :type path str
    :example path ~/.ssh/id_rsa

    :rtype abs_path str
    :return abs_path 文件绝对路径
    :example abs_path /home/seekplum/.ssh/id_rsa
    """
    cmd = conf.ls_command % path
    abs_path = run_cmd(cmd).strip()
    return abs_path


def get_current_branch_name():
    """查询当前分支名

    :rtype str
    :return 当前分支名
    """
    return run_cmd(conf.branch_abbrev).strip()


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


def check_repository_modify_status(repo_path):
    """检查仓库是否有文件修改

    :param repo_path 仓库路径
    :type repo_path str
    :example repo_path /tmp/git

    :rtype result bool
    :return result 检查结果
        True 仓库有文件进行了修改未提交
        False 仓库没有文件进行了修改

    >>> check_repository_modify_status("`pwd`")#doctest: +ELLIPSIS
    (True, '...')

    :rtype output str
    :return output 命令输出
    """
    with cd(repo_path):
        output = run_cmd(conf.status_default)

    result = False

    # 检查是否落后、超前远程分支
    if conf.pull_keyword in output or conf.push_keyword in output:
        with cd(repo_path):
            # 检查本地是否还有文件未提交
            if run_cmd(conf.status_short):
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
    with cd(repo_path):
        output = run_cmd(conf.stash_list)
    result = False
    if output:
        result = True
    return result, output
