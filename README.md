# linux 小工具

[![LICENSE](https://img.shields.io/github/license/seekplum/plum_tools.svg)](https://github.com/seekplum/plum_tools/blob/master/LICENSE)
[![codecov](https://codecov.io/gh/seekplum/plum_tools/branch/master/graph/badge.svg)](https://codecov.io/gh/seekplum/plum_tools)
[![CI](https://github.com/copier-org/copier/workflows/CI/badge.svg)](https://github.com/copier-org/copier/actions?query=branch%3Amaster)
[![pypi version](https://img.shields.io/pypi/v/plum_tools?logo=pypi&logoColor=%23959DA5)](https://pypi.python.org/pypi/plum_tools)
[![pyversions](https://img.shields.io/pypi/pyversions/plum_tools?logo=python&logoColor=%23959DA5)](https://pypi.python.org/pypi/plum_tools)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


## 目录结构

```text
➜  tree -L 1 -a
.
├── .bumpversion.cfg    # `bumpversion`工具的配置文件，用于自动更新版本
├── .gitignore          # 维护git仓库需要忽略文件
├── .gitlab-ci.yml      # gitlab ci的配置文件
├── .pylintrc           # pylint 配置文件
├── CHANGELOG.md        # 记录模块的变化
├── README.md           # 项目自述文件
├── bin                 # 项目二进制程序
├── docs                # 项目文档
├── plum_tools          # 核心代码模块
└── tests               # 单元测试目录

```

## 安装环境依赖

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

```bash
# 小版本
bumpversion patch

# 中版本
bumpversion minor
```

## gitrepo

使用默认的 `check` 子命令查找有未提交修改、分支差异或 stash 的 Git 仓库，
省略子命令时兼容原有用法：

```bash
gitrepo -p ~/PythonProjects -d -s
gitrepo check -p ~/PythonProjects -d -s
```

使用 `scan` 子命令扫描并通过 Rich 表格聚合展示仓库，默认扫描家目录，
按远程主机分表，例如 `github.com`、`gitlab.com` 各一张表。
表内默认按完整远程地址合并同一仓库的多个目录：

```bash
# 扫描多个目录，按远程主机分表、远程地址合并仓库
gitrepo scan -p ~/PythonProjects ~/work

# 按远程主机分表、仓库目录名合并仓库
gitrepo scan -p ~/PythonProjects --group-by name

# 仅展示包含重复克隆的分组
gitrepo scan -p ~/PythonProjects --duplicates

# 更新远程引用后检查
gitrepo scan -p ~/PythonProjects --fetch

# 按目录名跳过不需要遍历的子目录，check 同样支持
gitrepo scan -p ~/PythonProjects --exclude node_modules .venv
```

远程地址优先选择名为 `upstream` 的 remote，其次选择 `origin`，
Git 不记录 remote 的添加时间，其余 remote 按名称排序选择第一个。
分支的 upstream 指各分支配置的跟踪目标，
独立于用于分组的 remote。

远程分组将同一主机及仓库路径的 SSH、HTTPS 地址和 `.git` 后缀规范化，
保留仓库路径大小写及非默认端口。本地路径与 `file://` 地址按实际路径聚合，
SSH 主机别名不会自动解析为相同主机。
同一远程地址对应多个独立仓库时标记为重复克隆；worktree 逐个展示，
共用 Git 数据的目录不计为独立克隆。
两种模式使用相同布局：同一仓库的名称仅在首行显示，后续行留空，
仓库组之间加分隔线，形成纵向合并效果；每个目录保留自己的分支、remote 名称和状态。
`--group-by name` 按同一主机下的目录名合并，并逐行保留远程地址，
同名但远程不同的仓库会单独标记。非默认端口仍用于区分远程仓库，
相同主机不同端口的仓库放在同一张表。
本地远程路径和无远程 / 无法识别的仓库分别集中到独立表格。
`--duplicates` 先筛选包含重复克隆的仓库组，再按主机汇总展示，
重复克隆仍依据完整远程地址判断。

扫描支持普通仓库、嵌套仓库、worktree、子模块和裸仓库；
重叠扫描路径会去重，扫描时跳过 `.git` 内部目录，不递归跟随目录符号链接。
两个子命令都显示目录发现和仓库检查进度、耗时及检查失败数量，
输出重定向时关闭动态进度条。默认不排除其他目录，
可通过 `--exclude` 按名称跳过子目录，显式指定的扫描根目录仍会检查。
`scan` 在发现仓库后立即提交有界并发检查，合并工作区、当前分支和 stash 查询，
同一仓库的 worktree 共用分支读取及 fetch；`check` 按仓库数量和 CPU 数限制进程数。
表格同时展示暂存、未暂存、未跟踪、冲突及 stash 数量，
并检查所有本地分支的领先、落后、无 upstream、upstream 失效及游离 HEAD 状态。
无远程、空仓库、读取失败及远程更新失败也会显示。

默认检查依据本地缓存的远程引用。`--fetch` 会更新所有已配置远程的引用，
并可能触发 Git 的身份认证；更新失败时会标记错误并依据现有引用检查。
upstream 失效表示对应的本地跟踪引用不存在，
远程分支的删除是否反映到本地取决于 Git 的 fetch 清理配置。

## pcompare

比较两个及以上目录或文件，通过 Rich 表格分别展示一致、不一致的条目。

```bash
# 比较多个目录
pcompare ./backup_a ./backup_b ./backup_c

# 比较多个文件，文件名可以不同
pcompare ./config.yaml ./config.backup.yaml

# 也可以直接以模块方式运行
uv run python -m plum_tools.compare ./backup_a ./backup_b
```

目录按相对路径递归比较，包含隐藏文件和空目录。目录只有在全部子项一致时
才算一致，`.` 表示输入的根条目。表格中的列编号对应输入路径；同一行内
组号相同的条目一致，即使其他输入存在差异，也能识别其中相同的条目。

普通文件先比较大小，同大小的文件分块计算完整 MD5，不比较修改时间或权限。
符号链接仅比较链接目标，不跟随链接。目录与文件不能混合输入；路径不存在、
无法读取或遇到不支持的特殊文件时会报错。

退出码：`0` 表示整体一致，`1` 表示存在差异，`2` 表示输入或读取错误。

## pssh

通过 ip 简写或别名快速登录机器

```bash
➜  ~ pssh -h
usage: pssh [-h] [-t--type TYPE] [-i--identityfile IDENTITYFILE]
            [-u--username USER] [-p--port PORT]
            host

positional arguments:
  host                  specify server

optional arguments:
  -h, --help            show this help message and exit
  -t--type TYPE         host type
  -i--identityfile IDENTITYFILE
                        ssh login identityfile path
  -u--username USER     ssh login username
  -p--port PORT         ssh login port
```

## gitstash

外部传入一个 branch，保存本地未提交的修改，然后切换到 branch，将上次该 branch 保存的未提交的结果 stash pop 出来

```bash
➜  ~ gitstash -h
usage: gitstash [-h] branch

positional arguments:
  branch      specify branch

optional arguments:
  -h, --help  show this help message and exit
```

## pipmi

对指定机器进行远程执行 ipmitool 相关操作

```bash
➜  ~ pipmi -h
usage: pipmi [-h] -l HOST -s SERVERS [SERVERS ...] [-u USER] [-pass PASSWORD]
             [-p--port PORT] [-i--identityfile IDENTITYFILE] [-t--type TYPE]
             [-U USERNAME] [-c COMMAND] [-P PASSWORD]

optional arguments:
  -h, --help            show this help message and exit
  -l HOST, --login HOST
                        specify login ip
  -s SERVERS [SERVERS ...], --servers SERVERS [SERVERS ...]
                        specify server
  -u USER, --username USER
                        specify username
  -pass PASSWORD, --password PASSWORD
                        specify password
  -p--port PORT         ssh login port
  -i--identityfile IDENTITYFILE
                        ssh login identityfile path
  -t--type TYPE         host type
  -U USERNAME, --Username USERNAME
                        specify ipmi username
  -c COMMAND, --command COMMAND
                        specify ipmi command
  -P PASSWORD, --Password PASSWORD
                        specify ipmi password
```

## prn

上传文件到服务器

```bash
➜  ~ prn -h
usage: prn [-h] -s SERVERS [SERVERS ...] [-p PROJECT] [-t--type TYPE]
           [-i--identityfile IDENTITYFILE] [-u--username USER] [-p--port PORT]
           [-l--local LOCAL] [-r--remote REMOTE] [-d--delete DELETE]
           [-e--exclude EXCLUDE [EXCLUDE ...]]

optional arguments:
  -h, --help            show this help message and exit
  -s SERVERS [SERVERS ...], --servers SERVERS [SERVERS ...]
                        specify server
  -p PROJECT, --project PROJECT
                        specify project
  -t--type TYPE         host type
  -i--identityfile IDENTITYFILE
                        ssh login identityfile path
  -u--username USER     ssh login username
  -p--port PORT         ssh login port
  -l--local LOCAL       local path
  -r--remote REMOTE     remote path
  -d--delete DELETE     delete remote path other file
  -e--exclude EXCLUDE [EXCLUDE ...]
                        exclude file
```

## pping

ping 指定网段所有 ip 是否能 ping 通

```bash
➜  ~ pping -h
usage: pping [-h] [-t--type TYPE]

optional arguments:
  -h, --help     show this help message and exit
  -t--type TYPE  host type
```

## 详细文档

见[项目文档目录](docs/README.md)
