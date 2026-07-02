# -*- coding: utf-8 -*-
"""
布尔运算体相关功能
==================
- 检测选中物体身上的布尔修改器 -> 收集它们引用的运算体（切割体）
- 选中场景里所有被布尔修改器引用的运算体
- 智能切换：一键隐藏 / 显示这些布尔运算体
"""

import bpy

from ..compat import obj_hide_set, obj_hide_get, obj_select, set_active


# -----------------------------------------------------------------------------
# 核心收集逻辑（纯函数，方便复用与测试）
# -----------------------------------------------------------------------------
def iter_boolean_targets(obj):
    """
    遍历单个物体身上所有布尔修改器，产出它们引用的运算体。
    布尔修改器可能通过 .object（单物体）或 .collection（集合模式，2.92+）引用目标。
    """
    for mod in getattr(obj, "modifiers", []):
        if mod.type != 'BOOLEAN':
            continue
        target = getattr(mod, "object", None)
        if target is not None:
            yield target
        coll = getattr(mod, "collection", None)
        if coll is not None:
            for co in coll.all_objects:
                yield co


def collect_from_selection(context):
    """从选中物体出发，收集其布尔修改器引用的所有运算体（去重）。"""
    found = {}
    for obj in context.selected_objects:
        for target in iter_boolean_targets(obj):
            if target is not None:
                found[target.name] = target
    return list(found.values())


def collect_all(context):
    """扫描当前视图层内所有物体，收集被任意布尔修改器引用的运算体（去重）。"""
    found = {}
    for obj in context.view_layer.objects:
        for target in iter_boolean_targets(obj):
            if target is not None:
                found[target.name] = target
    return list(found.values())


def resolve_targets(context, scope):
    """
    根据范围与选择情况决定目标运算体。
    scope:
      'SCENE' -> 始终扫描全场景
      'AUTO'  -> 有选中物体则按选择检索；否则退化为全场景
    返回 list[Object]。
    """
    if scope == 'SCENE':
        return collect_all(context)
    if context.selected_objects:
        return collect_from_selection(context)
    return collect_all(context)


# -----------------------------------------------------------------------------
# 公共属性定义（两个 Operator 共用）
# -----------------------------------------------------------------------------
_SCOPE_ITEMS = [
    ('AUTO', "自动（按选择）", "有选中物体时按选择检索，否则扫描全场景"),
    ('SCENE', "全场景", "扫描整个视图层内所有布尔运算体"),
]


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------
class QOPS_OT_select_boolean_objects(bpy.types.Operator):
    """选中与当前选择相关的布尔运算体（无选择时选中全场景的布尔运算体）"""
    bl_idname = "qops.select_boolean_objects"
    bl_label = "选中布尔运算体"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(name="范围", items=_SCOPE_ITEMS, default='AUTO')
    extend: bpy.props.BoolProperty(
        name="追加到当前选择",
        description="勾选后保留现有选择，否则先清空",
        default=False,
    )

    def execute(self, context):
        targets = resolve_targets(context, self.scope)
        if not targets:
            self.report({'WARNING'}, "未找到相关布尔运算体")
            return {'CANCELLED'}

        if not self.extend:
            for o in context.selected_objects:
                obj_select(o, False)

        count = 0
        last = None
        for o in targets:
            try:
                obj_select(o, True)
                last = o
                count += 1
            except Exception:
                # 被隐藏的物体无法选中，跳过
                pass
        if last is not None:
            set_active(context, last)

        self.report({'INFO'}, "已选中 %d 个布尔运算体" % count)
        return {'FINISHED'}


class QOPS_OT_toggle_boolean_visibility(bpy.types.Operator):
    """智能切换相关布尔运算体的显示/隐藏（临时隐藏，Alt+H 也可恢复）"""
    bl_idname = "qops.toggle_boolean_visibility"
    bl_label = "切换布尔运算体显隐"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(name="范围", items=_SCOPE_ITEMS, default='AUTO')
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
        targets = resolve_targets(context, self.scope)
        if not targets:
            self.report({'WARNING'}, "未找到相关布尔运算体")
            return {'CANCELLED'}

        if self.action == 'HIDE':
            new_state = True
        elif self.action == 'SHOW':
            new_state = False
        else:
            # TOGGLE：只要有一个当前可见就全部隐藏；否则全部显示
            any_visible = any((not obj_hide_get(o)) for o in targets)
            new_state = True if any_visible else False

        vl = context.view_layer
        count = 0
        failed = 0
        for o in targets:
            # 逐物体容错：某个物体（如不在视图层）失败不应中断其余处理
            ok = obj_hide_set(o, new_state, view_layer=vl)
            if ok:
                count += 1
            else:
                failed += 1

        word = "隐藏" if new_state else "显示"
        if failed:
            self.report({'WARNING'},
                        "已%s %d 个布尔运算体，%d 个无法处理（不在场景中）"
                        % (word, count, failed))
        else:
            self.report({'INFO'}, "已%s %d 个布尔运算体" % (word, count))
        return {'FINISHED'}


# 本模块对外暴露的所有可注册类
classes = (
    QOPS_OT_select_boolean_objects,
    QOPS_OT_toggle_boolean_visibility,
)
