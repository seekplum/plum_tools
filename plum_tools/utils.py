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
import subprocess

from plum_tools.exceptions import RunCmdError


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
        message = "run `{}` fail".format(cmd)
        raise RunCmdError(message, out_msg=out_msg, err_msg=err_msg)
    return out_msg
