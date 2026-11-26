"""gitstash 命令行入口。"""

import os
import sys

from plum_tools.utils.cli import cli_entry
from plum_tools.utils.constants import STASH_UUID, GitCommand
from plum_tools.utils.exceptions import RunCmdError
from plum_tools.utils.git import check_repository_modify_status, check_repository_stash, get_current_branch_name
from plum_tools.utils.parser import get_base_parser
from plum_tools.utils.printer import print_warn
from plum_tools.utils.utils import cd, run_cmd


class GitCheckoutStash:
    """切换分支前储藏文件"""

    def __init__(self, current_branch: str, new_branch: str) -> None:
        """初始化信息

        :param current_branch: 当前分支名
        :example current_branch master

        :param new_branch: 新的分支名
        :example new_branch release-1.0.0
        """
        self._current_branch = current_branch
        self._current_path = os.getcwd()  # 当前执行命令的路径
        self._new_branch = new_branch
        self._mark = "-"
        self._stash_uuid = f"{self._current_branch}{self._mark}{STASH_UUID}"

    def _stash(self) -> None:
        """储藏文件"""
        # 分支有修改,先进行stash储藏
        is_modify, _ = check_repository_modify_status(self._current_path)
        if is_modify:
            cmd = GitCommand.STASH_SAVE % self._stash_uuid
            with cd(self._current_path):
                run_cmd(cmd)

    def _check_branch(self) -> bool:
        """检查分支是否一致

        :return
            True: 当前分支和要切换的分支一致
            False: 当前分支和要切换的分支不一致
        """
        return self._current_branch == self._new_branch

    def _checkout(self) -> None:
        """切换分支"""
        # 切换到新分支
        cmd = GitCommand.GIT_CHECKOUT % self._new_branch
        with cd(self._current_path):
            run_cmd(cmd)

    def _apply(self) -> None:
        """恢复储藏的文件"""
        # 检查切换后的分支是否有储藏文件
        is_stash, stash_out = check_repository_stash(self._current_path)
        if not is_stash:
            return
        for line in stash_out.splitlines():
            stash_string, _ = line.split(":", 1)
            stash_save = f"{self._new_branch}{self._mark}{STASH_UUID}"
            if stash_save.strip() in line:
                cmd = GitCommand.STASH_POP % stash_string
                with cd(self._current_path):
                    run_cmd(cmd)
                break

    def checkout(self) -> None:
        """储藏文件切换分支"""
        # 不需要切换
        if self._check_branch():
            return
        self._stash()
        self._checkout()
        self._apply()


@cli_entry
def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    parser.description = "切换 Git 分支前保存本地修改，切换后恢复目标分支上次保存的修改。"  # noqa
    parser.epilog = (
        "示例：\n  gitstash master\n  gitstash release-1.0.0\n\n请在 Git 仓库内执行，目标分支须可由 git checkout 切换。"
    )
    parser.add_argument(dest="branch", action="store", help="目标分支名，必填")
    args = parser.parse_args()
    new_branch = args.branch
    try:
        current_branch = get_current_branch_name()
    except RunCmdError:
        print_warn("当前目录不是一个 Git 仓库")
        sys.exit(1)
    stash = GitCheckoutStash(current_branch, new_branch)
    stash.checkout()


if __name__ == "__main__":
    raise SystemExit(main())
