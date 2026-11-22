"""定义清理类别、重建依据和保护规则。"""

from __future__ import annotations

from enum import IntEnum
from pathlib import Path

from ..utils.compat import StrEnum


class Command(StrEnum):
    """区分文件计划流程与原生工具清理入口。"""

    SCAN = "scan"
    SHOW = "show"
    RUN = "run"
    PRUNE = "prune"


class PruneAction(StrEnum):
    """原生工具独立预览或在当次确认后执行。"""

    SHOW = "show"
    RUN = "run"


class Category(StrEnum):
    """清理类别及命令行中的全选值。"""

    ALL = "all"
    USER_CACHE = "user-cache"
    SYSTEM_CACHE = "system-cache"
    PROJECT_CACHE = "project-cache"
    BUILD = "build"
    DEPS = "deps"
    TOOLS = "tools"
    DOCKER = "docker"


class Tool(StrEnum):
    """支持查询和清理缓存的开发工具。"""

    BREW = "brew"
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    PIP = "pip"
    UV = "uv"
    GO = "go"


class DockerTask(StrEnum):
    """区分 Docker 镜像与构建缓存的原生清理任务。"""

    IMAGES = "docker-images"
    BUILD = "docker-build"


# 任务标识保留在 JSON 中，终端使用中文名称。
DOCKER_TASK_LABELS: dict[str, str] = {DockerTask.IMAGES: "Docker 悬空镜像", DockerTask.BUILD: "Docker 构建缓存"}


class ProjectKind(StrEnum):
    """生成物规则能够识别的项目类型。"""

    NODE = "node"
    PYTHON = "python"
    GO = "go"
    RUST = "rust"
    MAVEN = "maven"
    GRADLE = "gradle"
    CMAKE = "cmake"
    SWIFT = "swift"


class ExitCode(IntEnum):
    """区分完成、清理失败、参数错误与用户中断。"""

    SUCCESS = 0
    FAILURE = 1
    USAGE = 2
    INTERRUPTED = 130  # noqa


class PlanVersion(IntEnum):
    """标识清理计划格式，拒绝不兼容的历史计划。"""

    CURRENT = 1


class PlanFile(StrEnum):
    """默认预览和执行在当前目录共享同一个计划文件。"""

    DEFAULT = ".pclean-plan.json"


class SnapshotMode(StrEnum):
    """区分整棵目录的状态快照和仅确认目录身份的快速快照。"""

    TREE = "tree"
    DIRECTORY = "directory"


class ScanTuning(IntEnum):
    """统一候选计量的默认线程数和进度上报批次。"""

    WORKERS = 1
    PROGRESS_BATCH = 128


class ExecutionLimits(IntEnum):
    """限制批量复核保留的节点数，超限候选改为逐项重新计量。"""

    CACHED_NODES = 50_000


# 包标记只在单次计量内缓存，并在计量结束时确认没有变化。
PackageChecks = dict[tuple[Path, bool], tuple[int, ...] | None]


# 这些参数决定扫描范围，加载计划时只能使用计划内保存的值。
PLAN_OPTIONS = (
    "root",
    "category",
    "exclude",
    "include_generated",
    "older_than",
    "fast_deps",
)
# 按展示顺序定义实际类别，all 仅用于参数展开。
CATEGORY_LABELS = {
    Category.USER_CACHE: "用户缓存与日志",
    Category.SYSTEM_CACHE: "系统缓存",
    Category.PROJECT_CACHE: "项目缓存",
    Category.BUILD: "构建产物",
    Category.DEPS: "依赖环境",
    Category.TOOLS: "工具缓存",
    Category.DOCKER: "Docker 缓存",
}
# 项目类别共用目录遍历，只扫描一次。
PROJECT_CATEGORIES = {Category.PROJECT_CACHE, Category.BUILD, Category.DEPS}
# 动态范围只能由原生工具当次查询和清理，不写入文件计划。
PRUNE_CATEGORIES = {Category.TOOLS, Category.SYSTEM_CACHE, Category.DOCKER}
# Homebrew 下载缓存仍逐文件进入计划，其余工具使用原生命令。
PRUNE_TOOLS = tuple(tool for tool in Tool if tool != Tool.BREW)
# 依赖目录仅在选中 deps（包括默认 all）且可按配置重建时进入候选清单。
DEPENDENCIES = {"node_modules", ".node_modules", ".venv", "venv", ".tox", ".nox", "vendor"}
# 这些名称提供足够明确的缓存语义，其余名称需要显式添加。
PROJECT_CACHES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".parcel-cache",
    ".turbo",
    ".vite",
    ".eslintcache",
    ".stylelintcache",
    ".tsbuildinfo",
    ".nyc_output",
}
# Go 覆盖率文件还必须校验格式头，不能仅凭通用文件名清理。
GO_COVERAGE_FILES = {"coverage.out", "coverage.txt", "cover.out", "coverprofile.out"}
# 构建目录还必须匹配相应项目标记。
BUILD_DIRS = {
    "dist": {ProjectKind.PYTHON, ProjectKind.NODE},
    "build": {
        ProjectKind.PYTHON,
        ProjectKind.NODE,
        ProjectKind.GRADLE,
        ProjectKind.CMAKE,
    },
    "target": {ProjectKind.RUST, ProjectKind.MAVEN},
    ".next": {ProjectKind.NODE},
    ".nuxt": {ProjectKind.NODE},
    ".output": {ProjectKind.NODE},
    ".svelte-kit": {ProjectKind.NODE},
    "coverage": {ProjectKind.NODE, ProjectKind.PYTHON},
    "htmlcov": {ProjectKind.PYTHON},
    ".build": {ProjectKind.SWIFT},
}
# 项目标记用于记录重建依据和执行前复核配置快照。
PROJECT_MARKERS = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "uv.lock",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "tox.ini",
    "noxfile.py",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "CMakeLists.txt",
    "Package.swift",
    "Package.resolved",
}
# 锁文件单独存在时不足以推断 Python 项目。
PYTHON_MARKERS = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "tox.ini",
    "noxfile.py",
}
# 优先按项目已有锁文件选择 Node 安装方式。
NODE_INSTALL_COMMANDS = (
    ("pnpm-lock.yaml", "pnpm install"),
    ("yarn.lock", "yarn install"),
    ("package-lock.json", "npm ci"),
)
# Python 管理工具优先于通用的 pip 安装方式。
PYTHON_INSTALL_COMMANDS = (
    ("uv.lock", "uv sync"),
    ("poetry.lock", "poetry install"),
    ("Pipfile", "pipenv install"),
)
# 构建命令只用于说明重建方式，不会在清理流程中执行。
BUILD_COMMANDS = (
    ("go.mod", ProjectKind.GO, "go build ./..."),
    ("Cargo.toml", ProjectKind.RUST, "cargo build"),
    ("pom.xml", ProjectKind.MAVEN, "mvn package"),
    ("build.gradle", ProjectKind.GRADLE, "gradle build"),
    ("build.gradle.kts", ProjectKind.GRADLE, "gradle build"),
    ("CMakeLists.txt", ProjectKind.CMAKE, "cmake -S . -B build；cmake --build build"),
    ("Package.swift", ProjectKind.SWIFT, "swift build"),
)
# 凭证、本地数据及仓库元数据不能因目录被忽略而进入删除范围。
PROTECTED_NAMES = {
    ".Trash",
    ".git",
    ".hg",
    ".svn",
    ".ssh",
    ".gnupg",
    ".aws",
    ".kube",
    ".docker",
    ".config",
    "credentials.json",
    "auth.json",
    "key.json",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "secrets",
}
# 依赖和内置项目缓存也会包含这些名称，其余范围仍按本地数据保护。
USER_DATA_NAMES = {"data", "uploads", "backups"}
# 文件级规则额外保护密钥、数据库和未完成的工具操作。
PROTECTED_PATTERNS = (
    ".env",
    ".env.*",
    "*.key",
    "*.age",
    "id_rsa*",
    "id_ed25519*",
    "*.sqlite*",
    "*.db",
    "*.lock",
    "*.incomplete",
    "*.partial",
    "*.pid",
    "*.sock",
)
# 按类别预计算保护规则，避免每个节点重复过滤。
CATEGORY_PROTECTED_PATTERNS = {
    category: tuple(pattern for pattern in PROTECTED_PATTERNS if pattern not in omitted)
    for category, omitted in (
        (Category.BUILD, {"*.lock"}),
        (Category.DEPS, {"*.lock", "*.db", "*.sqlite*"}),
        (Category.PROJECT_CACHE, {"*.lock", "*.db", "*.sqlite*"}),
    )
}
# 用户缓存扫描避开由原生工具管理的目录和可包含源码的 chezmoi 工作区。
MANAGED_CACHE_NAMES = {
    "homebrew",
    "npm",
    "pnpm",
    "yarn",
    "pip",
    "uv",
    "go-build",
    "chezmoi",
    "node-gyp",
    "pypoetry",
    "pre-commit",
    "corepack",
}
# 查询禁止可选锁、自动下载和自动更新，以减少预览阶段的副作用。
QUERY_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "COREPACK_ENABLE_NETWORK": "0",
    "HOMEBREW_NO_AUTO_UPDATE": "1",
    "HOMEBREW_NO_ANALYTICS": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "UV_PYTHON_DOWNLOADS": "never",
    "GOTOOLCHAIN": "local",
}
