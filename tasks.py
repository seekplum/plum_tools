# -*- coding: utf-8 -*-

from invoke import task


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


@task(clean)
def upload(ctx, name="private"):
    """上传包到指定pip源
    """
    ctx.run('python setup.py sdist upload -r %s' % name, echo=True)


@task(sdist)
def tupload(ctx, name="private"):
    """上传包到指定pip源
    """
    ctx.run('twine upload dist/* -r %s' % name, echo=True)


@task(clean)
def check(ctx, job=4):
    """检查代码规范
    """
    ctx.run("pylint --rcfile=.pylintrc -j %s --output-format parseable plum_tools" % job,
            echo=True)
    ctx.run("pylint --rcfile=.pylintrc -j %s --output-format parseable tests --ignore=test.py "
            "--disable=C0111,W0201,R0201" % job,
            echo=True)


@task(clean)
def unittest(ctx):
    """运行单元测试和计算测试覆盖率
    """
    ctx.run("export PYTHONPATH=`pwd` && pytest --cov=plum_tools tests", encoding="utf-8", pty=True, echo=True)


@task(clean)
def coverage(ctx):
    """运行单元测试和计算测试覆盖率
    """
    ctx.run("export PYTHONPATH=`pwd` && coverage run --source=plum_tools -m pytest tests && coverage report -m",
            encoding="utf-8", pty=True, echo=True)


@task
def lock(ctx):
    ctx.run('if [ -f "Pipfile.lock" ]; then pipenv lock -v --keep-outdated ; else pipenv lock ; fi', echo=False)
