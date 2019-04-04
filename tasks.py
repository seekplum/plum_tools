# -*- coding: utf-8 -*-

import os

from invoke import task

root = os.path.dirname(os.path.abspath(__file__))
name = 'plum_tools'


@task
def clean(ctx):
    """清除代码中无效文件
    """
    ctx.run('rm -rf build dist', echo=True)
    ctx.run("find . -name '*.pyc' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '*.pyo' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '__pycache__' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name 'htmlcov' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.coverage*' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.pytest_cache' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.benchmarks' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '*.egg-info' -exec rm -rf {} +", echo=True)


@task(clean)
def sdist(ctx):
    ctx.run('python setup.py sdist', echo=True)


@task(sdist)
def upload(ctx, r="private"):
    """上传包到指定pip源
    """
    ctx.run('python setup.py sdist upload -r %s' % r, echo=True)


@task(sdist)
def register(ctx, n, r="private"):
    ctx.run('twine register %s -r %s' % (n, r), echo=True, warn=True)


@task(register)
def tupload(ctx, n, r="private"):
    """上传包到指定pip源
    """
    ctx.run('twine upload %s -r %s' % (n, r), echo=True)


@task(clean)
def check(ctx, j=4):
    """检查代码规范
    """
    ctx.run("pylint -j %s --output-format colorized   --disable=all --enable=E,F plum_tools" % j)


@task(clean)
def unittest(ctx):
    """运行单元测试和计算测试覆盖率
    """
    ctx.run("export PYTHONPATH=`pwd` && pytest --cov=plum_tools tests", echo=True)


@task
def lock(ctx):
    ctx.run("if [ $(ls -l Pipfile.lock | wc -l) -gt 0 ];then "
            "pipenv lock -v --keep-outdated ; else pipenv lock ; fi", echo=True)
