#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum_tools
#     FileName: pping
#         Desc: ping指定网段所有ip是否能ping通
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-07 10:26
#=============================================================================
"""
import argparse

from multiprocessing import Pool

from plum_tools import conf
from plum_tools.exceptions import RunCmdError
from plum_tools.utils import print_text
from plum_tools.utils import run_cmd
from plum_tools.utils import get_prefix_host_ip


def ping(ip):
    """ping指定ip是否能ping通

    :param ip 主机ip
    :type ip str
    :example ip 10.10.100.1
    """
    cmd = conf.ping_command % ip
    try:
        run_cmd(cmd)
    except RunCmdError:
        pass
    else:
        return ip


def run(host_type):
    """打印IP段内所有能ping通的ip

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type str
    :example host_type default
    """
    prefix_host = get_prefix_host_ip(host_type)
    pool = Pool(processes=100)
    targets = ["%s%d" % (prefix_host, i) for i in range(1, 255)]
    result = pool.map(ping, targets)
    for ip in result:
        if ip:
            print_text(ip)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t" "--type",
                        action="store",
                        required=False,
                        dest="type",
                        default="default",
                        help="host type")

    args = parser.parse_args()
    run(args.type)
