"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_conf
#         Desc: 测试枚举
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-03 22:58
#=============================================================================
"""

import os
import unittest

from plum_tools.conf import (
    GitCommand,
    OsCommand,
    PathConfig,
    SSHConfig,
)


class TestGitCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.g = GitCommand

    def tearDown(self) -> None:
        del self.g

    def test_pull_keyword(self) -> None:
        assert self.g.PULL_KEYWORD == '"git pull"'

    def test_push_keyword(self) -> None:
        assert self.g.PUSH_KEYWORD == '"git push"'

    def test_git_checkout(self) -> None:
        assert self.g.GIT_CHECKOUT == "git checkout %s"

    def test_branch_abbrev(self) -> None:
        assert self.g.BRANCH_ABBREV == "git rev-parse --abbrev-ref HEAD"

    def test_stash_list(self) -> None:
        assert self.g.STASH_LIST == "git stash list"

    def test_stash_pop(self) -> None:
        assert self.g.STASH_POP == "git stash pop --index %s"

    def test_stash_save(self) -> None:
        assert self.g.STASH_SAVE == 'git stash save "%s"'

    def test_status_default(self) -> None:
        assert self.g.STATUS_DEFAULT == "git status"

    def test_status_short(self) -> None:
        assert self.g.STATUS_SHORT == "git status -s"


class TestOsCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.o = OsCommand

    def tearDown(self) -> None:
        del self.o

    def test_find_command(self) -> None:
        assert self.o.FIND_COMMAND == 'find %s -name ".git"'

    def test_ipmi_command(self) -> None:
        assert self.o.IPMI_COMMAND == "ipmitool -I lanplus -H %(ip)s -U %(user)s -P %(password)s %(command)s"

    def test_ping_command(self) -> None:
        assert self.o.PING_COMMAND == "ping -W 3 -c 1 %s"

    def test_stat_command(self) -> None:
        assert self.o.STAT_COMMAND == "stat %s"


class TestSSHConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.s = SSHConfig

    def tearDown(self) -> None:
        del self.s

    def test_connect_timeout(self) -> None:
        assert self.s.CONNECT_TIMEOUT == 3

    def test_default_ssh_port(self) -> None:
        assert self.s.DEFAULT_SSH_PORT == 22


class TestPathConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.p = PathConfig

    def tearDown(self) -> None:
        del self.p

    def test_plum_yml_name(self) -> None:
        assert self.p.PLUM_YML_NAME == ".plum_tools.yaml"

    def test_ssh_config_name(self) -> None:
        assert self.p.SSH_CONFIG_NAME == ".ssh/config"

    def test_home(self) -> None:
        assert self.p.HOME == os.environ["HOME"]

    def test_plum_yml_path(self) -> None:
        assert self.p.PLUM_YML_PATH == os.path.join(self.p.HOME, self.p.PLUM_YML_NAME)

    def test_ssh_config_path(self) -> None:
        assert self.p.SSH_CONFIG_PATH == os.path.join(self.p.HOME, self.p.SSH_CONFIG_NAME)

    def test_root(self) -> None:
        current_path = os.path.dirname(os.path.abspath(__file__))
        assert self.p.ROOT == os.path.join(os.path.dirname(current_path), "src/plum_tools")
