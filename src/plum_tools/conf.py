"""
#=============================================================================
#  ProjectName: plum_tools
#     FileName: conf
#         Desc: 相关常量配置信息
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-06 18:39
#=============================================================================
"""

import os
from enum import IntEnum, StrEnum

VERSION = "0.6.3"


STASH_UUID = "plum123456789987654321plum"
COMMAND_TIMEOUT = 3  # 执行命令超时时间
PROCESSES_NUMBER = 100  # 进程数量
LOCAL_HOST = "__localhost__"


class GitCommand(StrEnum):
    """git 相关命令"""

    STASH_LIST = "git stash list"  # 检查是否有文件在储藏区
    STATUS_DEFAULT = "git status"  # 检查文件状态
    STATUS_SHORT = "git status -s"  # 检查文件状态，简短输出，只能看到文件是否有改动，无法确认是否落后、超前远程分支
    BRANCH_ABBREV = "git rev-parse --abbrev-ref HEAD"  # 查询当前分支名
    STASH_SAVE = 'git stash save "%s"'  # 保存修改的文件到储藏区
    STASH_POP = "git stash pop --index %s"  # 把储藏的文件恢复
    GIT_CHECKOUT = "git checkout %s"  # 切换分支

    PULL_KEYWORD = '"git pull"'  # 落后远程分支关键字
    PUSH_KEYWORD = '"git push"'  # 超前远程分支关键字


class OsCommand(StrEnum):
    """系统 相关命令"""

    FIND_COMMAND = 'find %s -name ".git"'  # 通过系统命令查找文件路径
    PING_COMMAND = "ping -W 3 -c 1 %s"  # ping命令 -W 超时时间 -c 次数
    # ipmi命令
    IPMI_COMMAND = "ipmitool -I lanplus -H %(ip)s -U %(user)s -P %(password)s %(command)s"
    STAT_COMMAND = "stat %s"


class SSHConfig(IntEnum):
    """ssh配置相关"""

    DEFAULT_SSH_PORT = 22
    CONNECT_TIMEOUT = 3


class PathConfig(StrEnum):
    """相关配置文件"""

    HOME = os.environ["HOME"]
    ROOT = os.path.dirname(os.path.abspath(__file__))
    PLUM_YML_NAME = ".plum_tools.yaml"  # 项目需要的配置文件名
    PLUM_YML_PATH = os.path.join(HOME, PLUM_YML_NAME)  # 项目需要的配置文件路径
    SSH_CONFIG_NAME = ".ssh/config"  # ssh配置文件名
    SSH_CONFIG_PATH = os.path.join(HOME, SSH_CONFIG_NAME)  # ssh配置文件路径
