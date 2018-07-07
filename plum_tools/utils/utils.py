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
import re
import platform
import sys
import subprocess

from plum_tools import conf
from plum_tools.exceptions import RunCmdError
from plum_tools.exceptions import SystemTypeError

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
        "ipmi_interval": int,
        lambda x: x.startswith("host_type_"): str,
        "projects": {
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


def get_file_abspath(path):
    """文件的相对路径

    :param path 文件路径
    :type path str
    :example path ~/.ssh/id_rsa

    :rtype abs_path str
    :return abs_path 文件绝对路径
    :example abs_path /home/seekplum/.ssh/id_rsa
    """

    def replace_path(old_path):
        """替换路径中的空格
        """
        return old_path.replace(" ", "\ ")

    # 系统直接可以找到
    if os.path.exists(path):
        return path

    # 通过系统命令stat查找真实路径
    path = replace_path(path)
    cmd = conf.stat_command % path
    output = run_cmd(cmd)

    # 获取操作系统类型
    system_type = platform.system()
    if system_type == "Linux":
        pattern = re.compile('File: "(.*)"')
    # mac系统
    elif system_type == "Darwin":
        pattern = re.compile('"\s+\d+\s+\d+\s+\d+(.*)$')
    else:
        raise SystemTypeError("此项功能仅支持 Linux / Darwin(mac)")
    match = pattern.search(output)
    abs_path = replace_path(match.group(1).strip())
    return abs_path
