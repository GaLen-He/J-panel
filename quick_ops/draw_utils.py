# -*- coding: utf-8 -*-
"""
跨版本 GPU 绘制辅助
===================
Blender 的视口绘制 API 在 4.0 前后有差异：内置着色器名从 '3D_UNIFORM_COLOR'
改为 'UNIFORM_COLOR'（2D/3D 前缀被去掉）。这里做统一封装，主逻辑不碰版本判断。
目标兼容：Blender 3.0 ~ 5.x（均已是 gpu 模块时代，无需 bgl）。
"""

import gpu
from gpu_extras.batch import batch_for_shader

from .compat import bl_ver


def _uniform_color_shader_name():
    # 4.0 起去掉了维度前缀
    return 'UNIFORM_COLOR' if bl_ver() >= (4, 0, 0) else '3D_UNIFORM_COLOR'


def get_uniform_color_shader():
    return gpu.shader.from_builtin(_uniform_color_shader_name())


def draw_lines(shader, coords, color, width=1.0):
    """用 LINES 图元绘制一批线段。coords 为偶数个点，两两一段。"""
    try:
        gpu.state.line_width_set(width)
    except Exception:
        pass
    try:
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
    except Exception:
        pass
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_points(shader, coords, color, size=6.0):
    """绘制一批点。"""
    try:
        gpu.state.point_size_set(size)
    except Exception:
        pass
    try:
        gpu.state.blend_set('ALPHA')
    except Exception:
        pass
    batch = batch_for_shader(shader, 'POINTS', {"pos": coords})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def reset_state():
    try:
        gpu.state.line_width_set(1.0)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('NONE')
    except Exception:
        pass
