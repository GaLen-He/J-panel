# -*- coding: utf-8 -*-
"""
交互式镜像修改器
================
激活后在视口绘制一个 3D 坐标轴 gizmo，鼠标移动选择镜像方向（当前方向加粗高亮），
左键确认、右键 / ESC 取消。

两种模式：
- 多物体：以“最后选中的物体（活动物体）”为镜像基准，为其余物体添加镜像修改器；
  基准物体本身不会被加修改器、不会被移动。
- 单物体：以物体自身参考系（自身局部原点/坐标轴）为基准做自镜像
  （mirror_object=None）。

方向说明：镜像修改器的镜像平面是对称的（同一根轴的 +/- 定义同一镜面）。
本功能提供 6 方向 gizmo 便于直观选择，底层按所选“轴向”施加纯镜像
（不切割几何体）。
"""

import bpy
from mathutils import Vector
from bpy_extras import view3d_utils

from ..draw_utils import get_uniform_color_shader, draw_lines, draw_points, reset_state


# 6 个方向：(名称, 轴索引, 符号, 基础颜色)
_AXES = [
    ("+X", 0, 1.0, (1.0, 0.2, 0.2, 1.0)),
    ("-X", 0, -1.0, (1.0, 0.2, 0.2, 1.0)),
    ("+Y", 1, 1.0, (0.4, 1.0, 0.3, 1.0)),
    ("-Y", 1, -1.0, (0.4, 1.0, 0.3, 1.0)),
    ("+Z", 2, 1.0, (0.3, 0.5, 1.0, 1.0)),
    ("-Z", 2, -1.0, (0.3, 0.5, 1.0, 1.0)),
]


def _axis_vectors(base_obj, index, sign):
    """返回基准物体局部坐标轴在世界空间的方向（已归一化）。"""
    mat = base_obj.matrix_world
    # 取旋转部分作用于单位轴
    v = Vector((0.0, 0.0, 0.0))
    v[index] = sign
    world_dir = (mat.to_3x3() @ v)
    if world_dir.length > 1e-8:
        world_dir.normalize()
    return world_dir


class QOPS_OT_interactive_mirror(bpy.types.Operator):
    """以最后选中物体为基准，交互式为其余选中物体添加镜像修改器"""
    bl_idname = "qops.interactive_mirror"
    bl_label = "交互式镜像"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object is not None

    # ---- 生命周期 ----
    def invoke(self, context, event):
        base = context.active_object
        if base is None:
            self.report({'WARNING'}, "没有活动物体作为镜像基准")
            return {'CANCELLED'}

        # 排除基准自身，得到需要加修改器的目标物体
        sel = [o for o in context.selected_objects if o != base]

        self.base = base
        if sel:
            # 多物体：以最后选中(活动)物体为镜像基准，其余物体镜像
            self.targets = sel
            self.self_mode = False
        else:
            # 单物体：以自身参考系(自身局部坐标)为基准做自镜像
            self.targets = [base]
            self.self_mode = True
        self.origin = base.matrix_world.translation.copy()
        self.current = 0  # 默认高亮 +X
        self._shader = get_uniform_color_shader()

        # 注册视口绘制回调
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (context,), 'WINDOW', 'POST_VIEW'
        )
        # 单独一个 2D 回调用于提示文字（可选，简洁起见此处省略文字）
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _remove_handle(self):
        """只移除一次绘制回调，幂等且带兜底。"""
        h = getattr(self, "_handle", None)
        if h is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
            except Exception:
                pass
            self._handle = None

    def _finish(self, context):
        self._remove_handle()
        # 刷新所有 3D 视图，确保 gizmo 残影被清掉
        try:
            for area in context.window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        except Exception:
            if context.area:
                context.area.tag_redraw()

    def cancel(self, context):
        """被系统中断时 Blender 调用此方法（而非 modal），必须在这里清理回调。"""
        self._finish(context)

    # ---- 交互 ----
    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            self._update_current(context, event)
            return {'RUNNING_MODAL'}

        # 在“左键按下”时记录方向，但在“左键抬起”时才确认。
        # 这样可以吃掉整对 按下/抬起 事件，避免 release 漏给视口工具
        # 导致用完后点击变成框选、难以选中物体（Blender 4.x/5.0 尤为明显）。
        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._update_current(context, event)
                return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE':
                self._finish(context)
                return self._apply(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            self.report({'INFO'}, "已取消镜像")
            return {'CANCELLED'}

        # 允许缩放/旋转视图（透传导航事件）
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def _update_current(self, context, event):
        """根据鼠标位置，挑选屏幕上方向最接近的坐标轴方向。"""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return
        center = view3d_utils.location_3d_to_region_2d(region, rv3d, self.origin)
        if center is None:
            return
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        mdir = mouse - center
        if mdir.length < 1e-4:
            return
        mdir.normalize()

        best_i = self.current
        best_dot = -2.0
        length = self._gizmo_length(context)
        for i, (_name, index, sign, _col) in enumerate(_AXES):
            tip3d = self.origin + _axis_vectors(self.base, index, sign) * length
            tip2d = view3d_utils.location_3d_to_region_2d(region, rv3d, tip3d)
            if tip2d is None:
                continue
            sdir = tip2d - center
            if sdir.length < 1e-4:
                continue
            sdir.normalize()
            d = mdir.dot(sdir)
            if d > best_dot:
                best_dot = d
                best_i = i
        self.current = best_i

    def _gizmo_length(self, context):
        """gizmo 视觉长度，随物体尺寸略作缩放。"""
        dims = self.base.dimensions
        base_size = max(dims.x, dims.y, dims.z, 1.0)
        return base_size * 0.9 + 0.5

    # ---- 应用 ----
    def _apply(self, context):
        name, index, sign, _col = _AXES[self.current]
        count = 0
        for obj in self.targets:
            # 双保险：多物体模式下，基准物体绝不加修改器（避免自我镜像导致基准“被移动/翻倍”）
            if not self.self_mode and obj == self.base:
                continue
            try:
                mod = obj.modifiers.new(name="Mirror", type='MIRROR')
                # 单物体自镜像用 None（以自身局部原点/坐标轴为镜面），
                # 多物体则以基准物体为镜面参考。
                mod.mirror_object = None if self.self_mode else self.base
                mod.use_axis = (index == 0, index == 1, index == 2)
                count += 1
            except Exception:
                pass
        if self.self_mode:
            self.report({'INFO'}, "已按 %s 轴为物体添加自镜像修改器（基准：自身）"
                        % (name[1],))
        else:
            self.report({'INFO'}, "已按 %s 轴为 %d 个物体添加镜像修改器（基准：%s）"
                        % (name[1], count, self.base.name))
        return {'FINISHED'}

    # ---- 绘制 ----
    def _draw_callback(self, context):
        # 全程 guard：任何异常都不得每帧抛出（否则会干扰视口交互）。
        try:
            if context.region_data is None:
                return
            # 基准物体可能已被删除，访问其矩阵会报错
            base = getattr(self, "base", None)
            if base is None or base.name not in bpy.data.objects:
                return
            shader = self._shader
            length = self._gizmo_length(context)
            o = self.origin

            # 先画三根完整轴（暗色细线）
            for index, col in ((0, (0.6, 0.15, 0.15, 0.5)),
                               (1, (0.2, 0.55, 0.15, 0.5)),
                               (2, (0.15, 0.3, 0.6, 0.5))):
                pos = o + _axis_vectors(base, index, 1.0) * length
                neg = o + _axis_vectors(base, index, -1.0) * length
                draw_lines(shader, [neg, pos], col, width=2.0)

            # 再画当前选中的方向（加粗高亮 + 端点）
            name, index, sign, col = _AXES[self.current]
            tip = o + _axis_vectors(base, index, sign) * length
            bright = (col[0], col[1], col[2], 1.0)
            draw_lines(shader, [o, tip], bright, width=6.0)
            draw_points(shader, [tip], (1.0, 1.0, 1.0, 1.0), size=12.0)
            draw_points(shader, [o], (1.0, 1.0, 1.0, 1.0), size=8.0)
        except Exception:
            pass
        finally:
            reset_state()


classes = (
    QOPS_OT_interactive_mirror,
)
