# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

`plum_tools` 是一个 Python 命令行工具包，面向 Linux/macOS 下的 SSH、Git 仓库检查、文件同步、IPMI、ping 网段扫描和 import 分析等日常运维/开发任务。

- 包源码在 `src/plum_tools/`，测试在 `tests/`。
- 构建后发布的 Python 包名是 `plum_tools`，wheel 包包含 `src/plum_tools`。
- 项目使用 `uv` 管理依赖，`hatchling`/`hatch-vcs` 构建与版本推导，`poethepoet` 动态生成常用任务。
- 支持 Python `>=3.10,<3.15`，CI 主要覆盖 Python 3.12、3.13、3.14。

## 常用命令

### 环境与依赖

```bash
uv sync
```

### 测试

```bash
uv run poe test
```

默认等价于运行 pytest 并统计覆盖率：`pytest -svv --cov=src --cov-fail-under=50 --cov-report=term-missing tests`。

运行单个测试文件或单个用例时，把 pytest 参数直接传给 poe 任务：

```bash
uv run poe test tests/test_gitrepo.py
uv run poe test tests/test_gitrepo.py::test_name -svv
```

`pyproject.toml` 中默认 pytest 参数会排除 `integration` 标记：`-m 'not integration'`。

### Lint / 类型检查 / 安全检查

```bash
uv run poe lint
uv run poe lint-parallel
uv run poe lint-mypy
uv run poe lint-black
uv run poe lint-isort
uv run poe lint-flake8
uv run poe lint-pylint
uv run poe lint-ruff
uv run poe lint-bandit
uv run poe lint-codespell
uv run poe lint-vulture
```

这些任务默认检查 `src bin tests`，也可以传入指定文件或目录：

```bash
uv run poe lint-mypy src/plum_tools tests
uv run poe lint-black src/plum_tools/prn.py
```

注意：`lint-ruff` 当前会执行 `ruff check ... --fix`，可能修改文件；需要只检查格式时使用 `lint-black`、`lint-isort` 等更具体任务。

### 格式化

```bash
uv run poe format
uv run poe format-autoflake
uv run poe format-isort
uv run poe format-black
uv run poe format-ruff
```

格式化任务同样支持传入指定源码路径。

### 构建与发布相关

```bash
uv build
bumpversion patch
bumpversion minor
```

发布 workflow 会在 tag 推送时构建 dist，并先发布到 TestPyPI，再发布到 PyPI。

### 清理与依赖升级

```bash
uv run poe clean
uv run poe clean-pyc
uv run poe clean-test
uv run poe upgrade-deps
uv run poe upgrade-pkg --pkg redis
uv run poe pyupgrade
```

`clean*` 任务会删除缓存、覆盖率、dist、`__pycache__` 等生成物；执行前确认当前工作区状态。

### pre-commit

```bash
uv run pre-commit run --all-files --show-diff-on-failure
```

本地 hook 包含 commitizen、codespell、mypy、ruff 和单元测试。

## 代码结构与架构

### CLI 入口

`pyproject.toml` 的 `[project.scripts]` 暴露以下命令：

- `gitrepo` -> `plum_tools.gitrepo:main`：递归查找目录下的 git 仓库，并检查未提交修改、远程超前/落后和可选 stash 状态。
- `gitstash` -> `plum_tools.gitstash:main`：切分支前按当前分支标记 stash，切到目标分支后恢复对应 stash。
- `pssh` -> `plum_tools.pssh:main`：根据 IP 简写或 `~/.ssh/config` 别名拼接并执行 SSH 登录命令。
- `pping` -> `plum_tools.pping:main`：并发 ping 指定网段内的 1-254 地址，输出可达 IP。
- `pipmi` -> `plum_tools.pipmi:main`：先 SSH 到登录机，再对目标机器执行 `ipmitool` 命令。
- `prn` -> `plum_tools.prn:main`：基于 rsync 上传/下载项目文件，配置来自 `~/.plum_tools.yaml` 或命令行参数。
- `pfind_imports` -> `plum_tools.find_imports:main`：用 AST 扫描 Python import，按标准库/第三方库筛选输出。

每个 CLI 模块通常包含 `main()`、参数解析和业务函数/类；共享参数解析来自 `src/plum_tools/utils/parser.py`。

### 配置模型

核心配置在 `src/plum_tools/conf.py`：

- `PathConfig.PLUM_YML_PATH` 指向用户家目录下的 `~/.plum_tools.yaml`。
- `src/plum_tools/.plum_tools.yaml` 是示例配置，包含默认 SSH 配置、`host_type_*` 网段前缀、IPMI 偏移和项目同步配置。
- `GitCommand`、`OsCommand`、`SSHConfig` 集中维护 shell/git/ssh 相关常量。

`src/plum_tools/utils/utils.py` 中的 `YmlConfig.parse_config_yml()` 负责读取并缓存 YAML 配置；依赖配置的命令在测试中通常需要 mock 该解析结果或隔离 HOME/配置路径。

### SSH 与主机解析

`src/plum_tools/utils/sshconf.py` 负责：

- 根据 `host_type_<type>` 将 IP 简写补全为完整 IP。
- 解析 `~/.ssh/config` 中的 Host 别名。
- 将命令行覆盖项、YAML 默认 SSH 配置和 SSH alias 配置合并。

`pssh`、`prn`、`pipmi` 都依赖这层解析逻辑。改动主机解析时，应优先补充 `tests/utils/test_sshconf.py` 以及对应 CLI 测试。

### 命令执行与外部进程

`src/plum_tools/utils/utils.py` 的 `run_cmd()` 是多数模块调用 shell 命令的统一入口，失败时抛出 `RunCmdError`，超时时抛出 `RunCmdTimeout`。

已有代码中不少功能会执行系统命令或外部工具（git、ssh、rsync、ping、ipmitool、find/stat）。测试这类逻辑时优先 mock `run_cmd()`、`subprocess`、`os.system()`、`paramiko.SSHClient` 或 `multiprocessing.Pool`，避免真实访问网络、SSH、文件同步或本机大量目录。

### 测试布局

- CLI 顶层模块测试位于 `tests/test_*.py`。
- 共享工具测试位于 `tests/utils/test_*.py`。
- `tests/common.py` 提供测试辅助能力。
- `tests/test_poe_tasks.py` 覆盖 `bin/poe_tasks.py` 中动态 poe 任务和 pytest 参数透传逻辑。

新增或修改某个模块时，优先在同名测试文件中补充测试；没有对应文件时按现有命名模式创建。

## 代码风格与工具配置要点

- Black、isort、flake8、pylint、ruff 的行宽均按 120 处理。
- mypy 对 `src.*`、`tests.*`、`bin.*` 要求函数定义有类型标注（`disallow_untyped_defs = true`）。
- Ruff 选择 `E/F/B/R` 并启用 import 排序检查；`__init__.py` 允许未使用 import 和未排序 import。
- Bandit 配置在 `pyproject.toml`，部分历史告警被跳过；涉及 shell、SSH、反序列化或密码参数的改动仍需重点审查。
- commit message 由 commitizen hook 校验。
