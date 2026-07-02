# -*- coding: utf-8 -*-
"""
快捷键注册
==========
在此注册插件的默认快捷键。用户可在「偏好设置 > 插件 > J 面板」展开后
的快捷键区域自行修改 / 停用，或直接在 PieMenuEditor(PME) 里调用对应 bl_idname。

默认按键：
- qops.interactive_mirror  ->  Alt+Shift+X（交互式镜像）
- qops.toggle_boolean_visibility  ->  Alt+Shift+H（切换布尔运算体显隐）
- qops.toggle_wire_visibility     ->  Alt+Shift+W（切换线框物体显隐）

如需改默认：修改下面对应 _new_kmi 的 type 与修饰键即可。

维护约定：每新增一个“大功能按钮”，都应在下面 register() 里为其
_new_kmi 注册一条快捷键条目（默认可 type='NONE' 不绑定），这样它会
自动出现在偏好设置面板的快捷键框中，供用户设置。
"""

import bpy

# 保存 (keymap, keymap_item) 以便注销与偏好面板绘制
addon_keymaps = []


def _new_kmi(km, idname, type='NONE', value='PRESS',
             ctrl=False, shift=False, alt=False, oskey=False, **props):
    kmi = km.keymap_items.new(
        idname, type=type, value=value,
        ctrl=ctrl, shift=shift, alt=alt, oskey=oskey,
    )
    for k, v in props.items():
        setattr(kmi.properties, k, v)
    addon_keymaps.append((km, kmi))
    return kmi


def register():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')

    # 交互式镜像 —— 默认 Alt+Shift+X
    _new_kmi(km, "qops.interactive_mirror",
             type='X', value='PRESS', shift=True, alt=True)

    # 切换布尔运算体显隐 —— 默认 Alt+Shift+H
    _new_kmi(km, "qops.toggle_boolean_visibility",
             type='H', value='PRESS', shift=True, alt=True, action='TOGGLE')

    # 切换线框物体显隐 —— 默认 Alt+Shift+W
    _new_kmi(km, "qops.toggle_wire_visibility",
             type='W', value='PRESS', shift=True, alt=True, action='TOGGLE')


def unregister():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()
