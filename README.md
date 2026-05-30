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

查找指定路径下所有被改动的 git 仓库

```bash
➜  ~ gitrepo -h
usage: gitrepo [-h] [-p--path PATH [PATH ...]] [-d--detail] [-t--test]

optional arguments:
  -h, --help            show this help message and exit
  -p--path PATH [PATH ...]
                        The directory path to check
  -d--detail            display error details
  -t--test              run the test function
```

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
