# -*- coding: utf-8 -*-

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

# =========================================== git 相关命令 ===========================================
stash_list = "git stash list"  # 检查是否有文件在储藏区
status_default = "git status"  # 检查文件状态
status_short = "git status -s"  # 检查文件状态，简短输出，只能看到文件是否有改动，无法确认是否落后、超前远程分支
branch_abbrev = "git rev-parse --abbrev-ref HEAD"  # 查询当前分支名
stash_save = 'git stash save "%s"'  # 保存修改的文件到储藏区
stash_pop = "git stash pop --index %s"  # 把储藏的文件恢复
git_checkout = 'git checkout %s'  # 切换分支

pull_keyword = '"git pull"'  # 落后远程分支关键字
push_keyword = '"git push"'  # 超前远程分支关键字

# =========================================== 系统 相关命令 ===========================================
find_command = 'find %s -name ".git"'  # 通过系统命令查找文件路径
ping_command = "ping -W 3 -c 1 %s"  # ping命令 -W 超时时间 -c 次数
ipmi_command = "ipmitool -I lanplus -H %s -U %s -P %s %s"  # ipmi命令
stat_command = "stat %s"

# =========================================== ssh配置相关 ===========================================
default_ssh_port = 22
connect_timeout = 3

# =========================================== 相关常量 ===========================================
stash_uuid = "plum123456789987654321plum"

# =========================================== 相关配置文件 ===========================================
home = os.environ["HOME"]
root = os.path.dirname(os.path.abspath(__file__))
plum_yml_name = ".plum_tools.yaml"  # 项目需要的配置文件名
plum_yml_path = os.path.join(home, plum_yml_name)  # 项目需要的配置文件路径
ssh_config_name = ".ssh/config"  # ssh配置文件名
ssh_config_path = os.path.join(home, ssh_config_name)  # ssh配置文件路径
