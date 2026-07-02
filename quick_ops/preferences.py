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

    def draw(self, context):
        layout = self.layout

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
