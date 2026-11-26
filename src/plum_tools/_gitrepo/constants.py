"""Git 仓库筛选状态和排序字段。"""

from plum_tools.utils.enums import DocStrEnum


class Status(DocStrEnum):
    """仓库筛选值与状态说明。"""

    ALL = "all", "全部"
    ISSUES = "issues", "存在异常或检查失败"
    DUPLICATE = "duplicate", "重复克隆"
    WORKTREE = "worktree", "链接工作树"
    CLEAN = "clean", "状态正常"
    STAGED = "staged", "暂存"
    UNSTAGED = "unstaged", "未暂存"
    UNTRACKED = "untracked", "未跟踪"
    CONFLICT = "conflict", "冲突"
    SUBMODULE = "submodule", "子模块有变更"
    STASH = "stash", "已储藏"
    AHEAD = "ahead", "领先"
    BEHIND = "behind", "落后"
    NO_UPSTREAM = "no-upstream", "无 upstream"
    GONE = "gone", "upstream 已失效"
    LOCAL_UPSTREAM = "local-upstream", "跟踪本地分支"
    DETACHED = "detached", "游离 HEAD"
    UNBORN = "unborn", "尚无提交"
    NO_REMOTE = "no-remote", "未配置远程仓库"
    ERROR = "error", "检查失败"


class RepositorySortField(DocStrEnum):
    """仓库排序字段及其含义。"""

    PATH = "path", "路径"
    NAME = "name", "目录名"
    BRANCH = "branch", "分支"
    REMOTE = "remote", "远程地址"
    STASH = "stash", "已储藏条目数"
    UNTRACKED = "untracked", "未跟踪数"
    STAGED = "staged", "暂存数"
    UNSTAGED = "unstaged", "未暂存数"
    CONFLICT = "conflict", "冲突数"
    AHEAD = "ahead", "各本地分支领先数合计"
    BEHIND = "behind", "各本地分支落后数合计"
