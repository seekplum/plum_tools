# -*- coding: utf-8 -*-

import os

from invoke import task

root = os.path.dirname(os.path.abspath(__file__))
name = 'plum_tools'


@task
def clean(ctx):
    ctx.run('rm -rf build dist', echo=True)
    ctx.run("find . -name '*.pyc' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '*.pyo' -exec rm -f {} +", echo=True)
    ctx.run("find . -name '__pycache__' -exec rm -rf {} +", echo=True)


@task(clean)
def sdist(ctx):
    ctx.run('python setup.py sdist', echo=True)


@task(clean)
def upload(ctx, r="private"):
    ctx.run('python setup.py sdist upload -r %s' % r, echo=True)


@task(clean)
def register(ctx, n, r="private"):
    ctx.run('twine register %s -r %s' % (n, r), echo=True, warn=True)


@task(clean)
def tupload(ctx, n, r="private"):
    ctx.run('twine upload %s -r %s' % (n, r), echo=True)


@task(clean)
def check(ctx, j=4):
    ctx.run("pylint -j %s --output-format colorized   --disable=all --enable=E,F plum_tools" % j)
