#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import shutil

from setuptools import setup, find_packages

from plum_tools import conf

version = '0.1.4.dev0'


def install():
    setup(
        author="seekplum",
        author_email='1131909224m@sina.cn',
        classifiers=[
            'Programming Language :: Python :: 2.7',
        ],
        description="linux下常用的工具包",
        install_requires=[
            "functools32",
            "pyyaml",
            "schema"
        ],
        # scripts=[
        #     "bin/gitrepo"
        # ],
        setup_requires=[],
        include_package_data=True,
        name='plum_tools',
        namespace_packages=['plum_tools'],
        packages=find_packages(exclude=['tests', 'docs']),
        version=version,
        entry_points={
            'console_scripts': [
                "gitrepo = plum_tools.gitrepo:main",
                "gitstash = plum_tools.gitstash:main",
                "pssh = plum_tools.pssh:main",
                "pping = plum_tools.pping:main",
                "pipmi = plum_tools.pipmi:main",
                "prn = plum_tools.prn:main",
            ],
        }
    )


def init():
    if not os.path.exists(conf.plum_yml_path):
        shutil.copy(os.path.join(conf.root, conf.plum_yml_name), conf.home)


if __name__ == '__main__':
    install()
    init()
