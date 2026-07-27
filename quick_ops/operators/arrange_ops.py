# -*- coding: utf-8 -*-
"""
自动铺陈排列 v5
==============
修复清单：
1. 属性名 _snapshot 以下划线开头 → Blender 跳过注册 → redo 时快照永远为空
   → 改名 pos_json (无下划线)
2. align_ground 在 F9 中可见并可实时调整
3. use_parent / use_collection 改名去掉类私有前缀，确保 redo 时正确读取
4. execute 用 bpy.data.objects.get(name) 按名称查找对象，
   不依赖 context.selected_objects（redo 时选择可能已变化）
5. 布局计算完全基于快照内保存的原始包围盒，与当前物体位置无关
"""

import bpy
import math
import json
from mathutils import Vector


# =============================================================================
# 包围盒（含 Z，基于世界坐标）
# =============================================================================
def _world_bbox_obj(obj):
    mw = obj.matrix_world
    if hasattr(obj, 'bound_box') and obj.type in {
            'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'LIGHT', 'CAMERA'}:
        try:
            corners = [mw @ Vector(c) for c in obj.bound_box]
            xs = [v.x for v in corners]
            ys = [v.y for v in corners]
            zs = [v.z for v in corners]
            return (min(xs), min(ys), min(zs),
                    max(xs), max(ys), max(zs))
        except Exception:
            pass
    loc = mw.translation
    return loc.x, loc.y, loc.z, loc.x, loc.y, loc.z


# =============================================================================
# 分组逻辑（纯函数，只依赖传入的对象列表）
# =============================================================================
def _roots_in(objs):
    names = {o.name for o in objs}
    return [o for o in objs if o.parent is None or o.parent.name not in names]


def _build_groups(objs, use_parent, use_collection, scene=None):
    if use_collection:
        scene_coll = None
        try:
            if scene:
                scene_coll = scene.collection.name
        except Exception:
            pass
        def best(o):
            cs = [c for c in o.users_collection if c.name != scene_coll]
            return max(cs, key=lambda c: len(c.name)).name if cs else None
        gmap = {}
        for o in objs:
            k = best(o) or ("_" + o.name)
            gmap.setdefault(k, []).append(o)
        return [{'roots': _roots_in(g), 'all': g} for g in gmap.values()]

    elif use_parent:
        sel = {o.name for o in objs}
        def root(o):
            return o if (not o.parent or o.parent.name not in sel) else root(o.parent)
        gmap = {}
        for o in objs:
            r = root(o)
            gmap.setdefault(r.name, {'roots': [r], 'all': []})['all'].append(o)
        return list(gmap.values())

    return [{'roots': [o], 'all': [o]} for o in objs]


# =============================================================================
# 快照辅助
# =============================================================================
def _take_snapshot(objs):
    """记录每个对象的位置和原始包围盒（用于 redo 时从同一起点重排）。"""
    snap = {}
    for o in objs:
        bb = _world_bbox_obj(o)
        snap[o.name] = {
            'loc': [o.location.x, o.location.y, o.location.z],
            'bb': list(bb),           # [xmin,ymin,zmin,xmax,ymax,zmax]
        }
    return json.dumps(snap)


def _restore_from_snapshot(snap_json):
    """把对象还原到快照位置；返回成功还原的对象名列表。"""
    if not snap_json:
        return []
    try:
        snap = json.loads(snap_json)
    except Exception:
        return []
    restored = []
    for name, d in snap.items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        x, y, z = d['loc']
        obj.location.x = x
        obj.location.y = y
        obj.location.z = z
        restored.append(name)
    return restored


def _groups_from_snapshot(snap_json, use_parent, use_collection, scene=None):
    """从快照重建分组信息，使用快照中保存的包围盒（不依赖当前物体位置）。"""
    if not snap_json:
        return []
    try:
        snap = json.loads(snap_json)
    except Exception:
        return []
    objs = [bpy.data.objects.get(n) for n in snap]
    objs = [o for o in objs if o is not None]
    if not objs:
        return []
    groups = _build_groups(objs, use_parent, use_collection, scene)
    items = []
    for g in groups:
        # 合并组内所有对象的快照包围盒
        mn = [1e18, 1e18, 1e18]
        mx = [-1e18, -1e18, -1e18]
        for o in g['all']:
            if o.name not in snap:
                continue
            bb = snap[o.name]['bb']
            for i in range(3):
                mn[i] = min(mn[i], bb[i])
                mx[i] = max(mx[i], bb[i + 3])
        w = max(mx[0] - mn[0], 1e-6)
        h = max(mx[1] - mn[1], 1e-6)
        items.append({
            'roots': g['roots'],
            'w': w, 'h': h,
            'cx': (mn[0] + mx[0]) / 2.0,
            'cy': (mn[1] + mx[1]) / 2.0,
            'minz': mn[2],
            'area': w * h,
        })
    return items


# =============================================================================
# 算子
# =============================================================================
class QOPS_OT_auto_arrange(bpy.types.Operator):
    """将选中物体在 XY 平面自动铺陈排列（以世界原点居中）"""
    bl_idname = "qops.auto_arrange"
    bl_label = "自动铺陈排列"
    bl_options = {'REGISTER', 'UNDO'}

    # ── F9 可见参数 ──────────────────────────────────────────────────────────
    arr_mode: bpy.props.EnumProperty(
        name="模式",
        items=[('COLS', "按列数", ""), ('ROWS', "按行数", "")],
        default='COLS')
    cols: bpy.props.IntProperty(name="列数", default=5, min=1, max=100)
    rows: bpy.props.IntProperty(name="行数", default=3, min=1, max=100)
    padding: bpy.props.FloatProperty(
        name="间距",
        description="相邻物体包围盒之间的空隙（不是中心距）",
        default=0.1, min=0.0, soft_max=5.0)
    sort_by: bpy.props.EnumProperty(
        name="排序",
        items=[('SIZE_ASC', "由小到大", ""),
               ('SIZE_DESC', "由大到小", ""),
               ('NONE', "不排序", "")],
        default='SIZE_ASC')
    align_ground: bpy.props.BoolProperty(
        name="底部贴地",
        description="每组包围盒最低点对齐 Z=0",
        default=True)

    # ── 隐藏（结构性，invoke 时从场景属性复制）────────────────────────────
    use_parent: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    use_collection: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    # 关键：属性名不能以下划线开头，否则 Blender 不注册，redo 时永远是空串
    pos_json: bpy.props.StringProperty(default='', options={'HIDDEN'})
    sort_order: bpy.props.StringProperty(default='', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def invoke(self, context, event):
        sc = context.scene
        self.arr_mode       = getattr(sc, 'qops_arr_mode', 'COLS')
        self.cols           = getattr(sc, 'qops_arr_cols', 5)
        self.rows           = getattr(sc, 'qops_arr_rows', 3)
        self.padding        = getattr(sc, 'qops_arr_padding', 0.1)
        self.sort_by        = getattr(sc, 'qops_arr_sort', 'SIZE_ASC')
        self.align_ground   = getattr(sc, 'qops_arr_ground', True)
        self.use_parent     = getattr(sc, 'qops_arr_use_parent', False)
        self.use_collection = getattr(sc, 'qops_arr_use_collection', False)
        # 快照：在对象未移动时拍，包含位置 + 包围盒
        self.pos_json = _take_snapshot(context.selected_objects)
        return self.execute(context)

    def execute(self, context):
        if not self.pos_json:
            # 没有快照（直接调用 execute 而非 invoke）→ 实时拍
            self.pos_json = _take_snapshot(context.selected_objects)

        # ① 还原到原始位置（F9 redo 时确保从同一起点出发）
        _restore_from_snapshot(self.pos_json)

        # ② 从快照重建分组 + 包围盒（完全不依赖当前物体位置）
        items = _groups_from_snapshot(
            self.pos_json, self.use_parent, self.use_collection, context.scene)
        if not items:
            self.report({'WARNING'}, "没有可排列的物体")
            return {'CANCELLED'}

        # ③ 排序
        if self.sort_by == 'SIZE_ASC':
            items.sort(key=lambda b: b['area'])
        elif self.sort_by == 'SIZE_DESC':
            items.sort(key=lambda b: b['area'], reverse=True)
        # 存储排序结果供 redo 一致性（可选）

        # ④ 计算网格
        n = len(items)
        if self.arr_mode == 'COLS':
            ncols = max(1, self.cols)
            nrows = math.ceil(n / ncols)
        else:
            nrows = max(1, self.rows)
            ncols = math.ceil(n / nrows)

        # 每列最大宽 / 每行最大高
        col_w = [0.0] * ncols
        row_h = [0.0] * nrows
        for idx, b in enumerate(items):
            r, c = divmod(idx, ncols)
            if r < nrows:
                col_w[c] = max(col_w[c], b['w'])
                row_h[r] = max(row_h[r], b['h'])

        pad = max(0.0, self.padding)
        # 间距 = 相邻包围盒边界之间的空隙（pad 直接加在列宽/行高之间）
        total_w = sum(col_w) + pad * max(ncols - 1, 0)
        total_h = sum(row_h) + pad * max(nrows - 1, 0)
        col_xs, cx = [], -total_w / 2.0
        for cw in col_w:
            col_xs.append(cx + cw / 2.0)
            cx += cw + pad
        row_ys, cy = [], total_h / 2.0
        for rh in row_h:
            row_ys.append(cy - rh / 2.0)
            cy -= rh + pad

        # ⑤ 移动（从快照原始位置出发 + 偏移）
        try:
            snap = json.loads(self.pos_json)
        except Exception:
            snap = {}

        for idx, b in enumerate(items):
            r, c = divmod(idx, ncols)
            if r >= nrows:
                break
            target_cx = col_xs[c]
            target_cy = row_ys[r]
            dx = target_cx - b['cx']
            dy = target_cy - b['cy']
            dz = (-b['minz']) if self.align_ground else 0.0
            for obj in b['roots']:
                orig = snap.get(obj.name, {}).get('loc', None)
                if orig:
                    obj.location.x = orig[0] + dx
                    obj.location.y = orig[1] + dy
                    obj.location.z = orig[2] + dz
                else:
                    obj.location.x += dx
                    obj.location.y += dy
                    obj.location.z += dz

        self.report({'INFO'}, "已排列 %d 组 %d行×%d列" % (n, nrows, ncols))
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "arr_mode")
        if self.arr_mode == 'COLS':
            layout.prop(self, "cols")
        else:
            layout.prop(self, "rows")
        layout.prop(self, "padding")
        layout.prop(self, "sort_by")
        layout.prop(self, "align_ground")


classes = (QOPS_OT_auto_arrange,)


def register_extra():
    bpy.types.Scene.qops_arr_use_parent = bpy.props.BoolProperty(
        name="保持父子级相对位置",
        description="有父子关系的物体作为整体排列，只移动根节点",
        default=False)
    bpy.types.Scene.qops_arr_use_collection = bpy.props.BoolProperty(
        name="保持集合内相对位置",
        description="同集合物体作为整体(含父子级逻辑)",
        default=False)
    bpy.types.Scene.qops_arr_mode = bpy.props.EnumProperty(
        name="模式",
        items=[('COLS', "按列数", ""), ('ROWS', "按行数", "")],
        default='COLS')
    bpy.types.Scene.qops_arr_cols = bpy.props.IntProperty(
        name="列数", default=5, min=1, max=100)
    bpy.types.Scene.qops_arr_rows = bpy.props.IntProperty(
        name="行数", default=3, min=1, max=100)
    bpy.types.Scene.qops_arr_padding = bpy.props.FloatProperty(
        name="间距", default=0.1, min=0.0)
    bpy.types.Scene.qops_arr_sort = bpy.props.EnumProperty(
        name="排序",
        items=[('SIZE_ASC', "由小到大", ""),
               ('SIZE_DESC', "由大到小", ""),
               ('NONE', "不排序", "")],
        default='SIZE_ASC')
    bpy.types.Scene.qops_arr_ground = bpy.props.BoolProperty(
        name="底部贴地",
        description="每组包围盒最低点对齐 Z=0",
        default=True)


def unregister_extra():
    for p in ("qops_arr_use_parent", "qops_arr_use_collection",
              "qops_arr_mode", "qops_arr_cols", "qops_arr_rows",
              "qops_arr_padding", "qops_arr_sort", "qops_arr_ground"):
        try:
            delattr(bpy.types.Scene, p)
        except Exception:
            pass
