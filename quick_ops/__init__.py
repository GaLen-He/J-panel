# -*- coding: utf-8 -*-
"""
J Panel
================
一款把常用但 Blender 原生缺失的基础操作集成到 N 面板、并支持快捷键 / PME 调用的插件。
N 面板标签只显示一个大写字母 J。

包结构（规范多文件）
--------------------
quick_ops/
├── __init__.py        <- 本文件：只做 bl_info + 导入 + 注册汇总
├── compat.py          <- 版本兼容层
├── preferences.py     <- 插件偏好设置（含可编辑的快捷键入口）
├── operators/         <- 所有功能算子（Operator），按类别分模块
│   ├── __init__.py
│   ├── boolean_ops.py <- 布尔运算体：检测 / 选中 / 显隐
│   └── mirror_ops.py  <- 交互式镜像修改器（模态 + 3D 坐标轴 gizmo）
├── ui/                <- 所有界面面板
│   ├── __init__.py
│   └── panels.py      <- N 面板
├── draw_utils.py      <- 跨版本 GPU 绘制辅助
└── keymaps.py         <- 快捷键注册

设计原则
--------
1. 一切皆 Operator：每个功能都有稳定的 bl_idname（前缀 qops.），N 面板按钮、快捷键、
   PieMenuEditor 及其他插件都能通过这个 id 调用。
2. 版本兼容：目标 Blender 3.0 ~ 5.x。仅使用稳定 API 子集，差异集中在 compat.py / draw_utils.py。
3. __init__ 只作导入与注册汇总，功能主体在各模块中，方便扩展。
"""

bl_info = {
    "name": "J Panel",
    "author": "Jialiang",
    "version": (0, 8, 3),
    "blender": (3, 0, 0),
    "location": "View3D > 侧栏 (N) > J",
    "description": "常用基础操作集成到 N 面板，支持快捷键与 PME。含布尔运算体管理、交互式镜像修改器。",
    "category": "Object",
}

# 支持“重载脚本”时正确刷新子模块
if "bpy" in locals():
    import importlib
    from . import compat, keymaps, preferences, draw_utils, coat3d_link
    from . import operators as _operators
    from . import ui as _ui
    importlib.reload(compat)
    importlib.reload(draw_utils)
    importlib.reload(_operators)
    importlib.reload(_ui)
    importlib.reload(keymaps)
    importlib.reload(coat3d_link)
    importlib.reload(preferences)

import bpy

from . import operators
from . import ui
from . import keymaps
from . import preferences
from . import coat3d_link


def register():
    coat3d_link.register_props()
    preferences.register()
    operators.register()
    ui.register()
    keymaps.register()


def unregister():
    # 反向注销，避免依赖顺序问题
    keymaps.unregister()
    ui.unregister()
    operators.unregister()
    preferences.unregister()
    coat3d_link.unregister_props()


if __name__ == "__main__":
    register()
