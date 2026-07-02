# -*- coding: utf-8 -*-
"""
ui 子包
=======
汇总所有面板类，统一注册 / 注销。

新增面板时：在本目录建模块并用 classes 暴露，然后加入下方 _MODULES。
"""

import bpy

from . import panels

_MODULES = (
    panels,
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
