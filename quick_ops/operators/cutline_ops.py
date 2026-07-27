# -*- coding: utf-8 -*-
"""
PS 式切割线工具 v3
==================
可持续编辑的切割线会话（编辑模式）。绘制/擦除/吸附/变换/复制/贝塞尔锚点编辑，
最后 Enter 一次性刀具投影切割。

会话交互：
- 左键            按当前子工具绘制（贝塞尔线画完后锚点仍可编辑）
- Alt+左键拖拽     擦除选区内的切割线（闭环被剪开）；贝塞尔模式下 Alt+点击曲线=插入控制点
- Shift           吸附已有开放线端点，首尾相连自动合并/闭合
- Shift+D         复制鼠标附近的线段，移动后左键放置（右键取消）
- G / S / R       整体 移动/缩放/旋转（左键/Enter 确认，右键/ESC 取消）
- Ctrl+D          呼出子工具饼菜单（会话中也可切换）
- 退格            绘制中删上一点；空闲时删除最近一段线
- X               有选中锚点=删除锚点；否则清空全部
- Enter / 空格    确认切割
- 右键 / ESC      逐级取消（当前动作 -> 取消选择 -> 退出）

贝塞尔（可中断、可编辑）：
- 绘制：单击=角点，按下拖拽=平滑点；点击起点闭合；Enter 结束（开放线）
- 编辑：**按住 Ctrl 激活**（锚点高亮）——Ctrl+点击锚点/手柄拖动；
  Ctrl+点击曲线插入锚点；G 移动选中锚点；X/Del 删除锚点；Ctrl+点空白取消选择
"""

import math
import os

import bpy
from mathutils import Vector
from mathutils.geometry import interpolate_bezier
from bpy_extras import view3d_utils

from ..draw_utils import (
    get_shader_2d,
    draw_line_strip_2d,
    draw_points_2d,
    draw_tris_2d,
    reset_state,
)

MODE_ITEMS = [
    ('RECT', "方框", "拖拽绘制矩形切割线"),
    ('CIRCLE', "圆形", "以按下点为圆心拖拽半径"),
    ('POLY', "折线", "逐点点击；点击起点闭合；Enter 结束为开放线"),
    ('LASSO', "套索", "按住左键自由绘制，松开闭合"),
    ('BEZIER', "贝塞尔", "单击角点/按拖平滑点；画完可随时点锚点编辑"),
    ('WAND', "魔棒", "点击参考图色块，按容差自动生成切割轮廓(容差在工具设置调)"),
]

RESAMPLE_STEP = 6.0
SNAP_DIST = 12.0
MERGE_EPS = 4.0
CLOSE_DIST = 12.0
PICK_DIST = 12.0
BEZ_RES = 16

_COL_DONE_CLOSED = (0.30, 1.00, 0.45, 1.0)
_COL_DONE_OPEN = (0.35, 0.75, 1.00, 1.0)
_COL_ACTIVE = (1.00, 0.62, 0.15, 1.0)
_COL_ERASE = (1.00, 0.25, 0.25, 1.0)
_COL_POINT = (1.00, 1.00, 1.00, 1.0)
_COL_HANDLE = (0.75, 0.75, 0.75, 0.9)
_COL_ANCHOR = (1.00, 0.80, 0.10, 1.0)      # Ctrl 激活时
_COL_ANCHOR_DIM = (1.00, 0.85, 0.30, 0.30)  # 未激活时弱化
_COL_SEL = (1.00, 0.30, 0.30, 1.0)


# =============================================================================
# 数据与纯几何
# =============================================================================
class _Stroke:
    __slots__ = ("points", "closed", "anchors")

    def __init__(self, points, closed, anchors=None):
        self.points = points
        self.closed = closed
        self.anchors = anchors  # 贝塞尔锚点 [[co,hp,hn],...]；None=普通折线


def _rect_points(a, b):
    return [Vector((a.x, a.y)), Vector((b.x, a.y)),
            Vector((b.x, b.y)), Vector((a.x, b.y))]


def _circle_points(c, r, segs=64):
    return [Vector((c.x + r * math.cos(2 * math.pi * i / segs),
                    c.y + r * math.sin(2 * math.pi * i / segs)))
            for i in range(segs)]


def _resample(points, closed, step=RESAMPLE_STEP):
    if len(points) < 2:
        return [p.copy() for p in points]
    pts = list(points) + ([points[0]] if closed else [])
    out = [pts[0].copy()]
    carry = step
    for a, b in zip(pts, pts[1:]):
        seg = b - a
        L = seg.length
        if L < 1e-9:
            continue
        pos = carry
        while pos < L:
            out.append(a + seg * (pos / L))
            pos += step
        carry = pos - L
    if not closed and (out[-1] - pts[-1]).length > 1e-6:
        out.append(pts[-1].copy())
    return out


def _point_in_poly(pt, poly):
    x, y = pt.x, pt.y
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i].x, poly[i].y
        xj, yj = poly[j].x, poly[j].y
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / ((yj - yi) + 1e-12) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def _erase_strokes(strokes, region):
    if len(region) < 3:
        return strokes
    result = []
    for s in strokes:
        mask = [_point_in_poly(p, region) for p in s.points]
        if not any(mask):
            result.append(s)
            continue
        pts = s.points
        n = len(pts)
        if s.closed:
            start = mask.index(True)
            order = [(start + 1 + i) % n for i in range(n)]
        else:
            order = list(range(n))
        runs, cur = [], []
        for i in order:
            if mask[i]:
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
            else:
                cur.append(pts[i].copy())
        if len(cur) >= 2:
            runs.append(cur)
        for r in runs:
            result.append(_Stroke(r, False))  # 擦除后退化为折线
    return result




def _flip_anchor(a):
    """翻转一个锚点的左右手柄（用于反向合并时）。"""
    return [a[0], a[2], a[1]]


def _merge_anchors_lists(anch_a, anch_b, flip_a=False, flip_b=False):
    """合并两段锚点列表。任一为空则返回 None。flip=True 时翻转顺序并交换手柄。"""
    if not anch_a or not anch_b:
        return None
    aa = [_flip_anchor(x) for x in reversed(anch_a)] if flip_a else list(anch_a)
    ab = [_flip_anchor(x) for x in reversed(anch_b)] if flip_b else list(anch_b)
    return aa + ab[1:]


def _merge_open_strokes(strokes, new, eps=MERGE_EPS):
    """返回 (strokes, new, merged)。merged=True 时 new 已与他线合并(退化折线)。"""
    merged_any = False
    changed = True
    while changed and not new.closed:
        changed = False
        for other in strokes:
            if other.closed:
                continue
            a0, a1 = new.points[0], new.points[-1]
            b0, b1 = other.points[0], other.points[-1]
            if (b1 - a0).length <= eps:
                # other的末端 → new的首端
                new.points = other.points + new.points[1:]
                new.anchors = _merge_anchors_lists(
                    other.anchors, new.anchors, False, False)
            elif (b0 - a0).length <= eps:
                # other的首端(翻转后末端) → new的首端
                new.points = list(reversed(other.points)) + new.points[1:]
                new.anchors = _merge_anchors_lists(
                    other.anchors, new.anchors, True, False)
            elif (b0 - a1).length <= eps:
                # new的末端 → other的首端
                new.points = new.points + other.points[1:]
                new.anchors = _merge_anchors_lists(
                    new.anchors, other.anchors, False, False)
            elif (b1 - a1).length <= eps:
                # new的末端 → other的末端(翻转)
                new.points = new.points + list(reversed(other.points))[1:]
                new.anchors = _merge_anchors_lists(
                    new.anchors, other.anchors, False, True)
            else:
                continue
            strokes.remove(other)
            changed = True
            merged_any = True
            break
        if len(new.points) >= 3 and (new.points[0] - new.points[-1]).length <= eps:
            new.points = new.points[:-1]
            new.closed = True
    return strokes, new, merged_any


def _sample_bezier(anchors, closed, res=BEZ_RES):
    if len(anchors) < 2:
        return [a[0].copy() for a in anchors]
    pairs = list(zip(anchors, anchors[1:]))
    if closed:
        pairs.append((anchors[-1], anchors[0]))
    pts = []
    for a, b in pairs:
        seg = interpolate_bezier(a[0], a[2], b[1], b[0], res)
        seg = [Vector((v[0], v[1])) for v in seg]
        pts += seg if not pts else seg[1:]
    if closed and len(pts) > 1:
        pts = pts[:-1]
    return pts


def _thin_points(points, min_dist=12.0, max_count=120):
    """稀疏化闭合轮廓点：相邻点至少间隔 min_dist，且总数不超过 max_count。"""
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    for p in points[1:]:
        if (p - out[-1]).length >= min_dist:
            out.append(p)
    # 首尾过近时去掉最后一个
    if len(out) >= 3 and (out[0] - out[-1]).length < min_dist * 0.5:
        out.pop()
    while len(out) > max_count:
        out = out[::2]
    return out


def _catmull_anchors(points, closed=True):
    """把轮廓点拟合成平滑贝塞尔锚点（Catmull-Rom 切线求对称手柄）。"""
    n = len(points)
    if n < 3:
        return None
    anchors = []
    for i in range(n):
        p = points[i]
        prv = points[(i - 1) % n]
        nxt = points[(i + 1) % n]
        t = (nxt - prv) * (1.0 / 6.0)
        anchors.append([p.copy(), p - t, p + t])
    return anchors


def _copy_stroke(s):
    anchors = None
    if s.anchors:
        anchors = [[a[0].copy(), a[1].copy(), a[2].copy()] for a in s.anchors]
    return _Stroke([p.copy() for p in s.points], s.closed, anchors)


# =============================================================================
# 模态算子
# =============================================================================
class QOPS_OT_draw_cut(bpy.types.Operator):
    """切割线会话：左键绘制 Alt擦除 Shift吸附 Shift+D复制 G/S/R变换 Enter切割"""
    bl_idname = "qops.draw_cut"
    bl_label = "绘制切割线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and context.area is not None
                and context.area.type == 'VIEW_3D')

    # ---------- 生命周期 ----------
    def invoke(self, context, event):
        self.strokes = []
        self.cur = []
        self.anchor = None
        self.bz = []
        self.bz_drag = False
        self.erase_pts = []
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.state = 'IDLE'
        self.sel = None            # 活动锚点 (stroke, anchor_idx)
        self.sel_pts = []          # 多选锚点 [(stroke, idx), ...]
        self.drag_part = None      # 'CO'/'HP'/'HN'
        self.drag_moved = False
        self.box_start = None      # Ctrl 框选起点
        self.multi_orig = None     # 多选移动备份 [(stroke,idx,(co,hp,hn)),...]
        self.tr_kind = None
        self.tr_m0 = None
        self.tr_center = None
        self.tr_orig = None
        self.dup_stroke = None
        self.dup_orig = None
        self.ctrl_now = False
        self.wand_hover = None      # 当前悬停颜色 (r,g,b)
        self.wand_last = None       # 上次吸取颜色
        self._wand_sample_pos = None
        self._cursor_cur = None
        self._shader = get_shader_2d()
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_cb, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)

        self._on_press_idle(context, event)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        h = getattr(self, "_handle", None)
        if h is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
            except Exception:
                pass
            self._handle = None
        if context.area:
            context.area.tag_redraw()

    def cancel(self, context):
        self._finish(context)

    # ---------- 小工具 ----------
    def _mode(self, context):
        return getattr(context.scene, "qops_cut_mode", 'RECT')

    def _snap(self, m, enabled):
        if not enabled:
            return m.copy()
        best, bd = None, SNAP_DIST
        for s in self.strokes:
            if s.closed:
                continue
            for p in (s.points[0], s.points[-1]):
                d = (m - p).length
                if d < bd:
                    bd, best = d, p
        return best.copy() if best is not None else m.copy()

    def _pick_anchor(self, m):
        """优先选中已选锚点的手柄，其次任意贝塞尔锚点。"""
        if self.sel is not None:
            s, i = self.sel
            if s in self.strokes and s.anchors and i < len(s.anchors):
                a = s.anchors[i]
                for part, pt in (('HN', a[2]), ('HP', a[1])):
                    if (m - pt).length < PICK_DIST:
                        return (s, i, part)
        best, bd = None, PICK_DIST
        for s in self.strokes:
            if not s.anchors:
                continue
            for i, a in enumerate(s.anchors):
                d = (m - a[0]).length
                if d < bd:
                    bd, best = d, (s, i, 'CO')
        return best

    def _pick_stroke(self, m, maxdist=30.0):
        best, bd = None, maxdist
        for s in self.strokes:
            for p in s.points:
                d = (m - p).length
                if d < bd:
                    bd, best = d, s
        return best

    def _insert_anchor(self, m):
        """Ctrl+点击：在最近的贝塞尔曲线上插入锚点。"""
        best = None  # (stroke, sample_idx, dist)
        for s in self.strokes:
            if not s.anchors:
                continue
            for idx, p in enumerate(s.points):
                d = (m - p).length
                if best is None or d < best[2]:
                    best = (s, idx, d)
        if best is None or best[2] > PICK_DIST:
            return None
        s, idx, _ = best
        nseg = len(s.anchors) - (0 if s.closed else 1)
        if nseg <= 0:
            return None
        per = BEZ_RES - 1
        seg = min(idx // per, nseg - 1)
        t = (idx - seg * per) / float(per)
        t = min(max(t, 0.05), 0.95)
        a = s.anchors[seg]
        b = s.anchors[(seg + 1) % len(s.anchors)]
        # De Casteljau 分割：在 t 处插入锚点，曲线形状严格不变
        P0, C1, C2, P3 = a[0], a[2], b[1], b[0]

        def lp(u, v, tt):
            return u + (v - u) * tt

        Q0 = lp(P0, C1, t)
        Q1 = lp(C1, C2, t)
        Q2 = lp(C2, P3, t)
        R0 = lp(Q0, Q1, t)
        R1 = lp(Q1, Q2, t)
        Spt = lp(R0, R1, t)
        a[2] = Q0
        b[1] = Q2
        s.anchors.insert(seg + 1, [Spt, R0, R1])
        s.points = _sample_bezier(s.anchors, s.closed)
        return (s, seg + 1)

    def _resample_sel_stroke(self):
        if self.sel is None:
            return
        s, _ = self.sel
        if s.anchors:
            s.points = _sample_bezier(s.anchors, s.closed)

    def _add_stroke(self, pts, closed, anchors=None):
        if anchors is not None:
            pts = _sample_bezier(anchors, closed)
        else:
            pts = _resample(pts, closed)
        if len(pts) < 2:
            return
        s = _Stroke(pts, closed, anchors)
        if not s.closed:
            self.strokes, s, merged = _merge_open_strokes(self.strokes, s)
            # 合并后不清空 anchors——_merge_anchors_lists 已正确拼接
            # 若合并后 anchors 有效则重新采样保持 points/anchors 一致
            if s.anchors:
                s.points = _sample_bezier(s.anchors, s.closed)
            if s.closed and s.anchors:    # 首尾闭合时确保采样正确
                s.points = _sample_bezier(s.anchors, True)
        self.strokes.append(s)

    def _all_points(self):
        for s in self.strokes:
            for p in s.points:
                yield p

    # ---------- IDLE 左键按下分发 ----------
    def _on_press_idle(self, context, event):
        m = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.alt:
            # 贝塞尔模式：Alt+点击曲线 = 在该处插入控制点；点不到曲线则照常擦除
            if self._mode(context) == 'BEZIER':
                r = self._insert_anchor(m)
                if r is not None:
                    self.sel = r
                    self.sel_pts = [r]
                    self.tr_m0 = m.copy()
                    self.multi_orig = self._snapshot_sel()
                    self.drag_part = 'CO'
                    self.drag_moved = False
                    self.state = 'BEZ_DRAG'
                    return
            self.erase_pts = [m.copy()]
            self.state = 'ERASE'
            return
        if event.ctrl:
            # Ctrl = 锚点编辑：点锚点(可多选整体拖动)/手柄；点曲线插点；拖空白框选
            hit = self._pick_anchor(m)
            if hit is not None:
                s_i = (hit[0], hit[1])
                if hit[2] == 'CO':
                    if s_i not in self.sel_pts:
                        if event.shift:
                            self.sel_pts.append(s_i)
                        else:
                            self.sel_pts = [s_i]
                    self.sel = s_i
                    self.tr_m0 = m.copy()
                    self.multi_orig = self._snapshot_sel()
                    self.drag_part = 'CO'
                else:
                    self.sel = s_i
                    if s_i not in self.sel_pts:
                        self.sel_pts = [s_i]
                    self.drag_part = hit[2]
                self.drag_moved = False
                self.state = 'BEZ_DRAG'
                return
            r = self._insert_anchor(m)
            if r is not None:
                self.sel = r
                self.sel_pts = [r]
                self.tr_m0 = m.copy()
                self.multi_orig = self._snapshot_sel()
                self.drag_part = 'CO'
                self.drag_moved = False
                self.state = 'BEZ_DRAG'
                return
            # Ctrl 拖空白 = 框选锚点
            self.box_start = m.copy()
            self.state = 'BOX'
            return
        # 普通点击：一律开始绘制（锚点编辑请按住 Ctrl）
        mode = self._mode(context)
        if mode == 'WAND':
            self._wand_click(context, m)
            return
        p0 = self._snap(m, event.shift)
        if mode == 'RECT':
            self.anchor = p0
            self.state = 'DRAG_RECT'
        elif mode == 'CIRCLE':
            self.anchor = p0
            self.state = 'DRAG_CIRCLE'
        elif mode == 'LASSO':
            self.cur = [p0]
            self.state = 'DRAG_LASSO'
        elif mode == 'POLY':
            self.cur = [p0]
            self.state = 'POLY'
        else:  # BEZIER
            self.bz = [[p0, p0.copy(), p0.copy()]]
            self.bz_drag = True
            self.state = 'BEZIER'

    def _update_cursor(self, context):
        """魔棒模式空闲时显示吸管光标。"""
        want = None
        try:
            if (self.state == 'IDLE'
                    and self._mode(context) == 'WAND'):
                want = 'EYEDROPPER'
        except Exception:
            want = None
        if want == self._cursor_cur:
            return
        try:
            if want:
                context.window.cursor_modal_set(want)
            else:
                context.window.cursor_modal_restore()
            self._cursor_cur = want
        except Exception:
            pass

    def _wand_sample(self, context, m):
        """悬停取色（节流：移动>6px 才重新采样）。"""
        if (self._wand_sample_pos is not None
                and (m - self._wand_sample_pos).length < 6.0):
            return
        self._wand_sample_pos = m.copy()
        try:
            from . import wand_ops
            self.wand_hover = wand_ops.sample_color(context, (m.x, m.y))
        except Exception:
            self.wand_hover = None

    def _wand_click(self, context, m):
        """魔棒：点击参考图色块 -> 生成闭合切割线加入会话。"""
        try:
            from . import wand_ops
        except Exception as e:
            self.report({'ERROR'}, "魔棒模块加载失败：%s" % e)
            return
        tol = float(getattr(context.scene, "qops_wand_tolerance", 0.15))
        inv = bool(getattr(context.scene, "qops_wand_invert", False))
        try:
            pts, err = wand_ops.wand_screen_contour(context, (m.x, m.y), tol,
                                                    invert=inv)
        except Exception as e:
            self.report({'ERROR'}, "魔棒失败：%s" % e)
            return
        if err is not None:
            self.report({'WARNING'}, err)
            return
        if self.wand_hover is not None:
            self.wand_last = self.wand_hover
        if bool(getattr(context.scene, "qops_wand_smooth", True)):
            thin = _thin_points(pts)
            anchors = _catmull_anchors(thin, True)
            if anchors is not None:
                self._add_stroke(None, True, anchors=anchors)
                self.report({'INFO'},
                            "魔棒：平滑轮廓(%d锚点)。Ctrl可编辑锚点 · Enter切割"
                            % len(anchors))
                return
        self._add_stroke(pts, True)
        self.report({'INFO'},
                    "魔棒：已生成轮廓(%d点)。Enter切割 · 退格删除 · Alt擦除修边"
                    % len(pts))

    # ---------- 交互 ----------
    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        m = Vector((event.mouse_region_x, event.mouse_region_y))
        st = self.state
        if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}:
            self.ctrl_now = (event.value == 'PRESS')
        else:
            self.ctrl_now = bool(event.ctrl)
        self._update_cursor(context)

        if st == 'IDLE' and context.region is not None:
            if (m.x < 0 or m.y < 0
                    or m.x > context.region.width
                    or m.y > context.region.height):
                return {'PASS_THROUGH'}

        # ---- 鼠标移动 ----
        if event.type == 'MOUSEMOVE':
            self.mouse = m
            if st == 'IDLE' and self._mode(context) == 'WAND':
                self._wand_sample(context, m)
            if st == 'DRAG_LASSO':
                if not self.cur or (m - self.cur[-1]).length > 4.0:
                    self.cur.append(m.copy())
            elif st == 'ERASE':
                if not self.erase_pts or (m - self.erase_pts[-1]).length > 4.0:
                    self.erase_pts.append(m.copy())
            elif st == 'BEZIER' and self.bz_drag and self.bz:
                a = self.bz[-1]
                a[2] = m.copy()
                a[1] = a[0] * 2.0 - m
            elif st == 'BEZ_DRAG' and self.sel is not None:
                self.drag_moved = True
                if self.drag_part == 'CO':
                    self._apply_multi_offset(m - self.tr_m0)
                else:
                    s, i = self.sel
                    a = s.anchors[i]
                    if self.drag_part == 'HN':
                        a[2] = m.copy()
                        a[1] = a[0] * 2.0 - m
                    else:  # HP
                        a[1] = m.copy()
                        a[2] = a[0] * 2.0 - m
                    self._resample_sel_stroke()
            elif st == 'BEZ_GRAB':
                self._apply_multi_offset(m - self.tr_m0)
            elif st == 'TRANSFORM':
                self._apply_transform(m)
            elif st == 'DUP' and self.dup_stroke is not None:
                off = m - self.tr_m0
                s = self.dup_stroke
                s.points = [p + off for p in self.dup_orig[0]]
                if self.dup_orig[1] is not None:
                    s.anchors = [[a[0] + off, a[1] + off, a[2] + off]
                                 for a in self.dup_orig[1]]
            return {'RUNNING_MODAL'}

        # ---- 左键 ----
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if st == 'IDLE':
                    self._on_press_idle(context, event)
                elif st == 'POLY':
                    if (len(self.cur) >= 3
                            and (m - self.cur[0]).length < CLOSE_DIST):
                        self._add_stroke(self.cur, True)
                        self.cur = []
                        self.state = 'IDLE'
                    else:
                        self.cur.append(self._snap(m, event.shift))
                elif st == 'BEZIER':
                    if (len(self.bz) >= 2
                            and (m - self.bz[0][0]).length < CLOSE_DIST):
                        self._add_stroke(None, True, anchors=self.bz)
                        self.bz = []
                        self.state = 'IDLE'
                    else:
                        p0 = self._snap(m, event.shift)
                        self.bz.append([p0, p0.copy(), p0.copy()])
                        self.bz_drag = True
                elif st in {'TRANSFORM', 'BEZ_GRAB', 'DUP'}:
                    self.state = 'IDLE'   # 确认
                return {'RUNNING_MODAL'}
            else:  # RELEASE
                if st == 'DRAG_RECT':
                    if (m - self.anchor).length >= 4.0:
                        self._add_stroke(_rect_points(self.anchor, m), True)
                    self.anchor = None
                    self.state = 'IDLE'
                elif st == 'DRAG_CIRCLE':
                    r = (m - self.anchor).length
                    if r >= 4.0:
                        self._add_stroke(_circle_points(self.anchor, r), True)
                    self.anchor = None
                    self.state = 'IDLE'
                elif st == 'DRAG_LASSO':
                    if len(self.cur) >= 3:
                        self._add_stroke(self.cur, True)
                    self.cur = []
                    self.state = 'IDLE'
                elif st == 'ERASE':
                    self.strokes = _erase_strokes(self.strokes, self.erase_pts)
                    self.erase_pts = []
                    self.sel = None
                    self.sel_pts = []
                    self.state = 'IDLE'
                elif st == 'BEZIER':
                    self.bz_drag = False
                elif st == 'BEZ_DRAG':
                    self.state = 'IDLE'   # 结束拖动，保留选择
                elif st == 'BOX' and self.box_start is not None:
                    if (m - self.box_start).length < 4.0:
                        self.sel_pts = []
                        self.sel = None
                    else:
                        x0, x1 = sorted((self.box_start.x, m.x))
                        y0, y1 = sorted((self.box_start.y, m.y))
                        picked = [(s_, i_)
                                  for s_ in self.strokes if s_.anchors
                                  for i_, a_ in enumerate(s_.anchors)
                                  if x0 <= a_[0].x <= x1 and y0 <= a_[0].y <= y1]
                        if event.shift:
                            for it in picked:
                                if it not in self.sel_pts:
                                    self.sel_pts.append(it)
                        else:
                            self.sel_pts = picked
                        self.sel = self.sel_pts[-1] if self.sel_pts else None
                    self.box_start = None
                    self.state = 'IDLE'
                return {'RUNNING_MODAL'}

        # ---- Shift+D 复制 ----
        if (event.type == 'D' and event.value == 'PRESS'
                and event.shift and not event.ctrl and st == 'IDLE'):
            if self.strokes:
                src = self._pick_stroke(m) or self.strokes[-1]
                cp = _copy_stroke(src)
                self.strokes.append(cp)
                self.dup_stroke = cp
                self.dup_orig = (
                    [p.copy() for p in cp.points],
                    ([[a[0].copy(), a[1].copy(), a[2].copy()]
                      for a in cp.anchors] if cp.anchors else None),
                )
                self.tr_m0 = m.copy()
                self.state = 'DUP'
            return {'RUNNING_MODAL'}

        # ---- Ctrl+D 子工具饼菜单 ----
        if (event.type == 'D' and event.value == 'PRESS'
                and event.ctrl and st == 'IDLE'):
            try:
                bpy.ops.wm.call_panel(name="QOPS_MT_cut_pie", keep_open=False)
            except Exception:
                pass
            return {'RUNNING_MODAL'}

        # ---- G/S/R ----
        if st == 'IDLE' and event.value == 'PRESS' and event.type in {'G', 'S', 'R'}:
            if event.type == 'G' and self.sel_pts:
                self.tr_m0 = m.copy()
                self.multi_orig = self._snapshot_sel()
                self.state = 'BEZ_GRAB'
            elif self.strokes:
                self._start_transform(event.type, m)
            return {'RUNNING_MODAL'}

        # ---- 退格 ----
        if event.type == 'BACK_SPACE' and event.value == 'PRESS':
            if st == 'POLY' and self.cur:
                self.cur.pop()
                if not self.cur:
                    self.state = 'IDLE'
            elif st == 'BEZIER' and self.bz:
                self.bz.pop()
                self.bz_drag = False
                if not self.bz:
                    self.state = 'IDLE'
            elif st == 'IDLE' and self.strokes:
                if self.sel is not None and self.sel[0] is self.strokes[-1]:
                    self.sel = None
                self.strokes.pop()
            return {'RUNNING_MODAL'}

        # ---- X / Delete ----
        if event.type in {'X', 'DEL'} and event.value == 'PRESS':
            if st == 'IDLE' and self.sel_pts:
                by = {}
                for (s_, i_) in self.sel_pts:
                    if s_ in self.strokes and s_.anchors:
                        by.setdefault(id(s_), (s_, set()))[1].add(i_)
                for s_, idxs in by.values():
                    for i_ in sorted(idxs, reverse=True):
                        if i_ < len(s_.anchors):
                            s_.anchors.pop(i_)
                    if len(s_.anchors) < 2:
                        if s_ in self.strokes:
                            self.strokes.remove(s_)
                    else:
                        s_.points = _sample_bezier(s_.anchors, s_.closed)
                self.sel = None
                self.sel_pts = []
            elif event.type == 'X':
                self.strokes = []
                self.cur = []
                self.bz = []
                self.erase_pts = []
                self.sel = None
                self.sel_pts = []
                self.state = 'IDLE'
            return {'RUNNING_MODAL'}

        # ---- 确认 ----
        if event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'} and event.value == 'PRESS':
            if st == 'POLY':
                if len(self.cur) >= 2:
                    self._add_stroke(self.cur, False)
                self.cur = []
                self.state = 'IDLE'
            elif st == 'BEZIER':
                if len(self.bz) >= 2:
                    self._add_stroke(None, False, anchors=self.bz)
                self.bz = []
                self.state = 'IDLE'
            elif st in {'TRANSFORM', 'BEZ_GRAB', 'DUP'}:
                self.state = 'IDLE'
            elif st == 'IDLE':
                if self.strokes:
                    return self._commit(context)
            return {'RUNNING_MODAL'}

        # ---- 取消 / 退出 ----
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            if st == 'TRANSFORM':
                self._cancel_transform()
                self.state = 'IDLE'
            elif st == 'BEZ_GRAB':
                self._restore_multi()
                self.state = 'IDLE'
            elif st == 'DUP':
                if self.dup_stroke in self.strokes:
                    self.strokes.remove(self.dup_stroke)
                self.dup_stroke = None
                self.state = 'IDLE'
            elif st in {'POLY', 'BEZIER', 'DRAG_RECT', 'DRAG_CIRCLE',
                        'DRAG_LASSO', 'ERASE', 'BEZ_DRAG', 'BOX'}:
                self.cur = []
                self.bz = []
                self.erase_pts = []
                self.anchor = None
                self.box_start = None
                self.state = 'IDLE'
            else:  # IDLE
                if self.sel is not None or self.sel_pts:
                    self.sel = None
                    self.sel_pts = []
                else:
                    self._finish(context)
                    return {'CANCELLED'}
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    # ---------- 多选锚点辅助 ----------
    def _snapshot_sel(self):
        """备份当前多选锚点，供偏移移动/取消还原。"""
        out = []
        for (st_, i_) in self.sel_pts:
            if st_ in self.strokes and st_.anchors and i_ < len(st_.anchors):
                a = st_.anchors[i_]
                out.append((st_, i_, (a[0].copy(), a[1].copy(), a[2].copy())))
        return out

    def _apply_multi_offset(self, off):
        if not self.multi_orig:
            return
        touched = set()
        for st_, i_, (oc, ohp, ohn) in self.multi_orig:
            if st_ in self.strokes and st_.anchors and i_ < len(st_.anchors):
                a = st_.anchors[i_]
                a[0] = oc + off
                a[1] = ohp + off
                a[2] = ohn + off
                touched.add(id(st_))
        for st_ in self.strokes:
            if id(st_) in touched and st_.anchors:
                st_.points = _sample_bezier(st_.anchors, st_.closed)

    def _restore_multi(self):
        if not self.multi_orig:
            return
        touched = set()
        for st_, i_, (oc, ohp, ohn) in self.multi_orig:
            if st_ in self.strokes and st_.anchors and i_ < len(st_.anchors):
                a = st_.anchors[i_]
                a[0], a[1], a[2] = oc.copy(), ohp.copy(), ohn.copy()
                touched.add(id(st_))
        for st_ in self.strokes:
            if id(st_) in touched and st_.anchors:
                st_.points = _sample_bezier(st_.anchors, st_.closed)

    # ---------- 整体变换 ----------
    def _start_transform(self, kind, m):
        pts = list(self._all_points())
        if not pts:
            return
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        self.tr_center = Vector(((min(xs) + max(xs)) / 2.0,
                                 (min(ys) + max(ys)) / 2.0))
        self.tr_kind = kind
        self.tr_m0 = m.copy()
        self.tr_orig = []
        for s in self.strokes:
            anchors = None
            if s.anchors:
                anchors = [[a[0].copy(), a[1].copy(), a[2].copy()]
                           for a in s.anchors]
            self.tr_orig.append(([p.copy() for p in s.points], anchors))
        self.state = 'TRANSFORM'

    def _apply_transform(self, m):
        if self.tr_kind is None or self.tr_orig is None:
            return
        c = self.tr_center
        if self.tr_kind == 'G':
            off = m - self.tr_m0
            fn = lambda p: p + off
        elif self.tr_kind == 'S':
            d0 = max((self.tr_m0 - c).length, 1e-3)
            fac = (m - c).length / d0
            fn = lambda p: c + (p - c) * fac
        else:  # R
            a0 = math.atan2(self.tr_m0.y - c.y, self.tr_m0.x - c.x)
            a1 = math.atan2(m.y - c.y, m.x - c.x)
            da = a1 - a0
            ca, sa = math.cos(da), math.sin(da)

            def fn(p):
                v = p - c
                return Vector((c.x + v.x * ca - v.y * sa,
                               c.y + v.x * sa + v.y * ca))
        for s, (opts, oanch) in zip(self.strokes, self.tr_orig):
            s.points = [fn(p) for p in opts]
            if oanch is not None:
                s.anchors = [[fn(a[0]), fn(a[1]), fn(a[2])] for a in oanch]

    def _cancel_transform(self):
        if self.tr_orig is not None:
            for s, (opts, oanch) in zip(self.strokes, self.tr_orig):
                s.points = [p.copy() for p in opts]
                if oanch is not None:
                    s.anchors = [[a[0].copy(), a[1].copy(), a[2].copy()]
                                 for a in oanch]
        self.tr_kind = None
        self.tr_orig = None

    # ---------- 确认切割 ----------
    def _commit(self, context):
        strokes = [s for s in self.strokes if len(s.points) >= 2]
        self._finish(context)
        if not strokes:
            self.report({'WARNING'}, "没有可切割的线")
            return {'CANCELLED'}

        region = context.region
        rv3d = context.region_data
        edit_obj = context.edit_object
        if region is None or rv3d is None or edit_obj is None:
            self.report({'ERROR'}, "上下文缺失，无法切割")
            return {'CANCELLED'}

        try:
            mw = edit_obj.matrix_world
            centers = [mw @ Vector((c[0], c[1], c[2])) for c in edit_obj.bound_box]
            depth = sum(centers, Vector((0, 0, 0))) / 8.0
        except Exception:
            depth = edit_obj.matrix_world.translation

        verts, edges = [], []
        for s in strokes:
            base = len(verts)
            pts3 = []
            for p in s.points:
                loc = view3d_utils.region_2d_to_location_3d(
                    region, rv3d, (p.x, p.y), depth)
                if loc is None:
                    self.report({'ERROR'}, "屏幕点无法投影到 3D")
                    return {'CANCELLED'}
                pts3.append(tuple(loc))
            n = len(pts3)
            verts += pts3
            edges += [(base + i, base + i + 1) for i in range(n - 1)]
            if s.closed:
                edges.append((base + n - 1, base))

        me = bpy.data.meshes.new("QOPS_cutline")
        me.from_pydata(verts, edges, [])
        cutter = bpy.data.objects.new("QOPS_cutline", me)
        context.collection.objects.link(cutter)
        try:
            context.view_layer.update()
        except Exception:
            pass
        try:
            cutter.select_set(True)
        except Exception:
            pass

        ok, err = True, ""
        try:
            bpy.ops.mesh.knife_project(
                cut_through=bool(getattr(context.scene, "qops_cut_through", False)))
        except Exception as e:
            ok, err = False, str(e)

        try:
            bpy.data.objects.remove(cutter)
        except Exception:
            pass
        try:
            bpy.data.meshes.remove(me)
        except Exception:
            pass

        if not ok:
            self.report({'ERROR'}, "切割失败：%s" % err)
            return {'CANCELLED'}
        self.report({'INFO'}, "切割完成，可直接选面挤出")
        return {'FINISHED'}

    # ---------- 绘制 ----------
    def _draw_cb(self, context):
        try:
            shader = self._shader
            st = getattr(self, "state", None)

            ctrl = getattr(self, "ctrl_now", False)
            for s in self.strokes:
                col = _COL_DONE_CLOSED if s.closed else _COL_DONE_OPEN
                draw_line_strip_2d(shader, s.points, col, width=2.5,
                                   closed=s.closed)
                if not s.closed and not s.anchors:
                    draw_points_2d(shader, [s.points[0], s.points[-1]],
                                   _COL_POINT, size=7.0)
                if s.anchors:
                    ctrl_or_bez = ctrl or st in {'BEZ_DRAG', 'BEZ_GRAB', 'BOX'}
                    draw_mode = self._mode(context) == 'BEZIER'
                    if ctrl_or_bez or draw_mode:
                        cos = [a[0] for a in s.anchors]
                        draw_points_2d(shader, cos, (0.0, 0.0, 0.0, 0.95),
                                       size=26.0)
                        draw_points_2d(shader, cos, _COL_ANCHOR, size=20.0)
                        sel_ids = {(id(x[0]), x[1])
                                   for x in getattr(self, "sel_pts", [])}
                        sel_cos = [a[0] for i2, a in enumerate(s.anchors)
                                   if (id(s), i2) in sel_ids]
                        if sel_cos:
                            draw_points_2d(shader, sel_cos,
                                           (0.0, 0.0, 0.0, 0.95), size=30.0)
                            draw_points_2d(shader, sel_cos, _COL_SEL, size=23.0)
                    else:
                        cos = [a[0] for a in s.anchors]
                        draw_points_2d(shader, cos, (0.0, 0.0, 0.0, 0.8),
                                       size=13.0)
                        draw_points_2d(shader, cos,
                                       (1.0, 0.85, 0.1, 0.85), size=9.0)

            # 选中锚点 + 手柄（Ctrl 或编辑中才显示）
            if self.sel is not None and (ctrl or st in {'BEZ_DRAG', 'BEZ_GRAB'}):
                s, i = self.sel
                if s in self.strokes and s.anchors and i < len(s.anchors):
                    a = s.anchors[i]
                    draw_line_strip_2d(shader, [a[1], a[0], a[2]],
                                       _COL_HANDLE, width=1.5)
                    draw_points_2d(shader, [a[1], a[2]],
                                   (0.0, 0.0, 0.0, 0.95), size=17.0)
                    draw_points_2d(shader, [a[1], a[2]], _COL_HANDLE, size=13.0)
                    draw_points_2d(shader, [a[0]],
                                   (0.0, 0.0, 0.0, 0.95), size=30.0)
                    draw_points_2d(shader, [a[0]], _COL_SEL, size=23.0)

            if st == 'DRAG_RECT' and self.anchor is not None:
                draw_line_strip_2d(shader, _rect_points(self.anchor, self.mouse),
                                   _COL_ACTIVE, width=2.0, closed=True)
            elif st == 'DRAG_CIRCLE' and self.anchor is not None:
                r = (self.mouse - self.anchor).length
                if r > 2.0:
                    draw_line_strip_2d(shader, _circle_points(self.anchor, r),
                                       _COL_ACTIVE, width=2.0, closed=True)
            elif st == 'DRAG_LASSO' and len(self.cur) >= 2:
                draw_line_strip_2d(shader, self.cur, _COL_ACTIVE, width=2.0)
            elif st == 'POLY':
                if len(self.cur) >= 2:
                    draw_line_strip_2d(shader, self.cur, _COL_ACTIVE, width=2.0)
                if self.cur:
                    draw_line_strip_2d(shader, [self.cur[-1], self.mouse],
                                       (1, 1, 1, 0.4), width=1.0)
                    draw_points_2d(shader, self.cur, _COL_POINT, size=6.0)
            elif st == 'BEZIER' and self.bz:
                pts = _sample_bezier(self.bz, False)
                if len(pts) >= 2:
                    draw_line_strip_2d(shader, pts, _COL_ACTIVE, width=2.0)
                a = self.bz[-1]
                try:
                    seg = interpolate_bezier(a[0], a[2], self.mouse, self.mouse, 12)
                    seg = [Vector((v[0], v[1])) for v in seg]
                    draw_line_strip_2d(shader, seg, (1, 1, 1, 0.4), width=1.0)
                except Exception:
                    pass
                draw_points_2d(shader, [x[0] for x in self.bz], _COL_ANCHOR, size=6.0)
                if self.bz_drag:
                    draw_line_strip_2d(shader, [a[1], a[0], a[2]],
                                       _COL_HANDLE, width=1.0)
                    draw_points_2d(shader, [a[1], a[2]], _COL_HANDLE, size=5.0)
            elif st == 'ERASE' and len(self.erase_pts) >= 2:
                draw_line_strip_2d(shader, self.erase_pts, _COL_ERASE,
                                   width=2.0, closed=len(self.erase_pts) >= 3)
            elif st == 'BOX' and self.box_start is not None:
                draw_line_strip_2d(shader,
                                   _rect_points(self.box_start, self.mouse),
                                   (1.0, 1.0, 1.0, 0.7), width=1.0, closed=True)

            # 魔棒取色环：上半=当前悬停色，下半=上次吸取色（PS 风格）
            if st == 'IDLE':
                try:
                    if self._mode(context) == 'WAND':
                        self._draw_wand_ring(shader)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                reset_state()
            except Exception:
                pass


    def _draw_wand_ring(self, shader):
        """在光标右上角画半环色样：上半=悬停色，下半=上次色。"""
        c = self.mouse + Vector((34.0, 34.0))
        r_in, r_out, segs = 11.0, 20.0, 24
        hover = self.wand_hover
        last = self.wand_last
        col_top = (hover[0], hover[1], hover[2], 1.0) if hover else (0.2, 0.2, 0.2, 0.6)
        col_bot = (last[0], last[1], last[2], 1.0) if last else (0.2, 0.2, 0.2, 0.6)

        def ring_half(a0, a1, col):
            tris = []
            for i in range(segs):
                t0 = a0 + (a1 - a0) * i / segs
                t1 = a0 + (a1 - a0) * (i + 1) / segs
                i0 = (c.x + r_in * math.cos(t0), c.y + r_in * math.sin(t0))
                i1 = (c.x + r_in * math.cos(t1), c.y + r_in * math.sin(t1))
                o0 = (c.x + r_out * math.cos(t0), c.y + r_out * math.sin(t0))
                o1 = (c.x + r_out * math.cos(t1), c.y + r_out * math.sin(t1))
                tris += [i0, o0, o1, i0, o1, i1]
            draw_tris_2d(shader, tris, col)

        ring_half(0.0, math.pi, col_top)          # 上半
        ring_half(math.pi, 2.0 * math.pi, col_bot)  # 下半
        # 内外描边 + 中分线，保证深浅背景都可见
        for r in (r_in, r_out):
            circle = [(c.x + r * math.cos(2 * math.pi * i / 32),
                       c.y + r * math.sin(2 * math.pi * i / 32))
                      for i in range(33)]
            draw_line_strip_2d(shader, [Vector(p) for p in circle],
                               (0.0, 0.0, 0.0, 0.8), width=1.0)
        draw_line_strip_2d(shader,
                           [Vector((c.x - r_out, c.y)), Vector((c.x - r_in, c.y))],
                           (0.0, 0.0, 0.0, 0.8), width=1.0)
        draw_line_strip_2d(shader,
                           [Vector((c.x + r_in, c.y)), Vector((c.x + r_out, c.y))],
                           (0.0, 0.0, 0.0, 0.8), width=1.0)


class QOPS_OT_activate_cut_tool(bpy.types.Operator):
    """激活 T 面板的「J 切割」工具（自动进入编辑模式）"""
    bl_idname = "qops.activate_cut_tool"
    bl_label = "激活 J 切割工具"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            if context.mode != 'EDIT_MESH':
                obj = context.active_object
                if obj is not None and obj.type == 'MESH':
                    bpy.ops.object.mode_set(mode='EDIT')
                else:
                    self.report({'WARNING'}, "请先选择一个网格物体")
                    return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, "激活失败：%s" % e)
            return {'CANCELLED'}

        # # 直接切换到工具（timer在Blender缺上下文时静默失败，改回直接调用）
        try:
            bpy.ops.wm.tool_set_by_id(name="qops.cut_tool")
        except Exception:
            pass
        return {'FINISHED'}


# 工具图标映射
_TOOL_ICONS = {
    'RECT': 'MESH_PLANE',
    'CIRCLE': 'MESH_CIRCLE',
    'LASSO': 'GP_SELECT_STROKES',
    'POLY': 'IPO_LINEAR',
    'BEZIER': 'CURVE_BEZCURVE',
    'WAND': 'EYEDROPPER',
}


class QOPS_MT_cut_pie(bpy.types.Panel):
    """Ctrl+D 呼出的子工具切换面板（图标按钮，参考 BoxHelper 风格）"""
    bl_idname = "QOPS_MT_cut_pie"
    bl_label = "J 切割 · 子工具"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        layout = self.layout
        cur = getattr(context.scene, "qops_cut_mode", 'RECT')

        layout.label(text="切割子工具")
        row = layout.row(align=True)
        for mode_id, _, _ in MODE_ITEMS:
            op = row.operator("qops.set_cut_mode", text="",
                              icon=_TOOL_ICONS.get(mode_id, 'NONE'),
                              depress=(cur == mode_id))
            op.mode = mode_id

        layout.separator()
        layout.prop(context.scene, "qops_cut_through")
        layout.prop(context.scene)
        if cur == 'WAND':
            layout.prop(context.scene, "qops_wand_tolerance")
            layout.prop(context.scene, "qops_wand_smooth")
            layout.prop(context.scene, "qops_wand_invert")


# 自定义 J 手术刀图标（icons/qops.cutter.dat），缺失则退回内置刀具图标
_ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "icons", "qops.cutter")


_MODE_LABELS = {
    'RECT':   "方形切割",
    'CIRCLE': "圆形切割",
    'LASSO':  "套索切割",
    'POLY':   "折线切割",
    'BEZIER': "曲线切割",
    'WAND':   "选区创建",
}


class QOPS_OT_set_cut_mode(bpy.types.Operator):
    """切换切割子工具"""
    bl_idname = "qops.set_cut_mode"
    bl_label = "切换子工具"
    bl_options = {'REGISTER'}
    mode: bpy.props.StringProperty(default='RECT')

    @classmethod
    def description(cls, context, properties):
        return _MODE_LABELS.get(getattr(properties, "mode", ""), "切换子工具")

    def execute(self, context):
        try:
            context.scene.qops_cut_mode = self.mode
        except Exception:
            pass
        return {'FINISHED'}


class QOPS_ToolDrawCut(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'
    bl_idname = "qops.cut_tool"
    bl_label = "J 切割"
    bl_description = ("PS 式切割线：左键绘制，Alt 擦除，Shift 吸附，Ctrl 编辑锚点，"
                      "Shift+D 复制，G/S/R 变换，Ctrl+D 切子工具，Enter 切割")
    bl_icon = _ICON_PATH if os.path.isfile(_ICON_PATH + ".dat") else "ops.mesh.knife"
    bl_widget = None
    bl_keymap = (
        ("qops.draw_cut",
         {"type": 'LEFTMOUSE', "value": 'PRESS'},
         None),
        ("qops.draw_cut",
         {"type": 'LEFTMOUSE', "value": 'PRESS', "alt": True},
         None),
        ("qops.draw_cut",
         {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": True},
         None),
        ("qops.draw_cut",
         {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
         None),
        ("wm.call_panel",
         {"type": 'D', "value": 'PRESS', "ctrl": True},
         {"properties": [("name", "QOPS_MT_cut_pie"),
                         ("keep_open", False)]}),
    )

    @staticmethod
    def draw_settings(context, layout, tool):
        layout.prop(context.scene, "qops_cut_mode", text="")
        layout.prop(context.scene, "qops_cut_through")
        if getattr(context.scene, "qops_cut_mode", '') == 'WAND':
            layout.prop(context.scene, "qops_wand_tolerance")
            layout.prop(context.scene, "qops_wand_smooth")
            layout.prop(context.scene, "qops_wand_invert")


classes = (
    QOPS_OT_draw_cut,
    QOPS_OT_activate_cut_tool,
    QOPS_OT_set_cut_mode,
    QOPS_MT_cut_pie,
)


def register_extra():
    bpy.types.Scene.qops_cut_mode = bpy.props.EnumProperty(
        name="切割子工具", items=MODE_ITEMS, default='RECT')
    bpy.types.Scene.qops_cut_through = bpy.props.BoolProperty(
        name="切透", description="连同背面的面一起切", default=False)
    bpy.types.Scene.qops_wand_tolerance = bpy.props.FloatProperty(
        name="魔棒容差",
        description="颜色相似度容差(0-1)：越大选中的色块范围越广",
        default=0.15, min=0.01, max=1.0)
    bpy.types.Scene.qops_wand_smooth = bpy.props.BoolProperty(
        name="曲线描边",
        description="勾选后魔棒轮廓拟合成平滑贝塞尔曲线(锚点可Ctrl编辑)，"
                    "形状更规则不抖动；取消则保留原始逐像素轮廓",
        default=True)
    bpy.types.Scene.qops_wand_invert = bpy.props.BoolProperty(
        name="反选(取图案主体)",
        description="勾选后：点击背景(如白底)，实际描的是背景之外的图案主体外轮廓。"
                    "适合'选背景删背景'：切割后背景成独立面，选中删除即可",
        default=False)
    try:
        bpy.utils.register_tool(QOPS_ToolDrawCut, separator=True, group=False)
    except Exception:
        pass


def unregister_extra():
    try:
        bpy.utils.unregister_tool(QOPS_ToolDrawCut)
    except Exception:
        pass
    for p in ("qops_cut_mode", "qops_cut_through", "qops_wand_tolerance", "qops_wand_smooth", "qops_wand_invert"):
        try:
            delattr(bpy.types.Scene, p)
        except Exception:
            pass
