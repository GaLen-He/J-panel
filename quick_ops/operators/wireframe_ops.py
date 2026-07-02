# -*- coding: utf-8 -*-
"""
线框显示物体相关功能
====================
针对“显示模式被设为线框”的物体（display_type == 'WIRE'），不限布尔物体。
用途：Alt+H 会把所有隐藏物体一起显示出来（包括线框物体），这里提供一个
独立的“隐藏/显示所有线框显示物体”开关来单独管理它们。
"""

import bpy

from ..compat import obj_hide_set, obj_hide_get


def collect_wire_objects(context):
    """收集当前视图层内所有 display_type == 'WIRE' 的物体（去重）。"""
    found = {}
    for obj in context.view_layer.objects:
        if getattr(obj, "display_type", None) == 'WIRE':
            found[obj.name] = obj
    return list(found.values())


class QOPS_OT_toggle_wire_visibility(bpy.types.Operator):
    """智能切换所有线框显示物体的显示/隐藏（display_type=='WIRE'，不限布尔）"""
    bl_idname = "qops.toggle_wire_visibility"
    bl_label = "切换线框物体显隐"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(
        name="操作",
        items=[
            ('TOGGLE', "切换", "根据当前状态自动切换显示或隐藏"),
            ('HIDE', "隐藏", "强制隐藏"),
            ('SHOW', "显示", "强制显示"),
        ],
        default='TOGGLE',
    )

    def execute(self, context):
        targets = collect_wire_objects(context)
        if not targets:
            self.report({'WARNING'}, "未找到线框显示物体（display_type=WIRE）")
            return {'CANCELLED'}

        if self.action == 'HIDE':
            new_state = True
        elif self.action == 'SHOW':
            new_state = False
        else:
            any_visible = any((not obj_hide_get(o)) for o in targets)
            new_state = True if any_visible else False

        vl = context.view_layer
        count = 0
        failed = 0
        for o in targets:
            ok = obj_hide_set(o, new_state, view_layer=vl)
            if ok:
                count += 1
            else:
                failed += 1

        word = "隐藏" if new_state else "显示"
        if failed:
            self.report({'WARNING'},
                        "已%s %d 个线框物体，%d 个无法处理（不在场景中）"
                        % (word, count, failed))
        else:
            self.report({'INFO'}, "已%s %d 个线框物体" % (word, count))
        return {'FINISHED'}


classes = (
    QOPS_OT_toggle_wire_visibility,
)
