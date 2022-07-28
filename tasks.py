# -*- coding: utf-8 -*-

import os
import subprocess
from datetime import datetime

import six
from invoke import task

root = os.path.dirname(os.path.abspath(__file__))
package_name = "plum_tools"


def covert_source(source):
    source = source.replace("/", ".")
    if source.endswith(".py"):
        source = source[:-3]
    return source


@task
def clean(ctx):
    """清除项目中无效文件"""
    ctx.run("rm -rf build dist", echo=True)
    ctx.run("find . -name '*.pyc' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '*.pyo' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '*.log' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '__pycache__' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name 'htmlcov' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.coverage*' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.pytest_cache' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.benchmarks' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '*.egg-info' -exec rm -rf {} +", echo=True)
    ctx.run("find . -name '.DS_Store' -exec rm -rf {} +", echo=True)


@task
def checkone(ctx, source):
    """检查代码规范

    inv checkone tasks.py
    """
    ctx.run(
        "isort --check-only --diff {source}".format(source=source),
        echo=True,
    )
    ctx.run("black --check {source}".format(source=source), echo=True)
    ctx.run("flake8 {source}".format(source=source), echo=True)
    if six.PY3:
        ctx.run("mypy {source}".format(source=source), echo=True)


@task(clean)
def sdist(ctx):
    ctx.run("python setup.py sdist", echo=True)


@task(clean)
def upload(ctx, name="private"):
    """上传包到指定pip源"""
    ctx.run("python setup.py sdist upload -r %s" % name, echo=True)


@task(sdist)
def tupload(ctx, name="private"):
    """上传包到指定pip源"""
    ctx.run("twine upload dist/* -r %s" % name, echo=True)


@task(clean)
def check(ctx, job=4):
    """检查代码规范"""
    ctx.run("isort --check-only --diff %s" % package_name, echo=True)
    if six.PY3:
        ctx.run("black --check %s" % package_name, echo=True)
    ctx.run("flake8 %s" % package_name, echo=True)
    if six.PY3:
        ctx.run("mypy %s" % package_name, echo=True)


@task(clean)
def unittest(ctx):
    """运行单元测试和计算测试覆盖率

    pytest --cov-config=.coveragerc --cov=plum_tools --cov-fail-under=100 tests
    """
    ctx.run(
        "export PYTHONPATH=`pwd` && pytest tests", encoding="utf-8", pty=True, echo=True
    )


@task(clean)
def coverage(ctx):
    """运行单元测试和计算测试覆盖率"""
    ctx.run(
        "export PYTHONPATH=`pwd` && "
        "coverage run --rcfile=.coveragerc --source=%s -m pytest tests && "
        "coverage report -m --fail-under=57" % package_name,
        encoding="utf-8",
        pty=True,
        echo=True,
    )


@task(clean)
def unittestone(ctx, source, test):
    """运行单元测试和计算测试覆盖率

    inv unittestone --source plum_tools.fib --test tests/test_fib.py
    """
    ctx.run(
        "export PYTHONPATH=`pwd` && "
        "pytest -vv -rsxS -q --cov-config=.coveragerc --cov-report term-missing "
        "--cov --cov-fail-under=100 {source} {test}".format(
            source=covert_source(source), test=test
        ),
        encoding="utf-8",
        pty=True,
        echo=True,
    )


@task(clean)
def coverageone(ctx, source, test):
    """运行单元测试和计算测试覆盖率

    inv coverageone --source plum_tools.fib --test tests/test_fib.py
    """
    ctx.run(
        "export PYTHONPATH=`pwd` && "
        "coverage run --rcfile=.coveragerc --source={source} -m pytest -vv -rsxS -q {test} && "
        "coverage report -m".format(source=covert_source(source), test=test),
        encoding="utf-8",
        pty=True,
        echo=True,
    )


@task(clean)
def format(ctx):
    """格式化代码"""
    autoflake_args = [
        "--remove-all-unused-imports",
        "--recursive",
        "--remove-unused-variables",
        "--in-place",
        "--exclude=__init__.py",
    ]
    ctx.run(
        "autoflake {args} {package_name} tests".format(args=" ".join(autoflake_args)),
        package_name=package_name,
        echo=True,
    )
    ctx.run("isort %s tests" % package_name, echo=True)
    if six.PY3:
        ctx.run("black %s tests" % package_name, echo=True)


@task(clean)
def formatone(ctx, source):
    """格式化单个文件"""
    autoflake_args = [
        "--ignore-init-module-imports",
        "--remove-all-unused-imports",
        "--recursive",
        "--remove-unused-variables",
        "--in-place",
        "--exclude=__init__.py",
    ]
    ctx.run(
        "autoflake {args} {source}".format(
            source=source, args=" ".join(autoflake_args)
        ),
        echo=True,
    )
    ctx.run("isort {source}".format(source=source), echo=True)
    if six.PY3:
        ctx.run("black {source}".format(source=source), echo=True)


def get_site_packages_dir(packages: str) -> str:
    if packages is None:
        return ""
    if not os.getenv("VIRTUAL_ENV"):
        return ""
    site_packages_dir = subprocess.check_output(
        "find ${VIRTUAL_ENV} -name 'site-packages'", shell=True, text=True
    ).strip()
    if not packages.strip():
        return site_packages_dir
    packages_list = [
        package_name.strip()
        for package_name in packages.split(",")
        if package_name.strip()
    ]
    packages_unique = sorted(
        list(set(packages_list)), key=lambda x: packages_list.index(x)
    )
    if packages_unique:
        return " ".join(
            [
                os.path.join(site_packages_dir, package_name)
                for package_name in packages_unique
            ]
        )
    return site_packages_dir


def get_plint_args(msg_ids: str, ignore_default: bool) -> list:
    pylint_args = [
        "--jobs=0",
        "--exit-zero",
        "--persistent=n",
    ]
    if not ignore_default:
        pylint_args.append(
            "--ignore=.git,venv*,docs,node_modules,tests,test*.py,debug_celery.py"
        )
    if msg_ids:
        pylint_args.extend(["--disable=all", f"--enable={msg_ids}"])
    return pylint_args


@task
def pylintone(ctx, source, msg_ids="", packages=None, ignore_default=False):
    """检查单个文件

    inv --help pylintone

    inv pylintone --source 'plum_tools *.py' --msg-ids="W1505" --packages="pymongo,celery"
    """
    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f'pylint_{msg_ids.replace(",", "_")}_{time_str}.log'
    site_packages_dir = get_site_packages_dir(packages)
    pylint_args = " ".join(get_plint_args(msg_ids, ignore_default))
    cmd = f"pylint {pylint_args} {source} {site_packages_dir} > {file_name}"
    ctx.run(cmd, echo=True)


@task
def lock(ctx):
    """生成版本文件

    1.安装Pipenv

    pip install pipenv

    2.安装项目依赖包

    pipenv install --deploy --dev --skip-lock
    """
    ctx.run(
        'if [ -f "Pipfile.lock" ]; then pipenv lock -v --keep-outdated ; else pipenv lock --pre --clear ; fi',
        echo=False,
    )
