#!/usr/bin/env python
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

# =========================================== git 相关命令 ===========================================
stash_list = "git stash list"  # 检查是否有文件在储藏区
status_default = "git status"  # 检查文件状态
status_short = "git status -s"  # 检查文件状态，简短输出，只能看到文件是否有改动，无法确认是否落后、超前远程分支

pull_keyword = '"git pull"'  # 落后远程分支关键字
push_keyword = '"git push"'  # 超前远程分支关键字

# =========================================== 系统 相关命令 ===========================================
find_command = 'find {} -name ".git"'  # 通过系统命令查找文件路径
