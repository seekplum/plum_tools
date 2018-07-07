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
    ssh_conf = {}
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

            if begin:
                ssh_conf[key] = value

    if not begin:
        print_error("未在 %s 中配置主机 %s 的ssh登陆信息" % (conf.ssh_config_path, host))
        sys.exit(1)
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


class SSHConf(object):
    def __init__(self, user, port, identityfile):
        self._user = user
        self._port = port
        self._identityfile = identityfile

    def get_ssh_conf(self, host):
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
        if self._user:
            ssh_conf["user"] = self._user
        if self._port:
            ssh_conf["port"] = self._port
        if self._identityfile:
            ssh_conf["identityfile"] = self._identityfile
        ssh_conf["hostname"] = host
        return ssh_conf

    def merge_ssh_conf(self, alias_conf):
        """合并ssh配置信息

        :param alias_conf 在./ssh/config配置文件中的ssh主机信息
        :type alias_conf dict
        :example alias_conf
        {
            'identityfile': '~/.ssh/seekplum',
            'hostname': 'github.com',
            'user': 'seekplum',
            'port': 22
        }

        :rtype ssh_conf dict
        :return ssh_conf 和输入信息合并后的ssh主机信息
        :example ssh_conf
        {
            'identityfile': '~/.ssh/seekplum',
            'hostname': 'github.com',
            'user': 'seekplum',
            'port': 22
        }
        """
        yml_config = parse_config_yml(conf.plum_yml_path)
        default_ssh_conf = yml_config["default_ssh_conf"]
        ssh_conf = {
            'identityfile': self._identityfile or alias_conf.get("identityfile", default_ssh_conf["identityfile"]),
            'hostname': alias_conf["hostname"],
            'user': self._user or alias_conf.get("user", default_ssh_conf["user"]),
            'port': self._port or alias_conf.get("port", default_ssh_conf["port"])
        }
        return ssh_conf


def login(host, host_type, user, port, identityfile):
    """登陆主机

    :param host: ip的简写或者主机的别名
    :type host str
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type str
    :example host_type default

    :param user ssh登陆用户名
    :type user str
    :example user root

    :param port ssh登陆端口
    :type port int
    :example port 22

    :param user ssh登陆用户名
    :type user str
    :example user root

    :param identityfile ssh登陆私钥文件路径
    :type identityfile str
    :example identityfile ~/.ssh/id_rsa
    """
    pattern = re.compile(r'^(?:\d+\.){0,2}\d+$')
    match = pattern.match(host)
    conf_obj = SSHConf(user, port, identityfile)
    # 传入的是ip的简写
    if match:
        host = get_host_ip(host, host_type)
        ssh_conf = conf_obj.get_ssh_conf(host)
    else:
        alias_conf = get_ssh_alias_conf(host)
        ssh_conf = conf_obj.merge_ssh_conf(alias_conf)
    cmd = get_login_ssh_cmd(**ssh_conf)
    # 不能使用run_cmd，因为会导致夯住，需要等待结果返回
    os.system(cmd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(dest="host",
                        action="store",
                        help="specify server")

    parser.add_argument("-t" "--type",
                        action="store",
                        required=False,
                        dest="type",
                        default="default",
                        help="host type")
    parser.add_argument("-i" "--identityfile",
                        action="store",
                        required=False,
                        dest="identityfile",
                        default="",
                        help="ssh login identityfile path")
    parser.add_argument("-u" "--username",
                        action="store",
                        required=False,
                        dest="user",
                        default="",
                        help="ssh login username")
    parser.add_argument("-p" "--port",
                        action="store",
                        required=False,
                        dest="port",
                        type=int,
                        default=0,
                        help="ssh login port")

    args = parser.parse_args()
    host, host_type, user, port, identityfile = args.host, args.type, args.user, args.port, args.identityfile
    # 执行登陆操作
    login(host, host_type, user, port, identityfile)
