# linux 小工具

[![LICENSE](https://img.shields.io/github/license/seekplum/plum_tools.svg)](https://github.com/seekplum/plum_tools/blob/master/LICENSE)
[![codecov](https://codecov.io/gh/seekplum/plum_tools/branch/master/graph/badge.svg)](https://codecov.io/gh/seekplum/plum_tools)
[![CI](https://github.com/copier-org/copier/workflows/CI/badge.svg)](https://github.com/copier-org/copier/actions?query=branch%3Amaster)
[![pypi version](https://img.shields.io/pypi/v/plum_tools?logo=pypi&logoColor=%23959DA5)](https://pypi.python.org/pypi/plum_tools)
[![pyversions](https://img.shields.io/pypi/pyversions/plum_tools?logo=python&logoColor=%23959DA5)](https://pypi.python.org/pypi/plum_tools)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


## 目录结构

所有命令的安装入口统一位于 `src/plum_tools/cli/`，文件名与终端命令名一致。例如，`gitrepo` 的入口是 `cli/gitrepo.py`，`pcompare` 的入口是 `cli/pcompare.py`。入口映射在 `pyproject.toml` 的 `[project.scripts]` 中。

```text
src/plum_tools/
├── cli/                # 命令行入口与参数分派
├── _gitrepo/           # 仓库读取、并发扫描、筛选、分组和报告
├── _compare/           # 本地比较、报告和可独立执行的远端扫描脚本
├── _cleanup/           # 清理计划、扫描和执行
├── _prn/               # 同步配置、路径和 rsync 执行
├── _pipmi/             # 主机配置和跳板机连接
├── _find_imports/      # Python 导入扫描和报告
├── _fork_check/        # 仓库对检查和报告
├── _agent_usage/       # 使用记录采集和报告
└── utils/              # 命令间共享的 CLI、Git、SSH、排序和枚举工具
```

`gitstash.py`、`pssh.py`、`pping.py` 等单模块工具的业务逻辑与入口同放在 `cli/` 中。项目任务脚本位于 `bin/`，文档位于 `docs/`。`tests/` 按源码子目录组织，例如 `tests/cli/`、`tests/_prn/` 和 `tests/utils/`。

## 安装环境依赖

项目支持 Python `>=3.11,<3.15`，CI 覆盖 Python 3.11、3.12、3.13、3.14。
`pcompare` 的独立远端扫描脚本支持远端 Python 3.9+，无需在远端安装本项目。

1.安装 [uv](https://github.com/astral-sh/uv)

```bash
# 推荐
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或
pip install uv
```

2.安装项目依赖环境

```bash
uv sync
```


## 运行单元测试

```bash
uv run poe test
```

## 检查 Python 代码规范

```bash
uv run poe lint
```

## 更新版本

版本号、发布日期和构建提交集中维护在 `src/plum_tools/_version.py`，
Hatch 直接从该文件读取包版本。使用 `bump-my-version` 同步更新版本号与发布日期，
日期采用执行环境的本地日期（`YYYY-MM-DD`），并按现有配置创建提交和标签。

```bash
# 小版本
uv run bump-my-version bump patch

# 中版本
uv run bump-my-version bump minor
```

发布 workflow 在构建前将当前检出提交的完整 ID 写入 `COMMIT_ID`，
随 wheel 和 sdist 一起打包。所有使用公共参数解析器的命令均通过 `--version`
展示版本、发布日期及提交前 12 位，例如：

```text
pcompare 版本: 0.6.6（2026-11-19） 提交: a1b2c3d4e5f6
```

尚未记录日期时显示 `开发版`，下次升版时自动填入日期。
未注入提交信息的本地源码版本不显示 `提交` 字段；提交信息不改变 PyPI 包版本号。

所有命令的 `--help` 均使用中文说明，并提供示例命令。存在默认值或可选值的参数会说明其取值或配置来源。
参数名、JSON 字段和枚举值保持原样；外部命令及系统的原始诊断保留原文。

所有命令支持 Ctrl+C 取消：停止当前任务并清理资源，向标准错误输出“已取消”，
以退出码 `130` 结束，不打印 Python 异常堆栈。扫描、等待子命令及输出表格时均可取消，
进程池和线程池会停止后续任务，加载动画和进度条自动关闭。
交互式 `pssh` 会话中的 Ctrl+C 仍交给 SSH 处理，用于中断远端当前命令。

## 紧凑模式

在宽终端中使用 `--compact` 减少结果占用的行数，默认关闭。
支持 `gitrepo scan`、`pfind_imports`、`pping`、
`pcompare` 和 `pipmi`：

```bash
gitrepo scan -p ~/PythonProjects --compact
gitrepo scan -p ~/PythonProjects --status issues -d --compact
pfind_imports -p . --compact
pping -p 192.168.1 --compact
pcompare ./backup_a ./backup_b --compact
pipmi -l 192.168.1.10 -s 20 21 -c 'power status' --compact
```

Git 仓库和文件比较表格精简边框，仓库状态摘要使用同行排列，文件及 stash 详情逐项展示。
`pfind_imports` 按标准库、第三方库分组并分栏，导入名与包名不同时显示
`导入名→包名`，相同时仅显示一次。`pping` 按 IP 地址顺序分栏。
分栏数量随终端宽度调整，长路径和错误内容继续换行显示。
`pipmi` 将主机、操作及单行结果合并展示，多行结果保留原有结构。

`--compact` 只影响展示，不改变扫描、比较、执行操作或退出码。
与 `--json` 同时使用时，JSON 内容和格式保持原样；
`pping` 未启用 `--json` 时，输出重定向或通过管道传递仍保持每行一个 IP。
`prn`、`pssh` 和 `gitstash` 未提供紧凑模式。

## gitrepo

必须指定 `scan` 子命令，业务参数统一放在子命令后。
原 `check` 已合并到 `scan`，旧命令不再接受，改用 `--status issues` 筛选异常仓库：

```bash
gitrepo scan -p ~/PythonProjects --status issues -d
```

默认展示仓库、目录和状态摘要；`-d/--detail` 额外展示“当前分支”“远程”两列，
以及文件路径、变更类型和 stash 条目。检查失败原因始终显示。
文件变更使用 Git 的两位状态码，第一位表示暂存区，第二位表示工作区，`.` 表示无变化，
`??` 表示未跟踪，重命名显示原路径与新路径；路径使用引号和转义保留空格、换行等特殊字符。
工作区修改和 stash 同时存在时，两者详情都会展示。
`issues` 匹配任意检查异常或错误，单纯重复克隆或 worktree 不计为异常。
筛选无结果且没有目录错误时不输出仓库表格，仍显示扫描统计。

使用 `scan` 子命令扫描并通过 Rich 表格聚合展示仓库，默认扫描家目录，
按远程主机分表，例如 `github.com`、`gitlab.com` 各一张表。
表内默认按全部远程地址的直接或间接关联合并仓库目录：

```bash
# 扫描多个目录，按远程主机分表、远程地址合并仓库
gitrepo scan -p ~/PythonProjects ~/work

# 按远程主机分表、仓库目录名合并仓库
gitrepo scan -p ~/PythonProjects --group-by name

# 仅展示重复克隆的目录
gitrepo scan -p ~/PythonProjects --status duplicate

# 展示领先或有已储藏记录的目录，多个状态按“或”匹配
gitrepo scan -p ~/PythonProjects --status ahead stash

# 查找本地文件变更，忽略仅切换子模块提交的情况
gitrepo scan -p ~/PythonProjects --status staged unstaged untracked --ignore-status submodule-pointer -d

# 查找异常，忽略分支落后和游离 HEAD
gitrepo scan -p ~/PythonProjects --status issues --ignore-status behind detached

# 仅展示链接工作树
gitrepo scan -p ~/PythonProjects --status worktree

# 更新远程引用后检查
gitrepo scan -p ~/PythonProjects --fetch

# 按目录名跳过不需要遍历的子目录
gitrepo scan -p ~/PythonProjects --exclude node_modules .venv

# 只展示匹配主机的表格，多个通配模式用 | 分隔
gitrepo scan -p ~/PythonProjects --host '*.xxx.net|github.com'

# 使用正则完整匹配主机，与 --host 互斥
gitrepo scan -p ~/PythonProjects --host-regex '.*\.xxx\.net|github\.com'

# 忽略 stash
gitrepo scan -p ~/PythonProjects --ignore-stash
```

主机筛选不区分大小写、不含端口，匹配分组内任一远程主机即可保留该组，
两种 `--group-by` 模式均适用。`--host` 支持 `*`、`?`、`[]` 通配符。
仅含本地远程路径，或无远程 / 无法识别的分组不匹配主机筛选；
筛选仅影响展示，所有仓库仍会扫描，统计保留扫描总数。
无效的 `--host-regex` 在扫描前报错。

`--status` 默认 `all`，支持空格分隔多个值，也可重复指定参数，匹配任一状态即保留目录。
`--ignore-status` 支持多个值和重复传参，在统计、展示及 `--status` 筛选前逐项忽略：

- `submodule-pointer` 忽略未暂存的子模块提交指针变化，保留已暂存的指针、模块内文件修改及未跟踪文件。
- `ahead`、`behind` 分别忽略本地分支领先、落后于跟踪分支的状态。
- `detached` 忽略游离 HEAD 提示，分支详情仍显示当前提交。

指定忽略项后，`clean` 表示其余检查均正常，JSON 的 `options.ignored_statuses` 列出本次忽略项。
指定 `all` 时不限制状态；状态筛选与主机筛选同时生效，空分组不展示。
重复关联在筛选前计算，隐藏连接两个仓库的中间仓库不会改变已有分组或重复标记。

| 状态 | 含义 |
| --- | --- |
| `all` | 全部目录，默认值 |
| `issues` | 任意本地 / 跟踪异常或检查错误，不含单纯重复克隆和 worktree |
| `duplicate` | 远程关联组内存在至少两个独立 Git 仓库 |
| `worktree` | 链接工作树，不包含主工作树 |
| `clean` | 工作区和跟踪状态正常，且无检查错误 |
| `staged` / `unstaged` / `untracked` / `conflict` | 暂存 / 未暂存 / 未跟踪 / 冲突 |
| `submodule` | 父仓库检测到子模块变更，包括提交指针变化、模块内文件修改或未跟踪文件 |
| `stash` | 已储藏，数量为 `git stash list` 中的条目数 |
| `ahead` / `behind` | 任一本地分支领先 / 落后于跟踪引用 |
| `no-upstream` / `gone` / `local-upstream` | 无 upstream / upstream 失效 / 跟踪本地分支 |
| `detached` / `unborn` | 游离 HEAD / 尚无提交 |
| `no-remote` | 未配置远程仓库，`git remote` 输出为空 |
| `error` | 检查失败，包含远程更新失败 |

`clean` 可与 `duplicate`、`worktree` 同时成立。
原 `--duplicates` 已移除，使用 `--status duplicate` 替代；多个状态按“或”匹配。

`scan` 默认检查并展示 stash，使用 `--ignore-stash` 跳过 stash 查询和展示，
stash 不再计入异常，其他工作区和分支检查照常执行。
不再接受 `-s/--stash`、省略子命令的写法或放在子命令前的业务参数。

`scan` 支持 `--json`：

```bash
gitrepo scan -p ~/PythonProjects --json
gitrepo scan -p ~/PythonProjects --json --ignore-stash
gitrepo scan -p ~/PythonProjects --json --host '*.xxx.net|github.com'
gitrepo scan -p ~/PythonProjects --json --status duplicate | jq '.repositories[].path'
```

JSON 模式的 stdout 只输出一个 JSON 对象，进度条写入 stderr；stderr 不是终端时关闭动态进度。
顶层包含 `schema_version`（`2`）、`command`（`scan`）、
无结果时两个数组为空，目录扫描错误逐条保留 `path` 和 `reason`。

JSON 始终收集文件与 stash 详情，不受 `-d` 限制；`--ignore-stash` 同时跳过 stash 详情查询。
`scan` 的每项提供 `path`、`common_dir`、`remote_name`、规范化的 `remote_url`、`branch`、
`bare`、`worktree`、`issues`、`errors`、`remotes`、`statuses`、`changes`、`stashes`、`counts`，以及 `host`、`group_key`、`kind`、
`duplicate_clone`、`has_issues`、`failed`。
`kind` 为 `normal`、`bare` 或 `worktree`；`host` 不含端口，
本地及无远程仓库的 `host` 分别为 `本地路径`、`无远程 / 无法识别`。
`remotes` 按 remote 名称保存规范化后的全部 fetch/push 地址，重复地址只保留一次；
`remote_name`、`remote_url` 保留首选 remote 及其首个有效地址。
`statuses` 保存实际命中的状态码，可同时包含 `clean`、`duplicate`、`worktree` 等多个状态。
`changes` 保存每个文件的 `status`、`path`，重命名或复制时另有 `original_path`。
子模块变更条目还包含 `submodule` 字段，值为中文说明，例如 `"submodule": "子模块（提交指针变更）"`。
`stashes` 保存完整 stash 条目，正常仓库的两个详情数组均为空。
`counts` 保存已读取的文件状态、stash 和分支差异计数；未读取的指标不包含在该对象中。
`issues`、`errors` 是可读消息；仓库检查失败或扫描到错误目录后仍会输出其余结果。

`summary` 的 `repository_count`、`issue_repository_count`、`failed_repository_count`、
`directory_error_count` 是全量扫描统计，`shown_repository_count` 对应 JSON 中的仓库条目数。
`scan` 另有 `independent_repository_count`、`group_count`、`shown_group_count` 和 `duplicate_group_count`。
`duplicate_group_count` 按全量扫描的远程关联组计数，不受展示分组与筛选影响。
`scan` 的 `repositories` 沿用主机过滤、状态筛选及分组规则，
两种分组模式都只保留状态命中的目录。
`options.stash_checked` 表示是否启用 stash 检查；`scan` 另记录 `group_by`、`statuses`、`fetch`。
`scan` JSON 已升级为版本 `2`：`options.duplicates_only` 由 `options.statuses` 替代，
`summary.duplicate_remote_count` 由 `summary.duplicate_group_count` 替代。

首选远程优先选择名为 `upstream` 的 remote，其次选择 `origin`，
其余 remote 按名称排序选择第一个有效地址，仅用于保留首选远程字段。
分组和重复判断使用所有 remote 的全部 fetch/push 地址。
分支的 upstream 指各分支配置的跟踪目标，
独立于用于分组的 remote。

远程分组将同一主机及仓库路径的 SSH、HTTPS 地址和 `.git` 后缀规范化，
保留仓库路径大小写及非默认端口。本地路径与 `file://` 地址按实际路径聚合，
SSH 主机别名不会自动解析为相同主机。
任意远程地址相同即关联仓库，并合并间接关联：A 的地址为 `{a,b}`，
B 为 `{b,c}`，C 为 `{c}` 或 `{c,d}` 时，A/B/C 同属一个关联组。
同组存在多个独立 Git 仓库时，组内全部目录标记为重复克隆。
worktree 逐个展示并带有 `worktree` 状态，共用 Git 数据的目录不计为独立克隆。
两种模式使用相同布局：同一仓库的名称仅在首行显示，后续行留空，
仓库组之间加分隔线，形成纵向合并效果；每个目录保留自己的状态，
开启 `--detail` 后额外展示当前分支和全部远程地址。
远程关联组以规范化地址排序后的首项作为稳定分组标识，以该地址的主机决定表格归属；
跨主机的关联组只展示一次，筛选其他关联主机时仍显示在该代表主机下。
`--group-by name` 按代表主机下的目录名合并，开启 `--detail` 后逐行展示远程地址，
同名但远程不同的仓库会单独标记。非默认端口仍用于区分远程仓库，
相同主机不同端口的仓库放在同一张表。
本地远程路径和无远程 / 无法识别的仓库分别集中到独立表格。
`--status duplicate` 只展示重复克隆关联组内的目录。

扫描支持普通仓库、嵌套仓库、worktree、子模块和裸仓库；
重叠扫描路径会去重，扫描时跳过 `.git` 内部目录，不递归跟随目录符号链接。
扫描显示目录发现和仓库检查进度、耗时及检查失败数量，
输出重定向时关闭动态进度条。默认不排除其他目录，
可通过 `--exclude` 按名称跳过子目录，显式指定的扫描根目录仍会检查。
`scan` 在发现仓库后立即提交有界并发检查，合并工作区、当前分支和 stash 查询，
同一仓库的 worktree 共用分支、stash 详情读取及 fetch。
表格同时展示暂存、未暂存、未跟踪、冲突及已储藏条目数，
并检查所有本地分支的领先、落后、无 upstream、upstream 失效及游离 HEAD 状态。
无远程、空仓库、读取失败及远程更新失败也会显示。

默认检查依据本地缓存的远程引用。`--fetch` 会更新所有已配置远程的引用，
并可能触发 Git 的身份认证；更新失败时会标记错误并依据现有引用检查。
upstream 失效表示对应的本地跟踪引用不存在，
远程分支的删除是否反映到本地取决于 Git 的 fetch 清理配置。

## pfind_imports

扫描 Python 项目的绝对导入，通过 Rich 表格展示导入名、映射后的包名和分类，
默认仅展示第三方库。文件发现与解析进度显示在 stderr，包含文件数、错误数及耗时；
stderr 不是终端时关闭动态进度。

```bash
# 扫描项目中的第三方库
pfind_imports -p ./project

# 展示标准库和第三方库
pfind_imports -p ./project --mode all

# 精确忽略指定 Python 文件，并添加导入名到包名的映射
pfind_imports -p ./project -i ./project/ignored.py -e custom=custom-package

# 使用 JSON 结果提取包名
pfind_imports -p ./project --json | jq -r '.modules[].package_name'
```

`--mode` 支持 `std`、`3rd-party`、`all`。同一顶层导入名仅保留首次发现的记录，
排除相对导入、项目根目录和 `src` 下的本地模块名，跳过 `.venv`、`__pycache__`。
内置 `PIL → pillow`、`grpc → grpcio` 映射，优先于 `--extra/-e`；
同一包有多个导入名时仍按导入名分别展示。

`--json` 的 stdout 只输出一个 JSON 对象，包含 `schema_version`（当前为 `1`）、
`project_dir`（绝对路径）、`mode`、`summary`、`modules`、`errors`。
每个模块包含 `name`（顶层导入名）、`origin_name`（原始模块名）、
`type`（`import` 或 `from`）、`mode`、`package_name`（映射后的包名）。
`summary` 提供 `file_count`（排除后发现的 Python 文件数）、
`scanned_file_count`（已处理文件数，包含解析失败的文件）、`module_count`、`error_count`。
无匹配模块时 `modules` 为空数组，无错误时 `errors` 为空数组；
错误逐条保留 `path` 和 `reason`，单个文件失败后继续处理其他文件。
普通输出使用独立表格展示错误，调用方可通过 JSON 的 `errors` 判断扫描是否完整。

## pcompare

比较两个及以上目录或文件，通过 Rich 表格默认仅展示不一致的条目。
扫描和比较期间显示加载动画，包含等待 SSH 及计算 MD5 的过程。

```bash
# 比较多个目录
pcompare ./backup_a ./backup_b ./backup_c

# 比较多个文件，文件名可以不同
pcompare ./config.yaml ./config.backup.yaml

# 比较远端与本地目录，远端 ~ 在远端展开
pcompare 'seekplum:~/Downloads' ~/Downloads

# 忽略目录和文件名称的大小写，仍比较文件内容
pcompare 'seekplum:~/Downloads' ~/Downloads --ignore-case

# 按名称排除所有层级的依赖目录，按相对路径排除指定目录
pcompare 'seekplum:~/Downloads' ~/Downloads \
  --exclude-name node_modules --exclude-name .venv \
  --exclude-path packages/web/dist

# 按通配符排除名称中包含 .log 的文件或目录
pcompare 'seekplum:~/packages' ~/packages --quick --exclude-name '*.log*'

# 使用 re: 前缀进行正则完整匹配
pcompare ./backup_a ./backup_b --exclude-name 're:.*\.log(?:\.\d+)?'

# 按路径通配符排除任意层级的 dist 目录
pcompare ./backup_a ./backup_b --exclude-path '**/dist'

# 展示全部条目
pcompare ./backup_a ./backup_b --show all

# 仅展示一致条目
pcompare ./backup_a ./backup_b --show identical

# 仅展示不一致条目（默认）
pcompare ./backup_a ./backup_b --show different

# 完整比较，仅展示到第二层目录、文件及链接
pcompare ./backup_a ./backup_b --show all --display-depth 2

# 快速比较，默认只扫描 2 层（与 tree -L 2 的层级一致）
pcompare ./backup_a ./backup_b --quick

# 指定扫描层级，也可与 --quick 一起使用
pcompare 'seekplum:~/Downloads' ~/Downloads -L 3

# 关闭内置忽略规则，仍保留手动传入的排除项
pcompare ./backup_a ./backup_b --no-default-excludes

# 比较多个远端文件，可混合本地路径
pcompare 'user@server-a:/data/config.yaml' 'server-b:/data/config.yaml' ./config.yaml

# 也可以直接以模块方式运行
uv run python -m plum_tools.cli.pcompare ./backup_a ./backup_b
```

目录按相对路径递归比较，包含隐藏文件和空目录。目录只有在全部子项一致时
才算一致，`.` 表示输入的根条目。表格中的列编号对应输入路径；同一行内
组号相同的条目一致，即使其他输入存在差异，也能识别其中相同的条目。

默认区分相对路径的大小写。`--ignore-case` 忽略每层目录名和文件名的大小写，
例如将 `README.md` 与 `readme.md` 匹配到同一行，仍比较条目类型、文件内容和链接目标。
表格采用按输入顺序最先出现的原始相对路径；排除规则仍按原始名称和路径匹配。
若同一个输入中存在大小写折叠后重名的条目，例如同时存在独立的 `README.md`
与 `readme.md`，命令报告冲突并以退出码 `2` 结束，避免覆盖或误合并。

`--show` 选择目录、文件和链接条目的展示类型：

| 参数值 | 展示内容 |
| --- | --- |
| `all` | 全部条目，按一致与不一致分表展示 |
| `identical` | 仅一致项 |
| `different` | 仅不一致项，默认值 |

汇总始终保留两类条目数量，展示类型不影响整体比较结果和退出码；
没有可展示条目时不显示空表格。

`--json` 默认输出全部已比较条目，支持 `--display-depth`，忽略 `--show` 和 `--compact`：

```bash
# 输出所有一致目录、文件和链接的相对路径
pcompare ./backup_a ./backup_b --json |
  jq -r '.entries[] | select(.identical) | .path'

# 仅输出根条目和第一层中的一致项
pcompare ./backup_a ./backup_b --display-depth 1 --json |
  jq -r '.entries[] | select(.identical) | .path'

# 仅输出一致目录
pcompare ./backup_a ./backup_b --json |
  jq -r '.entries[] | select(.identical and .entries[0].kind == "目录") | .path'

# 仅输出一致文件
pcompare ./backup_a ./backup_b --json |
  jq -r '.entries[] | select(.identical and .entries[0].kind == "文件") | .path'
```

stdout 只输出一个 JSON 对象，加载动画和错误写入 stderr。
顶层包含 `schema_version`（当前为 `1`）、`command`（`pcompare`）、
`paths`、`options`、`summary` 和 `entries`。
`paths` 按输入顺序保存本地绝对路径或原始远端路径；`options` 记录排除规则、
是否启用默认排除、实际比较深度 `max_depth`、`ignore_case` 和展示深度 `display_depth`。
`summary` 包含 `entry_count`、`identical_count`、`different_count` 和 `identical`。
每个条目提供相对路径 `path`、布尔值 `identical`、中文结果 `result`、
内容分组 `groups` 和按输入顺序排列的 `entries`。
各输入条目包含 `path`、`kind`（`目录`、`文件` 或 `链接`）、`size` 和 `target`，
缺失条目为 `null`；`groups` 中同一行的相同数字表示内容一致，`0` 表示缺失。
`.` 表示根条目，也计入汇总；仅需子项时可在 jq 中增加 `select(.path != ".")`。

JSON 仍遵循排除规则和扫描深度限制；`options.max_depth` 不为 `null` 时，
一致状态仅表示当前深度范围内一致。退出码仍为 `0`、`1`、`2`；
启用 shell 的 `pipefail` 时，有差异的比较即使成功输出 JSON，管道也会返回非零。

`--display-depth N` 限制表格和 JSON 条目的展示层级，默认不限；`N` 必须为非负整数，
根目录为第 0 层，`--display-depth 0` 仅展示根条目。
更深层条目仍参与比较，差异会反映在父目录上；汇总数量和退出码均依据
全部已比较条目，表格标题中的数量仅统计当前展示的条目。
该参数适用于三种展示类型，并可与 `--quick`、`--max-depth` 配合：
扫描深度控制读取和比较范围，展示深度仅控制输出行数。

默认按名称忽略 `.DS_Store`、`.idea`、`.node_modules`、`node_modules`、`.venv`、
`__pycache__`、`.mypy_cache`、`.pytest_cache`，
可通过 `--no-default-excludes` 关闭。手动排除参数与内置规则合并，
可重复传入，支持精确匹配、通配符和 `re:` 前缀的正则表达式：

- `--exclude-name` 按目录名或文件名匹配任意层级，例如 `node_modules`、
  `.venv`、`*.log*`。
- `--exclude-path` 按相对于各输入根目录的路径匹配，例如
  `packages/web/dist`，不会排除其他位置同名的 `dist`。

普通字符串仍精确匹配；通配符支持 `*`、`?`、`[abc]`，区分大小写。
路径通配符中 `*` 不跨越 `/`，独立路径段 `**` 匹配零层或多层目录，
例如 `packages/*/dist` 匹配一层项目目录，`**/dist` 匹配任意层级的 `dist`。
以 `re:` 开头时，正则对整个名称或相对路径进行匹配；需要部分匹配时显式添加 `.*`。
正则路径使用 `/` 分隔，表达式不会进行路径规范化；无效正则在扫描或连接 SSH 前报错。
包含通配符或正则的参数应加引号，避免被 shell 提前展开。

两类规则对全部本地和远端输入生效，匹配目录时跳过整个子树，
排除项不会被读取、计算摘要，也不参与比较和统计。
规则仅作用于输入目录内的子项，不排除直接传入的根目录或文件；
普通及通配符路径不能是绝对路径、`.` 或包含 `..`。

`--quick` 默认只扫描 2 层；`--max-depth N`（简写 `-L N`）可单独使用，
也可覆盖 `--quick` 的默认层级，`N` 必须为正整数。根目录是第 0 层，
根目录内的直接子项是第 1 层。扫描到边界目录时保留目录条目，停止读取其子项，
本地与远端均在扫描阶段限制深度。范围内的普通文件仍按大小及完整 MD5 比较。
有限深度模式的报告标记为“当前深度内一致 / 不一致”，退出码也仅反映该范围，
不保证未扫描的深层内容一致；不传这两个参数时仍完整递归。

普通文件先比较大小，同大小的文件分块计算完整 MD5，不比较修改时间或权限。
远端支持 `[user@]host:path`（IPv6 地址使用方括号），连接使用系统 `ssh`，
沿用 `~/.ssh/config` 中的主机别名、端口、密钥和跳板机配置。
本机需要 `ssh`，远端需要 PATH 中可执行的 Python 3.9+，无需安装本工具。
远端会计算扫描范围内普通文件的完整 MD5，仅传回文件清单和摘要，不下载文件内容。
远端路径中的空格或 `~` 建议用引号包裹；名称包含冒号的本地路径用 `./` 或绝对路径表示。
符号链接仅比较链接目标，不跟随链接。目录与文件不能混合输入；路径不存在、
无法读取或遇到不支持的特殊文件时会报错。

退出码：`0` 表示整体一致，`1` 表示存在差异，`2` 表示输入或读取错误。

## pssh

通过 IP、IP 简写或 SSH 主机别名快速登录服务器：

```bash
pssh 192.168.1.10
pssh dev -u root -p 2222
pssh 10 -t default
pssh --help
```

主机类型默认 `default`，可选值由 `~/.plum_tools.yaml` 中的
`host_type_<类型>` 配置决定。SSH 参数优先使用命令行值，其次读取
`~/.ssh/config` 中的主机别名配置，最后使用 `default_ssh_conf`。

## gitstash

切换分支前保存当前分支的本地修改，切换后恢复目标分支上次保存的修改。
在 Git 仓库内指定目标分支执行：

```bash
gitstash master
gitstash release-1.0.0
gitstash --help
```

## pipmi

通过 SSH 登录跳板机，对指定服务器执行 IPMI 命令：

```bash
pipmi -l 192.168.1.10 -s 20 21 -c 'power status'
pipmi -l 10 -s 20 -t default -U ADMIN -c 'chassis status'
pipmi --help
```

`-l` 指定跳板机，`-s` 支持多个服务器 IP 或 IP 简写；IPMI 地址按配置的
`ipmi_interval` 偏移计算。SSH 用户名默认 `root`，端口和私钥默认读取配置。
IPMI 用户名默认 `ADMIN`，密码默认 `12345678`，命令默认 `power on`；
可用 `-c` 指定其他 ipmitool 子命令。

## prn

通过 rsync 上传、下载或在本机同步项目文件：

```bash
# 查看上传命令
prn -s dev -p default --dry-run

# 指定路径并查看同步命令
prn -s dev -l ./src -r /srv/app --dry-run

# 下载配置项目的文件
prn -s dev -p default --download
prn --help
```

项目名默认 `default`，可选值由 `projects` 配置决定；未指定服务器时在本机同步。
本地路径、远端路径和排除规则默认读取项目配置。`--delete 0` 保留目标端多余文件，
`--delete 1` 删除；未传入时读取项目配置，未配置时为 `0`。

## pping

并发探测指定网段内 1 至 254 号地址，输出可达 IP：

```bash
pping -p 192.168.1
pping -t default
pping -p 192.168.1 --json | jq -r '.reachable[]'
pping --help
```

`-p` 指定网段前三段；未传入时读取主机类型对应的网段配置。
主机类型默认 `default`，可选值由 `host_type_<类型>` 配置决定。

`--json` 忽略 `--compact`，stdout 只输出一个 JSON 对象，进度条写入 stderr。
顶层包含 `schema_version`（当前为 `1`）、`command`（`pping`）、
`options`、`summary` 和 `reachable`。
`options` 记录 `host_type` 及补全末尾句点后的实际网段 `prefix_host`；
`summary` 包含 `target_count`、`reachable_count` 和 `unreachable_count`。
`reachable` 按 IP 数值顺序保存可达地址，没有可达地址时为空数组。

## 详细文档

见[项目文档目录](docs/README.md)
