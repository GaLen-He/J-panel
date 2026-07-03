# -*- coding: utf-8 -*-
"""
插件偏好设置
============
在「偏好设置 > 插件 > 快捷操作集合」展开后显示。
用 Blender 原生的 rna_keymap_ui 绘制本插件注册的快捷键，
用户可在此自行设置 / 修改 / 启用停用快捷键。默认不绑定按键。
"""

import bpy
import rna_keymap_ui

from . import keymaps


class QOPS_AddonPreferences(bpy.types.AddonPreferences):
    # 必须等于插件包名（顶层包名），Blender 用它匹配偏好设置。
    # __package__ 在本子模块里是 "quick_ops.preferences"，取第一段即包名。
    bl_idname = __package__.split(".")[0]

    # ---- 3DCoat 互导设置 ----
    coat_exchange_folder: bpy.props.StringProperty(
        name="3DCoat 交换文件夹",
        description="3DCoat AppLink 的 Exchange 目录；留空则自动探测",
        subtype='DIR_PATH',
        default="",
    )
    coat_send_scale: bpy.props.FloatProperty(
        name="发送缩放",
        description="发送到 3DCoat 时 FBX 的 global_scale。"
                    "若发到 3DCoat 里太小/太大，调这个值",
        default=0.8,
        min=0.0001,
        soft_min=0.001,
        soft_max=100.0,
    )
    coat_getback_scale: bpy.props.FloatProperty(
        name="取回缩放",
        description="从 3DCoat 取回时 FBX 的 global_scale。官方默认 0.01。"
                    "若取回后模型过大/过小，调这个值即可（无需再手动乘 0.07/0.017）",
        default=0.01,
        min=0.0001,
        soft_min=0.001,
        soft_max=100.0,
    )
    coat_send_to_origin: bpy.props.BoolProperty(
        name="发送到原点",
        description="发送前把物体临时移到世界原点再导出，让它在 3DCoat 里落在画布中心；"
                    "导出后 Blender 里的位置会自动还原。关闭则保留原始世界坐标",
        default=True,
    )
    coat_strip_empty_material: bpy.props.BoolProperty(
        name="取回不带空材质",
        description="取回时，如果 3DCoat 里没给模型上材质（FBX 带的是无纹理的默认材质），"
                    "自动清除该材质；只有在 3DCoat 里赋了材质/画了贴图（材质含纹理）才保留",
        default=True,
    )

    def draw(self, context):
        layout = self.layout

        # ---- 3DCoat 互导设置 ----
        cbox = layout.box()
        cbox.label(text="3DCoat 互导", icon='FILE_REFRESH')
        row = cbox.row(align=True)
        row.prop(self, "coat_exchange_folder", text="交换文件夹")
        row.operator("qops.coat_detect_exchange", text="", icon='VIEWZOOM')
        rows = cbox.row(align=True)
        rows.prop(self, "coat_send_scale")
        rows.prop(self, "coat_getback_scale")
        cbox.prop(self, "coat_send_to_origin")
        cbox.prop(self, "coat_strip_empty_material")
        cbox.label(text="发送默认0.8、取回默认0.01。发太小/取回太大就分别调",
                   icon='INFO')

        box = layout.box()
        box.label(text="快捷键", icon='KEYINGSET')
        box.label(
            text="默认未绑定按键。点下方每项右侧的输入框录制你想要的快捷键。",
            icon='INFO',
        )

        if not keymaps.addon_keymaps:
            box.label(text="（本插件当前没有注册任何快捷键条目）", icon='ERROR')
            return

        # Blender 官方推荐写法：用 addon keyconfig 绘制本插件的 keymap item，
        # 修改会正常保存。见官方 Add-on 教程的 Preferences 示例。
        wm = context.window_manager
        kc = wm.keyconfigs.addon
        for km, kmi in keymaps.addon_keymaps:
            col = box.column()
            col.context_pointer_set("keymap", km)
            rna_keymap_ui.draw_kmi(
                ["ADDON", "USER", "DEFAULT"],
                kc, km, kmi, col, 0,
            )


classes = (
    QOPS_AddonPreferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
