# linux 小工具

[![LICENSE](https://img.shields.io/github/license/seekplum/plum_tools.svg)](https://github.com/seekplum/plum_tools/blob/master/LICENSE)[![travis-ci](https://travis-ci.org/seekplum/plum_tools.svg?branch=master)](https://travis-ci.org/seekplum/plum_tools)[![coveralls](https://coveralls.io/repos/github/seekplum/plum_tools/badge.svg?branch=master)](https://coveralls.io/github/seekplum/plum_tools?branch=master) [![pypi version](https://img.shields.io/pypi/v/plum_tools.svg)](https://pypi.python.org/pypi/plum_tools) [![pyversions](https://img.shields.io/pypi/pyversions/plum_tools.svg)](https://pypi.python.org/pypi/plum_tools)

## 项目的git hooks

由于钩子文件无法提交到 `.git` 中，所以在第一次clone项目中需要执行以下命令，把钩子放到指定位置

```bash
cp -r hooks/* .git/hooks/
```

## gitrepo

查找指定路径下所有被改动的git仓库

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

通过ip简写或别名快速登录机器

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

外部传入一个branch，保存本地未提交的修改，然后切换到branch，将上次该branch保存的未提交的结果stash pop出来

```bash
➜  ~ gitstash -h
usage: gitstash [-h] branch

positional arguments:
  branch      specify branch

optional arguments:
  -h, --help  show this help message and exit
```

## pipmi

对指定机器进行远程执行ipmitool相关操作

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

ping指定网段所有ip是否能ping通

```bash
➜  ~ pping -h
usage: pping [-h] [-t--type TYPE]

optional arguments:
  -h, --help     show this help message and exit
  -t--type TYPE  host type
```
