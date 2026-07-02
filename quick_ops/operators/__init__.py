# -*- coding: utf-8 -*-
"""
operators 子包
==============
汇总各功能模块里的 Operator 类，统一注册 / 注销。

新增功能时：
1. 在本目录新建模块（如 transform_ops.py），里面定义 Operator 类，
   并在模块末尾用 classes = (...) 暴露它们；
2. 在下方 _MODULES 里加上你的模块；
   无需改动 __init__.py 的其余部分。
"""

import bpy

from . import boolean_ops
from . import mirror_ops
from . import wireframe_ops

# 所有功能模块，按需扩充
_MODULES = (
    boolean_ops,
    mirror_ops,
    wireframe_ops,
)


def _all_classes():
    for mod in _MODULES:
        for cls in getattr(mod, "classes", ()):
            yield cls


def register():
    for cls in _all_classes():
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(list(_all_classes())):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
