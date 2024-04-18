import os
import subprocess
from datetime import datetime
from multiprocessing import cpu_count
from typing import Any, Optional

from invoke import task
from invoke.context import Context

PACKAGE_NAME = "plum_tools"


def covert_source(source: str) -> str:
    source = source.replace("/", ".").replace(" ", ",")
    if source.endswith(".py"):
        source = source[:-3]
    return source


def get_source(source: Optional[str] = None, *, ignote_tests: bool = False, ignote_tasks: bool = False) -> str:
    if not source:
        source = PACKAGE_NAME
        if not ignote_tasks:
            source += " tasks.py"
        if not ignote_tests:
            source += " tests"
    return source


def get_tests(tests: Optional[str] = None) -> str:
    if not tests:
        tests = "tests"
    return tests


def ctx_run(ctx: Context, cmd: str, **kwargs: Any) -> None:
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("echo", True)
    kwargs.setdefault("pty", True)
    ctx.run(cmd, **kwargs)


@task
def clean_pyc(ctx: Context) -> None:
    """清理 Python 运行文件"""
    ctx_run(ctx, "rm -rf build dist")
    ctx_run(ctx, "find . -name '*.pyc' -exec rm -f {} +")
    ctx_run(ctx, "find . -name '*.pyo' -exec rm -f {} +")
    ctx_run(ctx, "find . -name '*~' -exec rm -f {} +")
    ctx_run(ctx, "find . -name '*.log' -exec rm -f {} +")
    ctx_run(ctx, "find . -name '*.log.*' -exec rm -f {} +")
    ctx_run(ctx, "find . -name '__pycache__' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name '.mypy_cache' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name '.ruff_cache' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name '*.egg-info' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name '.DS_Store' -exec rm -rf {} +")


@task
def clean_test(ctx: Context) -> None:
    """清理测试文件"""
    ctx_run(ctx, "find . -name '.pytest_cache' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name '.coverage' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name 'pytest_coverage*.xml' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name 'pytest_result*.xml' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name 'htmlcov' -exec rm -rf {} +")
    ctx_run(ctx, "find . -name '.benchmarks' -exec rm -rf {} +")


@task(clean_pyc, clean_test)
def clean(_: Context) -> None:
    """清理所有不该进代码库的文件"""


@task(clean)
def sdist(ctx: Context) -> None:
    """构建pypi包"""
    ctx_run(ctx, "python setup.py sdist")


@task(clean)
def upload(ctx: Context, name: str = "private") -> None:
    """上传包到指定pip源

    inv upload --name private
    """
    ctx_run(ctx, f"python setup.py sdist upload -r {name}")


@task(sdist)
def tupload(ctx: Context, name: str = "private") -> None:
    """上传包到指定pip源

    inv tupload --name private
    """
    ctx_run(ctx, f"twine upload dist/* -r {name}")


@task(clean)
def format(ctx: Context, source: Optional[str] = None) -> None:  # pylint: disable=redefined-builtin
    """格式化代码

    inv format --source tasks.py
    """
    source = get_source(source)
    autoflake_args = [
        "--remove-all-unused-imports",
        "--recursive",
        "--remove-unused-variables",
        "--in-place",
        "--exclude=__init__.py",
    ]
    args = " ".join(autoflake_args)
    ctx_run(ctx, f"autoflake {args} {source} tests")
    ctx_run(ctx, f"isort {source} tests")
    ctx_run(ctx, f"black {source} tests")


@task(clean)
def lint(ctx: Context, source: Optional[str] = None) -> None:
    """检查代码规范

    inv lint --source tasks.py
    """
    source = get_source(source)
    ctx_run(ctx, f"mypy {source}")
    ctx_run(ctx, f"black --check {source}")
    ctx_run(ctx, f"isort --check-only --diff {source}")
    ctx_run(ctx, f"flake8 {source}")
    ctx_run(ctx, f"pylint {source} --job {cpu_count()}")
    ctx_run(ctx, f"bandit -c pyproject.toml -r {source}")


@task(clean)
def test(ctx: Context, source: Optional[str] = None, tests: Optional[str] = None) -> None:
    """运行单元测试和计算测试覆盖率

    inv test --source plum_tools/conf.py --tests tests/test_conf.py

    pytest --cov-config=.coveragerc --cov=plum_tools --cov-fail-under=100 tests
    """
    source = get_source(source, ignote_tests=True, ignote_tasks=True)
    tests = get_tests(tests)
    ctx_run(
        ctx,
        "export PYTHONPATH=`pwd` && "
        "pytest -vv -rsxS -q --cov-config=.coveragerc --cov-report term-missing "
        f"--cov --cov-fail-under=57 {source} {tests}",
    )


@task(clean)
def coverage(ctx: Context, source: Optional[str] = None, tests: Optional[str] = None) -> None:
    """运行单元测试和计算测试覆盖率

    inv coverage --source plum_tools/conf.py --tests tests/test_conf.py
    """
    source = get_source(source, ignote_tests=True)
    tests = get_tests(tests)
    ctx_run(
        ctx,
        "export PYTHONPATH=`pwd` && "
        f"coverage run --rcfile=.coveragerc --source={covert_source(source)} -m pytest -vv -rsxS -q {tests} && "
        "coverage report -m --fail-under=57",
    )


def get_site_packages_dir(packages: Optional[str]) -> str:
    if packages is None:
        return ""
    if not os.getenv("VIRTUAL_ENV"):
        return ""
    site_packages_dir = subprocess.check_output(
        "find ${VIRTUAL_ENV} -name 'site-packages'", shell=True, text=True
    ).strip()
    if not packages.strip():
        return site_packages_dir
    packages_list = [package_name.strip() for package_name in packages.split(",") if package_name.strip()]
    packages_unique = sorted(list(set(packages_list)), key=lambda x: packages_list.index(x))
    if packages_unique:
        return " ".join([os.path.join(site_packages_dir, package_name) for package_name in packages_unique])
    return site_packages_dir


def get_plint_args(msg_ids: str, ignore_default: bool) -> list:
    pylint_args = [
        "--jobs=0",
        "--exit-zero",
        "--persistent=n",
    ]
    if not ignore_default:
        pylint_args.append("--ignore=.git,venv*,docs,node_modules,tests,test*.py,debug_celery.py")
    if msg_ids:
        pylint_args.extend(["--disable=all", f"--enable={msg_ids}"])
    return pylint_args


@task
def pylint(
    ctx: Context, source: str, msg_ids: str = "", packages: Optional[str] = None, ignore_default: bool = False
) -> None:
    """检查单个文件

    inv --help pylint

    inv pylint --source 'plum_tools *.py' --msg-ids="W1505" --packages="paramiko,pyyaml"
    """
    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f'pylint_{msg_ids.replace(",", "_")}_{time_str}.log'
    site_packages_dir = get_site_packages_dir(packages)
    pylint_args = " ".join(get_plint_args(msg_ids, ignore_default))
    cmd = f"pylint {pylint_args} {source} {site_packages_dir} > {file_name}"
    ctx_run(ctx, cmd)


@task
def install(ctx: Context, dev: bool = False, skip_lock: bool = False) -> None:
    """安装依赖

    1.安装Pipenv

    pip install pipenv
    """
    dev_flag = "--dev" if dev else ""
    skip_lock_flag = "--skip-lock" if skip_lock else ""
    ctx_run(
        ctx,
        (
            "PIPENV_VENV_IN_PROJECT=0 PIPENV_IGNORE_VIRTUALENVS=0 PIPENV_VERBOSITY=-1 "
            f"pipenv install --system --deploy {dev_flag} {skip_lock_flag}"
        ),
    )


@task
def requirements(ctx: Context) -> None:
    """导出依赖文件"""
    ctx_run(ctx, "pipenv requirements > requirements.txt")
    ctx_run(ctx, "pipenv requirements --dev-only > requirements-dev.txt")


@task
def lock(ctx: Context) -> None:
    """生成版本文件"""
    ctx_run(
        ctx, 'if [ -f "Pipfile.lock" ]; then pipenv lock --dev --verbose; else pipenv lock --pre --clear  --verbose; fi'
    )
