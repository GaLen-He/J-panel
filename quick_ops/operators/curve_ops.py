# -*- coding: utf-8 -*-
"""
曲线顶点倒角（交互式）
======================
Ctrl+Shift+B  或  右键菜单「曲线倒角」

• 拖动鼠标左右 → 改变倒角半径
• 滚轮 Up/Down → 增减段数（1~16 段，多段用 De Casteljau 精确分割圆弧）
• LMB / Enter  → 确认
• RMB / Esc    → 取消，恢复原始曲线
"""

import bpy
import math
from mathutils import Vector


# =============================================================================
# 向量辅助
# =============================================================================
def _lerp(a, b, t):
    return a + (b - a) * t


def _split_at_t(P0, C1, C2, P3, t):
    """De Casteljau 在 t 处分割，返回 (left, right)，各为 (P,C1,C2,P) 四元组。"""
    A = _lerp(P0, C1, t)
    B = _lerp(C1, C2, t)
    C = _lerp(C2, P3, t)
    D = _lerp(A,  B,  t)
    E = _lerp(B,  C,  t)
    F = _lerp(D,  E,  t)
    return (P0, A, D, F), (F, E, C, P3)


def _split_into_n(P0, C1, C2, P3, n):
    """把贝塞尔曲线分成 n 段，返回 n 个 (p0, c1, c2, p3) 段。"""
    if n == 1:
        return [(P0, C1, C2, P3)]
    segs = []
    rem = (P0, C1, C2, P3)
    for i in range(n - 1):
        t = 1.0 / (n - i)
        left, rem = _split_at_t(*rem, t)
        segs.append(left)
    segs.append(rem)
    return segs


# =============================================================================
# 倒角核心数学（圆弧三次贝塞尔逼近）
# =============================================================================
def fillet_corner(A, P, B, radius):
    """
    计算 P 处的圆角：P1/P2 为圆弧端点，H1/H2 为圆弧内侧手柄，
    hl1/hr2 为沿原边方向的直线侧手柄。
    返回 (P1, H1, P2, H2, hl1, hr2) 或 None。
    """
    dA = A - P;  lA = dA.length
    dB = B - P;  lB = dB.length
    if lA < 1e-9 or lB < 1e-9:
        return None
    dA = dA / lA;  dB = dB / lB
    r = min(radius, lA * 0.5, lB * 0.5)
    if r <= 1e-9:
        return None
    P1 = P + dA * r
    P2 = P + dB * r
    # 圆弧精确公式：k = 4/3 * tan(θ/4)，θ = π - α
    dot = max(-1.0, min(1.0, dA.x*dB.x + dA.y*dB.y + dA.z*dB.z))
    alpha = math.acos(dot)
    theta = math.pi - alpha
    if alpha > 1e-6 and theta > 1e-6:
        k = (4.0/3.0) * math.tan(theta/4.0) * r * math.tan(alpha/2.0)
    else:
        k = r * (2.0/3.0)
    H1 = P1 + (P - P1) * (k / max(r, 1e-9))
    H2 = P2 + (P - P2) * (k / max(r, 1e-9))
    # 直线侧手柄（沿原边 1/3 处保持进出线平直）
    hl1 = P1 + dA * (lA - r) / 3.0
    hr2 = P2 + dB * (lB - r) / 3.0
    return P1, H1, P2, H2, hl1, hr2


# =============================================================================
# 快照 / 还原（在 OBJECT 模式下调用）
# =============================================================================
def _snapshot(curve):
    data = []
    for sp in curve.splines:
        if sp.type == 'BEZIER':
            pts = [{'co': tuple(bp.co),
                    'hl': tuple(bp.handle_left),
                    'hr': tuple(bp.handle_right),
                    'tl': bp.handle_left_type,
                    'tr': bp.handle_right_type,
                    'sel': bp.select_control_point}
                   for bp in sp.bezier_points]
            data.append({'type': 'BEZIER', 'pts': pts,
                         'cyclic': sp.use_cyclic_u, 'res': sp.resolution_u})
        elif sp.type == 'POLY':
            pts = [{'co': tuple(p.co), 'sel': p.select} for p in sp.points]
            data.append({'type': 'POLY', 'pts': pts, 'cyclic': sp.use_cyclic_u})
    return data


def _restore(curve, data):
    while curve.splines:
        curve.splines.remove(curve.splines[0])
    for sd in data:
        if sd['type'] == 'BEZIER':
            sp = curve.splines.new('BEZIER')
            sp.bezier_points.add(len(sd['pts']) - 1)
            for bp, d in zip(sp.bezier_points, sd['pts']):
                bp.co = d['co']
                bp.handle_left_type = 'FREE'; bp.handle_right_type = 'FREE'
                bp.handle_left = d['hl']; bp.handle_right = d['hr']
                bp.handle_left_type = d['tl']; bp.handle_right_type = d['tr']
                bp.select_control_point = d['sel']
            sp.use_cyclic_u = sd['cyclic']; sp.resolution_u = sd['res']
        elif sd['type'] == 'POLY':
            sp = curve.splines.new('POLY')
            sp.points.add(len(sd['pts']) - 1)
            for pt, d in zip(sp.points, sd['pts']):
                pt.co = d['co']; pt.select = d['sel']
            sp.use_cyclic_u = sd['cyclic']


# =============================================================================
# 倒角应用（在 OBJECT 模式下调用）
# =============================================================================
def _apply_bevel(curve, snap, radius, segments):
    _restore(curve, snap)
    for sp in list(curve.splines):
        if sp.type == 'BEZIER':
            _bevel_bezier(curve, sp, radius, segments)
        elif sp.type == 'POLY':
            _bevel_poly(curve, sp, radius, segments)


def _bevel_bezier(curve, sp, radius, segments):
    pts = [{'co': Vector(bp.co[:]),
            'hl': Vector(bp.handle_left[:]),
            'hr': Vector(bp.handle_right[:]),
            'tl': bp.handle_left_type,
            'tr': bp.handle_right_type,
            'sel': bp.select_control_point}
           for bp in sp.bezier_points]
    n = len(pts)
    cyclic = sp.use_cyclic_u
    if n < 3 and not (cyclic and n >= 3):
        return

    def nb(i, off):
        j = i + off
        if cyclic: return pts[j % n]
        return pts[j] if 0 <= j < n else None

    new_pts = []
    changed = False
    for i, p in enumerate(pts):
        a = nb(i, -1); b = nb(i, +1)
        if p['sel'] and a and b:
            res = fillet_corner(a['co'], p['co'], b['co'], radius)
            if res:
                P1, H1, P2, H2, hl1, hr2 = res
                if segments <= 1:
                    new_pts.append({'co': P1, 'hl': hl1, 'hr': H1, 'tl': 'FREE', 'tr': 'FREE', 'sel': True})
                    new_pts.append({'co': P2, 'hl': H2, 'hr': hr2, 'tl': 'FREE', 'tr': 'FREE', 'sel': True})
                else:
                    # De Casteljau 分割圆弧为 segments 段
                    segs = _split_into_n(P1, H1, H2, P2, segments)
                    for si, seg in enumerate(segs):
                        sp0, sc1, sc2, sp1 = seg
                        left_hl = hl1 if si == 0 else segs[si-1][2]
                        if si == 0:
                            new_pts.append({'co': sp0, 'hl': hl1, 'hr': sc1,
                                            'tl': 'FREE', 'tr': 'FREE', 'sel': True})
                        if si < len(segs) - 1:
                            new_pts.append({'co': sp1, 'hl': sc2, 'hr': segs[si+1][1],
                                            'tl': 'FREE', 'tr': 'FREE', 'sel': True})
                        else:
                            new_pts.append({'co': sp1, 'hl': sc2, 'hr': hr2,
                                            'tl': 'FREE', 'tr': 'FREE', 'sel': True})
                changed = True
                continue
        new_pts.append(p)

    if not changed:
        return
    sp_new = curve.splines.new('BEZIER')
    sp_new.bezier_points.add(len(new_pts) - 1)
    for bp, d in zip(sp_new.bezier_points, new_pts):
        bp.co = d['co']
        bp.handle_left_type = 'FREE'; bp.handle_right_type = 'FREE'
        bp.handle_left = d['hl']; bp.handle_right = d['hr']
        bp.handle_left_type = d['tl']; bp.handle_right_type = d['tr']
        bp.select_control_point = d['sel']
    sp_new.use_cyclic_u = cyclic
    sp_new.resolution_u = sp.resolution_u
    curve.splines.remove(sp)


def _bevel_poly(curve, sp, radius, segments):
    pts = [{'co': Vector(p.co[:3]), 'sel': p.select} for p in sp.points]
    n = len(pts); cyclic = sp.use_cyclic_u
    if n < 3: return
    def nb(i, off):
        j = i + off
        if cyclic: return pts[j % n]
        return pts[j] if 0 <= j < n else None
    new_pts = []; changed = False
    for i, p in enumerate(pts):
        a = nb(i,-1); b = nb(i,+1)
        if p['sel'] and a and b:
            res = fillet_corner(a['co'], p['co'], b['co'], radius)
            if res:
                P1, _, P2, _, _, _ = res
                new_pts.append({'co': P1, 'sel': True})
                new_pts.append({'co': P2, 'sel': True})
                changed = True; continue
        new_pts.append(p)
    if not changed: return
    sp_new = curve.splines.new('POLY')
    sp_new.points.add(len(new_pts) - 1)
    for pt, d in zip(sp_new.points, new_pts):
        co = d['co']; pt.co = (co.x, co.y, co.z, 1.0); pt.select = d['sel']
    sp_new.use_cyclic_u = cyclic
    curve.splines.remove(sp)


# =============================================================================
# 算子（交互式模态）
# =============================================================================
class QOPS_OT_curve_bevel(bpy.types.Operator):
    """曲线顶点倒角：拖动鼠标调半径，滚轮调段数，LMB/Enter确认，RMB/Esc取消"""
    bl_idname  = "qops.curve_bevel"
    bl_label   = "曲线倒角"
    bl_options = {'REGISTER', 'UNDO'}

    radius: bpy.props.FloatProperty(
        name="半径", default=0.1, min=0.0001, soft_max=10.0, step=1, precision=4)
    segments: bpy.props.IntProperty(
        name="段数", default=1, min=1, max=16)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'CURVE'
                and context.mode == 'EDIT_CURVE')

    def invoke(self, context, event):
        obj = context.active_object
        # 切 OBJECT 模式拍快照
        bpy.ops.object.mode_set(mode='OBJECT')
        self._snap  = _snapshot(obj.data)
        self._init_x = event.mouse_x
        self._init_r = self.radius
        # 初始倒角预览
        _apply_bevel(obj.data, self._snap, self.radius, self.segments)
        bpy.ops.object.mode_set(mode='EDIT')
        self._set_header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            dx = event.mouse_x - self._init_x
            self.radius = max(0.0001, self._init_r + dx * 0.002)
            self._update(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELUPMOUSE':
            self.segments = min(16, self.segments + 1)
            self._update(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELDOWNMOUSE':
            self.segments = max(1, self.segments - 1)
            self._update(context)
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            context.area.header_text_set(None)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            context.area.header_text_set(None)
            bpy.ops.object.mode_set(mode='OBJECT')
            _restore(context.active_object.data, self._snap)
            bpy.ops.object.mode_set(mode='EDIT')
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        """F9 redo。"""
        obj = context.active_object
        was_edit = (context.mode == 'EDIT_CURVE')
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')
        if hasattr(self, '_snap'):
            _apply_bevel(obj.data, self._snap, self.radius, self.segments)
        else:
            snap = _snapshot(obj.data)
            _apply_bevel(obj.data, snap, self.radius, self.segments)
        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}

    def _update(self, context):
        obj = context.active_object
        bpy.ops.object.mode_set(mode='OBJECT')
        _apply_bevel(obj.data, self._snap, self.radius, self.segments)
        bpy.ops.object.mode_set(mode='EDIT')
        self._set_header(context)
        context.area.tag_redraw()

    def _set_header(self, context):
        context.area.header_text_set(
            "曲线倒角  半径: %.4f   段数: %d   "
            "← → 调半径   滚轮调段数   LMB/Enter 确认   RMB/Esc 取消"
            % (self.radius, self.segments))


def _curve_context_menu(self, context):
    self.layout.separator()
    self.layout.operator(QOPS_OT_curve_bevel.bl_idname, text="曲线倒角", icon='MOD_BEVEL')


classes = (QOPS_OT_curve_bevel,)


def register_extra():
    try:
        bpy.types.VIEW3D_MT_edit_curve_context_menu.append(_curve_context_menu)
    except Exception:
        pass


def unregister_extra():
    try:
        bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(_curve_context_menu)
    except Exception:
        pass
