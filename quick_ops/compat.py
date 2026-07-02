# -*- coding: utf-8 -*-
"""
版本兼容层
==========
把有 Blender 版本差异的调用集中在这里，主逻辑不碰版本判断。
目标兼容：Blender 3.0 ~ 5.x。
"""

import bpy


def bl_ver():
    """返回当前 Blender 版本元组，如 (4, 2, 0)。"""
    return bpy.app.version


def obj_hide_set(obj, state, view_layer=None):
    """
    临时隐藏/显示（相当于快捷键 H / Alt+H）。
    2.91+ 支持 view_layer 关键字；老版本只接受一个参数。

    健壮性：对“不在当前视图层”的物体（放在未链接到视图层的集合里、
    或以资产追加方式加载进来的），hide_set() 会抛 RuntimeError。
    此时回退到物体级的 hide_viewport（全局开关，不依赖视图层），
    保证“在这个文件里的物体”仍能被隐藏，而不是让调用方中断。

    返回 True 表示成功（含回退成功），False 表示彻底无法隐藏。
    """
    # 首选：视图层级临时隐藏（对应 H / Alt+H）
    try:
        if view_layer is not None and bl_ver() >= (2, 91, 0):
            obj.hide_set(state, view_layer=view_layer)
        else:
            obj.hide_set(state)
        return True
    except TypeError:
        try:
            obj.hide_set(state)
            return True
        except Exception:
            pass
    except Exception:
        pass
    # 回退：物体级全局开关（不依赖视图层）
    try:
        obj.hide_viewport = state
        return True
    except Exception:
        return False


def obj_hide_get(obj):
    """读取可见状态，容错。无法读取时视为“可见”(False)。"""
    try:
        return obj.hide_get()
    except Exception:
        try:
            return bool(obj.hide_viewport)
        except Exception:
            return False


def obj_select(obj, state):
    """选中/取消选中，兼容 2.8+ 的 select_set。"""
    obj.select_set(state)


def set_active(context, obj):
    """设置活动物体，兼容不同 context。"""
    try:
        context.view_layer.objects.active = obj
    except Exception:
        pass
