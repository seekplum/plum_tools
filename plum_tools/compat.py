#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: compat
#         Desc: 兼容Python2/Python3
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 20:16
#=============================================================================
"""

import sys

PY2 = sys.version_info[0] == 2

if PY2:
    text_type = unicode


    def implements_to_string(cls):
        if isinstance(cls, str):
            return cls

        if isinstance(cls, unicode):
            cls = cls.encode('utf-8')
        else:
            cls = implements_to_unicode("%s" % cls)
        return cls


    def implements_to_unicode(cls):
        if isinstance(cls, unicode):
            return cls

        if isinstance(cls, str):
            cls = cls.decode('utf-8')
        else:
            cls = implements_to_unicode("%s" % cls)
        return cls

else:
    text_type = str


    def implements_to_string(x):
        return "%s" % x


    def implements_to_unicode(x):
        return "%s" % x
