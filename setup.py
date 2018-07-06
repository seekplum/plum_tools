#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

from setuptools import setup, find_packages

root = os.path.dirname(os.path.abspath(__file__))

# 查询版本信息
with open(os.path.join(root, "VERSION")) as f:
    version = f.read().strip()

requirements = []

setup(
    author="seekplum",
    author_email='1131909224m@sina.cn',
    classifiers=[
        'Programming Language :: Python :: 2.7',
    ],
    description="linux下常用的工具包",
    install_requires=requirements,
    include_package_data=True,
    name='plum_tools',
    namespace_packages=['plum_tools'],
    packages=find_packages(exclude=['tests', 'docs']),
    version=version,
    entry_points={
        'console_scripts': [
            "gitrepo = plum_tools.gitrepo:main"
        ],
    }
)
