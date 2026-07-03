# -*- coding: utf-8 -*-
"""
N 面板界面
==========
3D 视图侧栏（N）里的「J」标签页（只显示一个大写字母 J）。
按钮只调用 Operator 的 bl_idname，不含业务逻辑。
"""

import bpy

from ..operators.boolean_ops import (
    QOPS_OT_select_boolean_objects,
    QOPS_OT_toggle_boolean_visibility,
)
from ..operators.mirror_ops import QOPS_OT_interactive_mirror
from ..operators.wireframe_ops import QOPS_OT_toggle_wire_visibility
from ..operators.coat3d_ops import (
    QOPS_OT_coat_send,
    QOPS_OT_coat_getback,
)


class QOPS_PT_boolean_panel(bpy.types.Panel):
    bl_label = "布尔运算体"
    bl_idname = "QOPS_PT_boolean_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout

        # 顶部：一键呼出包含全部功能的弹出菜单（也可绑快捷键 / 供 PME 调用）
        layout.operator("qops.show_menu", text="呼出功能菜单", icon='PRESET')
        layout.separator()

        layout.operator(
            QOPS_OT_select_boolean_objects.bl_idname,
            text="选中相关布尔运算体",
            icon='RESTRICT_SELECT_OFF',
        )

        layout.separator()

        op = layout.operator(
            QOPS_OT_toggle_boolean_visibility.bl_idname,
            text="切换显隐",
            icon='HIDE_OFF',
        )
        op.action = 'TOGGLE'

        row = layout.row(align=True)
        op_hide = row.operator(
            QOPS_OT_toggle_boolean_visibility.bl_idname,
            text="隐藏",
            icon='HIDE_ON',
        )
        op_hide.action = 'HIDE'
        op_show = row.operator(
            QOPS_OT_toggle_boolean_visibility.bl_idname,
            text="显示",
            icon='HIDE_OFF',
        )
        op_show.action = 'SHOW'

        # ---- 线框显示物体（不限布尔）----
        layout.separator()
        layout.label(text="线框显示物体", icon='MOD_WIREFRAME')
        op_w = layout.operator(
            QOPS_OT_toggle_wire_visibility.bl_idname,
            text="切换线框物体显隐",
            icon='SHADING_WIRE',
        )
        op_w.action = 'TOGGLE'
        row_w = layout.row(align=True)
        w_hide = row_w.operator(
            QOPS_OT_toggle_wire_visibility.bl_idname,
            text="隐藏",
            icon='HIDE_ON',
        )
        w_hide.action = 'HIDE'
        w_show = row_w.operator(
            QOPS_OT_toggle_wire_visibility.bl_idname,
            text="显示",
            icon='HIDE_OFF',
        )
        w_show.action = 'SHOW'


class QOPS_PT_mirror_panel(bpy.types.Panel):
    bl_label = "镜像"
    bl_idname = "QOPS_PT_mirror_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            QOPS_OT_interactive_mirror.bl_idname,
            text="交互式镜像",
            icon='MOD_MIRROR',
        )
        layout.label(text="多选:以最后选中为基准 / 单选:自身", icon='INFO')
        col = layout.column(align=True)
        col.label(text="移动鼠标选方向")
        col.label(text="左键确认 · 右键/ESC 取消")


class QOPS_PT_coat3d_panel(bpy.types.Panel):
    bl_label = "3DCoat 互导"
    bl_idname = "QOPS_PT_coat3d_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout

        # 面板内的“发送到原点”勾选项（与偏好设置里的同一个开关，状态同步）
        prefs = None
        try:
            addon = context.preferences.addons.get(__package__.split(".")[0])
            prefs = addon.preferences if addon else None
        except Exception:
            prefs = None
        if prefs is not None:
            layout.prop(prefs, "coat_send_to_origin")
            row_s = layout.row(align=True)
            row_s.prop(prefs, "coat_send_scale")
            row_s.prop(prefs, "coat_getback_scale")
            layout.prop(prefs, "coat_strip_empty_material")

        col = layout.column(align=True)
        col.operator(
            QOPS_OT_coat_send.bl_idname,
            text="发送到 3DCoat",
            icon='EXPORT',
        )
        col.operator(
            QOPS_OT_coat_getback.bl_idname,
            text="从 3DCoat 取回",
            icon='IMPORT',
        )
        layout.label(text="发送选中网格 · 取回自动还原比例", icon='INFO')
        layout.label(text="路径/缩放在偏好设置里配置", icon='PREFERENCES')


def _draw_all(layout, context):
    """把全部功能画到给定 layout —— 供 N 面板与弹出面板共用。"""
    prefs = None
    try:
        addon = context.preferences.addons.get(__package__.split(".")[0])
        prefs = addon.preferences if addon else None
    except Exception:
        prefs = None

    box = layout.box()
    box.label(text="布尔运算体", icon='MOD_BOOLEAN')
    box.operator(QOPS_OT_select_boolean_objects.bl_idname,
                 text="选中相关布尔运算体", icon='RESTRICT_SELECT_OFF')
    op = box.operator(QOPS_OT_toggle_boolean_visibility.bl_idname,
                      text="切换显隐", icon='HIDE_OFF'); op.action = 'TOGGLE'
    r = box.row(align=True)
    a = r.operator(QOPS_OT_toggle_boolean_visibility.bl_idname, text="隐藏", icon='HIDE_ON'); a.action = 'HIDE'
    b = r.operator(QOPS_OT_toggle_boolean_visibility.bl_idname, text="显示", icon='HIDE_OFF'); b.action = 'SHOW'

    box = layout.box()
    box.label(text="线框显示物体", icon='MOD_WIREFRAME')
    op = box.operator(QOPS_OT_toggle_wire_visibility.bl_idname,
                      text="切换线框物体显隐", icon='SHADING_WIRE'); op.action = 'TOGGLE'
    r = box.row(align=True)
    a = r.operator(QOPS_OT_toggle_wire_visibility.bl_idname, text="隐藏", icon='HIDE_ON'); a.action = 'HIDE'
    b = r.operator(QOPS_OT_toggle_wire_visibility.bl_idname, text="显示", icon='HIDE_OFF'); b.action = 'SHOW'

    box = layout.box()
    box.label(text="镜像", icon='MOD_MIRROR')
    box.operator(QOPS_OT_interactive_mirror.bl_idname, text="交互式镜像", icon='MOD_MIRROR')

    box = layout.box()
    box.label(text="3DCoat 互导", icon='FILE_REFRESH')
    if prefs is not None:
        box.prop(prefs, "coat_send_to_origin")
        rs = box.row(align=True)
        rs.prop(prefs, "coat_send_scale")
        rs.prop(prefs, "coat_getback_scale")
        box.prop(prefs, "coat_strip_empty_material")
    box.operator(QOPS_OT_coat_send.bl_idname, text="发送到 3DCoat", icon='EXPORT')
    box.operator(QOPS_OT_coat_getback.bl_idname, text="从 3DCoat 取回", icon='IMPORT')


class QOPS_PT_popover(bpy.types.Panel):
    """J Panel 完整弹出面板（供 wm.call_panel 呼出 / PME 引用）"""
    bl_label = "J Panel"
    bl_idname = "QOPS_PT_popover"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'   # 作为弹出面板使用

    def draw(self, context):
        _draw_all(self.layout, context)


class QOPS_OT_show_panel(bpy.types.Operator):
    """弹出完整的 J Panel 面板（可绑快捷键 / PME 用 bpy.ops.qops.show_panel() 调用）"""
    bl_idname = "qops.show_panel"
    bl_label = "呼出 J Panel 面板"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            bpy.ops.wm.call_panel(name=QOPS_PT_popover.bl_idname, keep_open=True)
        except Exception as e:
            self.report({'ERROR'}, "呼出面板失败：%s" % e)
            return {'CANCELLED'}
        return {'FINISHED'}


# 本模块对外暴露的所有可注册类
classes = (
    QOPS_PT_boolean_panel,
    QOPS_PT_mirror_panel,
    QOPS_PT_coat3d_panel,
    QOPS_PT_popover,
    QOPS_OT_show_panel,
)
