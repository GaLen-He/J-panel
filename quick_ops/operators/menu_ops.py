# -*- coding: utf-8 -*-
"""
呼出 J Panel 功能菜单
=====================
提供一个弹出菜单，一键呼出 J Panel 的所有功能，不必去 N 面板里找。
- QOPS_MT_main_menu：菜单本体（bpy.types.Menu），PieMenuEditor(PME) 可识别引用。
- qops.show_menu：弹出该菜单的算子，可绑快捷键、也可被 PME 用命令调用
  bpy.ops.qops.show_menu()。默认不绑定快捷键，入口在偏好设置的快捷键区。
"""

import bpy

from .boolean_ops import (
    QOPS_OT_select_boolean_objects,
    QOPS_OT_toggle_boolean_visibility,
)
from .wireframe_ops import QOPS_OT_toggle_wire_visibility
from .mirror_ops import QOPS_OT_interactive_mirror
from .coat3d_ops import QOPS_OT_coat_send, QOPS_OT_coat_getback


class QOPS_MT_main_menu(bpy.types.Menu):
    """J Panel 主菜单（可被 PieMenuEditor 引用）"""
    bl_label = "J Panel"
    bl_idname = "QOPS_MT_main_menu"

    def draw(self, context):
        layout = self.layout

        layout.operator(QOPS_OT_select_boolean_objects.bl_idname,
                        text="选中布尔运算体", icon='RESTRICT_SELECT_OFF')
        op = layout.operator(QOPS_OT_toggle_boolean_visibility.bl_idname,
                             text="切换布尔运算体显隐", icon='HIDE_OFF')
        op.action = 'TOGGLE'

        layout.separator()
        op = layout.operator(QOPS_OT_toggle_wire_visibility.bl_idname,
                             text="切换线框物体显隐", icon='SHADING_WIRE')
        op.action = 'TOGGLE'

        layout.separator()
        layout.operator(QOPS_OT_interactive_mirror.bl_idname,
                        text="交互式镜像", icon='MOD_MIRROR')

        layout.separator()
        layout.operator(QOPS_OT_coat_send.bl_idname,
                        text="发送到 3DCoat", icon='EXPORT')
        layout.operator(QOPS_OT_coat_getback.bl_idname,
                        text="从 3DCoat 取回", icon='IMPORT')


class QOPS_OT_show_menu(bpy.types.Operator):
    """弹出 J Panel 功能菜单（可绑快捷键 / 供 PME 调用）"""
    bl_idname = "qops.show_menu"
    bl_label = "呼出 J Panel 菜单"
    bl_options = {'REGISTER'}

    def execute(self, context):
        bpy.ops.wm.call_menu(name=QOPS_MT_main_menu.bl_idname)
        return {'FINISHED'}


classes = (
    QOPS_MT_main_menu,
    QOPS_OT_show_menu,
)
