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


class QOPS_PT_boolean_panel(bpy.types.Panel):
    bl_label = "布尔运算体"
    bl_idname = "QOPS_PT_boolean_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout

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


# 本模块对外暴露的所有可注册类
classes = (
    QOPS_PT_boolean_panel,
    QOPS_PT_mirror_panel,
)
