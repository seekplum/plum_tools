#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: pssh
#         Desc: 通过密钥快速登录机器
#                命令: pssh 1
#                描述: 使用指定路径下的密钥登录 x.x.x.1
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-05 22:02
#=============================================================================
"""
import argparse
import os
import re
import sys

from plum_tools import conf
from plum_tools.utils import print_error
from plum_tools.utils import parse_config_yml
from plum_tools.utils import get_prefix_host_ip


def get_ssh_alias_conf(host):
    """解析~/.ssh/config配置信息

    :rtype ssh_conf dict
    :return ssh_conf ssh主机信息
    :example ssh_conf
    {
        'identityfile': '~/.ssh/seekplum',
        'hostname': 'github.com',
        'user': 'seekplum',
        'port': 22
    }
    """
    begin = False
    # 查询默认的ssh信息
    ssh_conf = get_default_ssh_conf(host)
    with open(conf.ssh_config_path) as f:
        for line in f:
            data = line.split()
            # config配置都是两列
            if len(data) != 2:
                continue

            key = data[0].lower()
            value = data[1]

            # 多个主机信息已 Host 进行分隔
            if key == "host":
                if begin:
                    break
                elif value == host:
                    begin = True
                else:
                    continue

            if begin and key in ssh_conf:
                ssh_conf[key] = value

    if not begin:
        print_error("未在 %s 中配置主机 %s 的ssh登陆信息" % (conf.ssh_config_path, host))
        sys.exit(1)
    return ssh_conf


def get_default_ssh_conf(host):
    """查询默认的ssh登陆信息

    :param host: 主机ip
    :type host str
    :example host 10.10.100.1

    :rtype ssh_conf dict
    :return ssh_conf ssh主机信息
    :example ssh_conf
    {
        'identityfile': '~/.ssh/seekplum',
        'hostname': 'github.com',
        'user': 'seekplum',
        'port': 22
    }
    """
    yml_config = parse_config_yml(conf.plum_yml_path)
    ssh_conf = yml_config["default_ssh_conf"]
    ssh_conf["port"] = getattr(conf, "ssh_port", ssh_conf["port"])
    ssh_conf["identityfile"] = getattr(conf, "identityfile", ssh_conf["identityfile"])
    ssh_conf["hostname"] = host
    return ssh_conf


def get_login_ssh_cmd(hostname, user, port, identityfile):
    """组合登陆的命令

    :param hostname 主机ip
    :type hostname str
    :example hostname 10.10.100.1

    :param user ssh登陆使用的用户名
    :type user str
    :example user 10.10.100.1

    :param port ssh登陆使用的端口号
    :type port int
    :example port 22

    :param identityfile 主机ip
    :type identityfile str
    :example identityfile ~/.ssh/id_rse

    :rtype cmd str
    :return cmd ssh登陆的命令
    """
    cmd = 'ssh  -i %s ' \
          '-o "UserKnownHostsFile=/dev/null" ' \
          '-o "StrictHostKeyChecking no" ' \
          '-o  "ConnectTimeout=%s" ' \
          '%s@%s -p %d' % (identityfile, conf.connect_timeout, user, hostname, port)
    return cmd


def get_host_ip(host, host_type):
    """查询主机的ip

    :param host: ip的简写
    :type host str
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type int
    :example host_type 1

    :rtype str
    :return 完整的主机ip
    """
    prefix_host = get_prefix_host_ip(host_type)
    mark = "."
    # 处理输入的前两位的情况
    point_count = host.count(mark)
    prefix_host = mark.join(prefix_host.split(mark)[:(3 - point_count)])

    return "%s%s" % (prefix_host, host)


def login(host, host_type):
    """登陆主机

    :param host: ip的简写或者主机的别名
    :type host str
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type int
    :example host_type 1

    :rtype str
    :return 完整的主机ip
    """
    pattern = re.compile(r'^(?:\d+\.){0,2}\d+$')
    match = pattern.match(host)
    # 传入的是ip的简写
    if match:
        host = get_host_ip(host, host_type)
        ssh_conf = get_default_ssh_conf(host)
    else:
        ssh_conf = get_ssh_alias_conf(host)
    cmd = get_login_ssh_cmd(**ssh_conf)
    # 不能使用run_cmd，因为会导致夯住，需要等待结果返回
    os.system(cmd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("server",
                        action="store",
                        help="specify server")

    parser.add_argument("-t" "--type",
                        action="store",
                        required=False,
                        dest="type",
                        type=int,
                        default=1,
                        help="host type")
    parser.add_argument("-i" "--identityfile",
                        action="store",
                        required=False,
                        dest="identityfile",
                        default="",
                        help="identityfile path")
    parser.add_argument("-p" "--port",
                        action="store",
                        required=False,
                        dest="port",
                        type=int,
                        default=0,
                        help="ssh login number")

    args = parser.parse_args()

    if args.port:
        setattr(conf, "ssh_port", args.port)
    if args.identityfile:
        setattr(conf, "identityfile", args.identityfile)

    # 执行登陆操作
    login(args.server, args.type)
