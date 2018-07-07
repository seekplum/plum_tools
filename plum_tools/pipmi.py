#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum_tools
#     FileName: pipmi
#         Desc: 对指定机器进行开机操作
#               命令: pipmi -l 1 -s 2 3
#               描述: ssh登录1机器,对2,3进行开机操作
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-07 14:14
#=============================================================================
"""
import argparse
import socket
import sys

from contextlib import contextmanager

import paramiko

from plum_tools import conf
from plum_tools.utils import print_text
from plum_tools.utils import print_error
from plum_tools.utils import parse_config_yml
from plum_tools.utils import get_host_ip
from plum_tools.utils import get_file_abspath
from plum_tools.exceptions import RunCmdError
from plum_tools.exceptions import SSHException


class PSSHClient(paramiko.SSHClient):
    def __init__(self, host):
        super(PSSHClient, self).__init__()
        self.host = host

    def run_cmd(self, cmd, is_raise_exception=True, **kwargs):
        """执行系统命令
        
        :param cmd 要执行的命令
        :type cmd str
        :example cmd hostname
        
        :param is_raise_exception 执行命令有错误信息是否抛出异常，默认值为True
        :type is_raise_exception bool 
        :example is_raise_exception False
        
        :raise RunCmdError
        
        :rtype out_msg str
        :return out_msg 命令执行结果
        """
        stdin, stdout, stderr = self.exec_command(cmd, **kwargs)
        stdin.close()
        stdout.flush()
        out_msg = stdout.read()
        err_msg = stderr.read()
        if is_raise_exception and err_msg:
            message = "[%s] run cmd `%s` fail" % (self.host, cmd)
            raise RunCmdError(message, out_msg=out_msg, err_msg=err_msg)
        return out_msg


class SSHTool(object):

    def __init__(self, hostname, username, port, conn_timeout=3, password=None, identityfile=None):
        """初始化

        :param hostname 主机ip
        :type hostname str
        :example hostname 10.10.100.1

        :param username 用户名
        :type username str
        :example username root

        :param port 端口号
        :type port int
        :example port 22

        :param conn_timeout 连接超时时间
        :type conn_timeout int
        :example conn_timeout 3

        :param password 密码
        :type password str
        :example password xxx

        :param identityfile 密钥文件路径
        :type identityfile str
        :example identityfile ~/.ssh/id_rsa
        """
        self.host = hostname
        self.username = username
        self.password = password
        self.key_filename = identityfile
        self.port = port
        self.conn_timeout = conn_timeout

    def get_ssh(self):
        """获取一个 ssh连接对象

        :rtype ssh paramiko.SSHClient
        :return: ssh ssh连接对象
        """
        try:
            ssh = PSSHClient(host=self.host)
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=self.host,
                        username=self.username,
                        password=self.password,
                        key_filename=self.key_filename,
                        port=self.port,
                        timeout=self.conn_timeout)
            return ssh
        except socket.timeout:
            msg = "连接超时(%s@%s:%s)." % (self.username, self.host, self.port)
            msg = "%s请检查用户名,IP地址,端口号是否正确" % msg
            raise SSHException(msg)
        except paramiko.ssh_exception.NoValidConnectionsError:
            msg = "连接出现异常(%s@%s:%s)." % (self.username, self.host, self.port)
            raise SSHException("%s请检查端口或IP地址是否正确" % msg)
        except paramiko.ssh_exception.AuthenticationException:
            msg = "连接出现异常(%s@%s:%s)." % (self.username, self.host, self.port)
            raise SSHException("%s请检查密码或密钥是否正确" % msg)
        except Exception as e:
            msg = "连接出现异常(%s@%s:%s) %s." % (self.username, self.host, self.port, e)
            raise SSHException(msg)


@contextmanager
def get_ssh(hostname, username, port, conn_timeout=3, password=None, identityfile=None):
    """获取一个 ssh连接对象

    :param hostname 主机ip
    :type hostname str
    :example hostname 10.10.100.1

    :param username 用户名
    :type username str
    :example username root

    :param port 端口号
    :type port int
    :example port 22

    :param conn_timeout 连接超时时间
    :type conn_timeout int
    :example conn_timeout 3

    :param password 密码
    :type password str
    :example password xxx

    :param identityfile 密钥文件路径
    :type identityfile str
    :example identityfile ~/.ssh/id_rsa

    :rtype ssh paramiko.SSHClient
    :return: ssh ssh连接对象
    """
    ssh_tool = SSHTool(hostname=hostname,
                       username=username,
                       port=port,
                       conn_timeout=conn_timeout,
                       password=password,
                       identityfile=get_file_abspath(identityfile))
    ssh = ssh_tool.get_ssh()
    yield ssh
    ssh.close()


def get_ssh_config(hostname, username, port, identityfile, password):
    """查询默认的ssh配置信息

    :param hostname 主机ip
    :type hostname str
    :example hostname 10.10.100.1

    :param username 用户名
    :type username str
    :example username root

    :param port 端口号
    :type port int
    :example port 22

    :param password 密码
    :type password str
    :example password xxx

    :param identityfile 密钥文件路径
    :type identityfile str
    :example identityfile ~/.ssh/id_rsa

    :rtype ssh_conf dict
    :return ssh_conf ssh登陆的配置信息
    :example ssh_conf
    {
        'identityfile': '~/.ssh/seekplum',
        'hostname': 'github.com',
        'username': 'seekplum',
        'password': 'xxx',
        'port': 22
    }
    """
    yml_data = parse_config_yml(conf.plum_yml_path)
    default_ssh_conf = yml_data["default_ssh_conf"]
    ssh_conf = {
        "hostname": hostname,
        "username": username or default_ssh_conf["username"],
        "port": port or default_ssh_conf["port"],
        "identityfile": identityfile or default_ssh_conf["identityfile"],
        "password": password
    }
    return ssh_conf


def get_ipmi_ip(host, host_type):
    """根据ip计算带外 ip

    :param host: ip的简写
    :type host str
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :type host_type str
    :example host_type default

    :rtype ipmi_ip str
    :return ipmi_ip 带外ip
    :example ipmi_ip 10.10.10.101
    """
    yml_data = parse_config_yml(conf.plum_yml_path)
    hostname = get_host_ip(host, host_type)
    item = hostname.split(".")
    item[-1] = str(int(item[-1]) + yml_data["ipmi_interval"])
    ipmi_ip = ".".join(item)
    return ipmi_ip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--login",
                        required=True,
                        action="store",
                        dest="host",
                        help="specify login ip")
    parser.add_argument("-s", "--servers",
                        required=True,
                        action="store",
                        dest="servers",
                        nargs="+",
                        help="specify server")
    parser.add_argument("-u", "--username",
                        required=False,
                        action="store",
                        dest="user",
                        default="root",
                        help="specify username")
    parser.add_argument("-pass", "--password",
                        required=False,
                        action="store",
                        dest="password",
                        default="",
                        help="specify password")
    parser.add_argument("-p" "--port",
                        action="store",
                        required=False,
                        dest="port",
                        type=int,
                        default=0,
                        help="ssh login port")
    parser.add_argument("-i" "--identityfile",
                        action="store",
                        required=False,
                        dest="identityfile",
                        default="",
                        help="ssh login identityfile path")
    parser.add_argument("-t" "--type",
                        action="store",
                        required=False,
                        dest="type",
                        default="default",
                        help="host type")
    parser.add_argument("-U", "--Username",
                        required=False,
                        action="store",
                        dest="Username",
                        default="ADMIN",
                        help="specify ipmi username")
    parser.add_argument("-c", "--command",
                        required=False,
                        action="store",
                        dest="command",
                        default="power on",
                        help="specify ipmi command")
    parser.add_argument("-P", "--Password",
                        required=False,
                        action="store",
                        dest="Password",
                        default="12345678",
                        help="specify ipmi password")

    args = parser.parse_args()
    host, host_type, ip_list = args.host, args.type, args.servers
    username, port, identityfile, password = args.user, args.port, args.identityfile, args.password

    ipmi_username, ipmi_password, ipmi_command = args.Username, args.Password, args.command

    # 查询需要登陆的主机ip
    hostname = get_host_ip(host, host_type)

    # 查询登陆需要的ssh配置信息
    ssh_conf = get_ssh_config(hostname, username, port, identityfile, password)

    try:
        with get_ssh(**ssh_conf) as ssh:
            # 对每台机器执行 ipmi 命令
            for short_ip in ip_list:
                ipmi_ip = get_ipmi_ip(short_ip, host_type)

                cmd = conf.ipmi_command % (ipmi_ip, ipmi_username, ipmi_password, ipmi_command)
                print_text("cmd: %s" % cmd)
                try:
                    output = ssh.run_cmd(cmd, timeout=3)
                    print_text("output: %s\n" % output)
                except RunCmdError as e:
                    print_error(e.err_msg)
    except SSHException as e:
        print_error(e.message)
        sys.exit(1)
