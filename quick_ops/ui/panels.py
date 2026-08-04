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

        # ---- 线框显示物体（不限布尔）----
        layout.separator()
        layout.label(text="线框显示物体", icon='MOD_WIREFRAME')
        op_w = layout.operator(
            QOPS_OT_toggle_wire_visibility.bl_idname,
            text="切换线框物体显隐",
            icon='SHADING_WIRE',
        )
        op_w.action = 'TOGGLE'


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


class QOPS_PT_cutline_panel(bpy.types.Panel):
    bl_label = "切割工具"
    bl_idname = "QOPS_PT_cutline_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "qops_cut_mode", text="子工具")
        layout.prop(context.scene, "qops_cut_through")
        if getattr(context.scene, "qops_cut_mode", '') == 'WAND':
            layout.prop(context.scene, "qops_wand_tolerance")
            layout.prop(context.scene, "qops_wand_smooth")
            layout.prop(context.scene, "qops_wand_invert")
        col = layout.column(align=True)
        col.label(text="工具在 T 面板(编辑模式)「J 切割」", icon='TOOL_SETTINGS')
        col.label(text="左键绘制 · Alt擦除 · Shift吸附")
        col.label(text="Ctrl=编辑贝塞尔锚点 · Shift+D复制")
        col.label(text="魔棒:点击色块自动描边(需图像纹理)")
        col.label(text="G移动 S缩放 R旋转 · Ctrl+D 切子工具")
        col.label(text="Enter确认切割 · 退格删除 · X清空")


class QOPS_PT_arrange_panel(bpy.types.Panel):
    bl_label = "自动排列"
    bl_idname = "QOPS_PT_arrange_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        use_coll = getattr(sc, "qops_arr_use_collection", False)
        # 分组方式：层层勾选（集合包含组逻辑）
        layout.prop(sc, "qops_arr_use_parent")
        row = layout.row()
        row.prop(sc, "qops_arr_use_collection")
        if use_coll:
            row.label(text="(含组逻辑)", icon='INFO')
        # 布局参数
        row2 = layout.row(align=True)
        row2.prop(sc, "qops_arr_mode", expand=True)
        if getattr(sc, "qops_arr_mode", 'COLS') == 'COLS':
            layout.prop(sc, "qops_arr_cols")
        else:
            layout.prop(sc, "qops_arr_rows")
        layout.prop(sc, "qops_arr_padding")
        layout.prop(sc, "qops_arr_sort")
        layout.prop(sc, "qops_arr_ground")
        layout.separator()
        layout.operator("qops.auto_arrange", text="执行排列",
                        icon='SORTSIZE')
        layout.separator(factor=0.3)
        layout.operator("qops.select_controlling_objects",
                        text="选中关联控制曲线", icon='CURVE_DATA')


class QOPS_PT_merge_panel(bpy.types.Panel):
    bl_label = "合并导出"
    bl_idname = "QOPS_PT_merge_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "J"

    def draw(self, context):
        layout = self.layout
        layout.operator("qops.merge_export", text="一键合并", icon='MOD_BOOLEAN')
        layout.operator("qops.clear_materials", text="清空材质槽", icon='MATERIAL')
        col = layout.column(align=True)
        col.label(text="合并:打断关联→应用修改器→合并", icon='INFO')
        col.label(text="布尔切割体自动忽略 · 原点置底部")


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


# ── 各功能区的绘制函数（供折叠/排序共用）────────────────────────────────
def _sec_boolean(box, context):
    box.label(text="布尔运算体", icon='MOD_BOOLEAN')
    box.operator(QOPS_OT_select_boolean_objects.bl_idname,
                 text="选中相关布尔运算体", icon='RESTRICT_SELECT_OFF')
    op = box.operator(QOPS_OT_toggle_boolean_visibility.bl_idname,
                      text="切换布尔显隐", icon='HIDE_OFF'); op.action = 'TOGGLE'
    box.separator(factor=0.3)
    box.label(text="线框显示物体", icon='MOD_WIREFRAME')
    op2 = box.operator(QOPS_OT_toggle_wire_visibility.bl_idname,
                       text="切换线框物体显隐", icon='SHADING_WIRE'); op2.action = 'TOGGLE'




def _sec_mirror(box, context):
    box.operator(QOPS_OT_interactive_mirror.bl_idname, text="交互式镜像", icon='MOD_MIRROR')


def _sec_arrange(box, context):
    sc = context.scene
    box.prop(sc, "qops_arr_use_parent")
    box.prop(sc, "qops_arr_use_collection")
    row = box.row(align=True)
    row.prop(sc, "qops_arr_mode", expand=True)
    if getattr(sc, "qops_arr_mode", 'COLS') == 'COLS':
        box.prop(sc, "qops_arr_cols")
    else:
        box.prop(sc, "qops_arr_rows")
    box.prop(sc, "qops_arr_padding")
    box.prop(sc, "qops_arr_sort")
    box.prop(sc, "qops_arr_ground")
    box.operator("qops.auto_arrange", text="执行排列", icon='SORTSIZE')
    box.separator(factor=0.3)
    box.operator("qops.select_controlling_objects",
                 text="选中关联控制曲线", icon='CURVE_DATA')


def _sec_merge(box, context):
    box.operator("qops.merge_export", text="一键合并", icon='MOD_BOOLEAN')
    box.operator("qops.clear_materials", text="清空材质槽", icon='MATERIAL')



def _sec_coat(box, context):
    prefs = None
    try:
        addon = context.preferences.addons.get(__package__.split(".")[0])
        prefs = addon.preferences if addon else None
    except Exception:
        prefs = None
    if prefs is not None:
        box.prop(prefs, "coat_send_to_origin")
        rs = box.row(align=True)
        rs.prop(prefs, "coat_send_scale")
        rs.prop(prefs, "coat_getback_scale")
        box.prop(prefs, "coat_strip_empty_material")
    box.operator(QOPS_OT_coat_send.bl_idname, text="发送到 3DCoat", icon='EXPORT')
    box.operator(QOPS_OT_coat_getback.bl_idname, text="从 3DCoat 取回", icon='IMPORT')


# key -> (标题, 图标, 绘制函数)
_SECTIONS = {
    'boolean': ("布尔线框显隐切换", 'MOD_WIREFRAME', _sec_boolean),
    'mirror':  ("镜像", 'MOD_MIRROR', _sec_mirror),
    'arrange': ("自动排列", 'SORTSIZE', _sec_arrange),
    'merge':   ("合并导出", 'MOD_BOOLEAN', _sec_merge),
    'coat':    ("3DCoat 互导", 'FILE_REFRESH', _sec_coat),
}
_SECTION_DEFAULT_ORDER = ['boolean', 'mirror', 'arrange', 'merge', 'coat']


def _get_section_order(context):
    raw = getattr(context.scene, "qops_section_order", "")
    order = [k for k in raw.split(",") if k in _SECTIONS]
    # 补齐新增/缺失的区块
    for k in _SECTION_DEFAULT_ORDER:
        if k not in order:
            order.append(k)
    return order


def _draw_all(layout, context):
    """把全部功能画到给定 layout —— 供 N 面板与弹出面板共用。
    支持每个功能区折叠 + ▲▼ 调整顺序。"""
    sc = context.scene

    # 顶部：钉固按钮
    layout.operator("qops.toggle_pin", text="钉固为浮动窗口", icon='WINDOW')
    layout.separator(factor=0.3)

    order = _get_section_order(context)
    n = len(order)
    for i, key in enumerate(order):
        label, icon, draw_fn = _SECTIONS[key]
        box = layout.box()
        header = box.row(align=True)
        # 折叠三角
        expand_prop = "qops_sec_" + key
        expanded = getattr(sc, expand_prop, True)
        header.prop(sc, expand_prop,
                    text="", emboss=False,
                    icon='TRIA_DOWN' if expanded else 'TRIA_RIGHT')
        header.label(text=label, icon=icon)
        # ▲▼ 排序按钮
        sub = header.row(align=True)
        up = sub.operator("qops.move_section", text="", icon='TRIA_UP')
        up.key = key; up.direction = 'UP'
        sub.enabled = True
        dn = sub.operator("qops.move_section", text="", icon='TRIA_DOWN')
        dn.key = key; dn.direction = 'DOWN'
        if expanded:
            draw_fn(box, context)



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


class QOPS_OT_toggle_pin(bpy.types.Operator):
    """把 J Panel 钉固为一个独立浮动小窗口（可长期停留，不会点击后消失）"""
    bl_idname = "qops.toggle_pin"
    bl_label = "钉固 J Panel（浮动窗口）"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            bpy.ops.wm.window_new()
            win = context.window_manager.windows[-1]
            area = win.screen.areas[0]
            area.type = 'VIEW_3D'
            space = area.spaces.active
            # 打开 N 侧栏并尽量切到 J 标签
            try:
                space.show_region_ui = True
            except Exception:
                pass
            for r in area.regions:
                if r.type == 'UI':
                    try:
                        r.active_panel_category = "J"
                    except Exception:
                        pass
        except Exception as e:
            self.report({'ERROR'}, "打开浮动窗口失败：%s" % e)
            return {'CANCELLED'}
        return {'FINISHED'}


class QOPS_OT_move_section(bpy.types.Operator):
    """在弹出面板里上移/下移某个功能区"""
    bl_idname = "qops.move_section"
    bl_label = "移动功能区"
    bl_options = {'REGISTER'}
    key: bpy.props.StringProperty(default='')
    direction: bpy.props.EnumProperty(
        items=[('UP', "上移", ""), ('DOWN', "下移", "")], default='UP')

    def execute(self, context):
        order = _get_section_order(context)
        if self.key not in order:
            return {'CANCELLED'}
        i = order.index(self.key)
        j = i - 1 if self.direction == 'UP' else i + 1
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            context.scene.qops_section_order = ",".join(order)
        return {'FINISHED'}


# 本模块对外暴露的所有可注册类
classes = (
    QOPS_OT_move_section,
    QOPS_PT_boolean_panel,
    QOPS_PT_mirror_panel,
    QOPS_PT_cutline_panel,
    QOPS_PT_arrange_panel,
    QOPS_PT_merge_panel,
    QOPS_PT_coat3d_panel,
    QOPS_PT_popover,
    QOPS_OT_show_panel,
    QOPS_OT_toggle_pin,
)


def register_panel_props():
    for key in _SECTION_DEFAULT_ORDER:
        setattr(bpy.types.Scene, "qops_sec_" + key,
                bpy.props.BoolProperty(name=key, default=True))
    bpy.types.Scene.qops_section_order = bpy.props.StringProperty(
        name="功能区顺序", default=",".join(_SECTION_DEFAULT_ORDER))


def unregister_panel_props():
    for key in _SECTION_DEFAULT_ORDER:
        try:
            delattr(bpy.types.Scene, "qops_sec_" + key)
        except Exception:
            pass
    try:
        del bpy.types.Scene.qops_section_order
    except Exception:
        pass
