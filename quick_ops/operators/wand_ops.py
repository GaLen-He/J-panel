# -*- coding: utf-8 -*-
"""
魔棒：识别参考图色块 -> 生成切割轮廓
====================================
点击贴了图像纹理的参考平面：
1. 视口光线投射找到物体/命中点/面 -> 由重心坐标算出 UV
2. 读图像像素(降采样到 ≤1024)，以点击处颜色为种子、按容差泛洪填充
3. Moore 邻域追踪提取色块外轮廓，RDP 简化
4. 轮廓 UV -> 3D(重心逆映射) -> 屏幕坐标，交给切割会话作为闭合切割线

纯算法部分(泛洪/追踪/简化)不依赖 bpy，便于单测。
限制(v1)：只取外轮廓(色块内的洞忽略)；参考物需为带图像纹理的网格(如"图像作为平面")。
"""

import bpy
from mathutils import Vector
from mathutils.geometry import barycentric_transform, intersect_point_tri_2d
from bpy_extras import view3d_utils

WAND_MAX_DIM = 1024      # 魔棒工作分辨率上限
RDP_EPS = 1.6            # 轮廓简化容差(降采样像素)


# =============================================================================
# 纯算法（numpy）
# =============================================================================
def span_fill(mask, seed):
    """扫描线泛洪：返回 mask 中包含 seed 的连通区域(bool 数组)。
    mask: (H,W) bool；seed: (row, col)。"""
    import numpy as np
    h, w = mask.shape
    region = np.zeros_like(mask)
    r0, c0 = seed
    if not (0 <= r0 < h and 0 <= c0 < w) or not mask[r0, c0]:
        return region
    stack = [(r0, c0)]
    while stack:
        r, c = stack.pop()
        if region[r, c] or not mask[r, c]:
            continue
        row_m = mask[r]
        row_v = region[r]
        # 向左右扩展成整段 run
        c1 = c
        while c1 > 0 and row_m[c1 - 1] and not row_v[c1 - 1]:
            c1 -= 1
        c2 = c
        while c2 < w - 1 and row_m[c2 + 1] and not row_v[c2 + 1]:
            c2 += 1
        row_v[c1:c2 + 1] = True
        # 上下行寻找新种子（run 内每个可填连通段推一个种子）
        for rr in (r - 1, r + 1):
            if 0 <= rr < h:
                seg = mask[rr, c1:c2 + 1] & ~region[rr, c1:c2 + 1]
                if seg.any():
                    idx = np.flatnonzero(seg)
                    # 连续段取首个即可（每段一个种子）
                    starts = [idx[0]]
                    for k in range(1, len(idx)):
                        if idx[k] != idx[k - 1] + 1:
                            starts.append(idx[k])
                    for st in starts:
                        stack.append((rr, c1 + int(st)))
    return region


def erode4(m):
    """4邻域腐蚀（边界视为背景）。"""
    r = m.copy()
    r[1:, :] &= m[:-1, :]
    r[:-1, :] &= m[1:, :]
    r[:, 1:] &= m[:, :-1]
    r[:, :-1] &= m[:, 1:]
    r[0, :] = False
    r[-1, :] = False
    r[:, 0] = False
    r[:, -1] = False
    return r


def dilate4(m):
    """4邻域膨胀。"""
    r = m.copy()
    r[1:, :] |= m[:-1, :]
    r[:-1, :] |= m[1:, :]
    r[:, 1:] |= m[:, :-1]
    r[:, :-1] |= m[:, 1:]
    return r


def largest_component(mask):
    """返回 mask 中最大的连通块(bool)。用于反选时取图案主体。"""
    import numpy as np
    remaining = mask.copy()
    best = None
    best_n = 0
    guard = 0
    while remaining.any() and guard < 4000:
        guard += 1
        rc = np.argwhere(remaining)
        seed = (int(rc[0][0]), int(rc[0][1]))
        comp = span_fill(remaining, seed)
        n = int(comp.sum())
        if n > best_n:
            best_n, best = n, comp
        remaining &= ~comp
    return best if best is not None else mask


EDGE_THRESH = 0.08   # 边缘屏障阈值（灰度梯度）


_MOORE = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
_MOORE_IDX = {d: i for i, d in enumerate(_MOORE)}


def trace_boundary(region):
    """标准 Moore 邻域追踪(回溯记背景像素位置 + Jacob 终止准则)。
    返回外轮廓像素 [(row,col), ...]。"""
    import numpy as np
    h, w = region.shape
    rc = np.argwhere(region)
    if len(rc) == 0:
        return []
    r0, c0 = int(rc[0][0]), int(rc[0][1])
    start = (r0, c0)
    b_init = (r0, c0 - 1)   # 扫描序首像素的西侧必为背景/出界

    def inside(p):
        r, c = p
        return 0 <= r < h and 0 <= c < w and region[r, c]

    contour = [start]
    cur = start
    b = b_init
    npix = int(region.sum())
    max_steps = min(4 * h * w + 8, 8 * npix + 1024)
    for _ in range(max_steps):
        d0 = _MOORE_IDX[(b[0] - cur[0], b[1] - cur[1])]
        nxt = None
        for k in range(1, 9):
            d = (d0 + k) % 8
            cand = (cur[0] + _MOORE[d][0], cur[1] + _MOORE[d][1])
            if inside(cand):
                # 回溯 = 找到前检查的最后一个背景邻居
                pb = (d0 + k - 1) % 8
                b = (cur[0] + _MOORE[pb][0], cur[1] + _MOORE[pb][1])
                nxt = cand
                break
        if nxt is None:
            return contour  # 孤立像素
        cur = nxt
        if cur == start and b == b_init:
            return contour  # Jacob 终止：同方向再次进入起点
        contour.append(cur)
    return contour


def rdp(points, eps):
    """Douglas-Peucker 折线简化（迭代式）。points: [(x,y),...]"""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        dmax, imax = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if L2 <= 1e-12:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / L2
                t = min(max(t, 0.0), 1.0)
                qx, qy = ax + t * dx, ay + t * dy
                d = ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
            if d > dmax:
                dmax, imax = d, i
        if dmax > eps and imax > 0:
            keep[imax] = True
            stack.append((a, imax))
            stack.append((imax, b))
    return [p for p, k in zip(points, keep) if k]


# =============================================================================
# bpy 侧：从点击到屏幕轮廓
# =============================================================================
def _find_image(obj):
    """从物体材质里找第一张图像纹理。"""
    for slot in getattr(obj, "material_slots", []):
        mat = slot.material
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, "image", None):
                return node.image
    return None


def _load_pixels(image, max_dim=WAND_MAX_DIM):
    """读图像像素为 (H,W,C) float 数组，按需降采样。返回 (arr, step)。"""
    import numpy as np
    w, h = image.size
    ch = image.channels
    if w == 0 or h == 0:
        return None, 1
    buf = np.empty(w * h * ch, dtype=np.float32)
    try:
        image.pixels.foreach_get(buf)
    except Exception:
        buf = np.array(image.pixels[:], dtype=np.float32)
    arr = buf.reshape(h, w, ch)
    step = max(1, int(max(w, h) / max_dim) + (1 if max(w, h) % max_dim else 0)) \
        if max(w, h) > max_dim else 1
    if step > 1:
        # 关键：切片是视图，会让缓存持有整张原图缓冲(8K图≈1GB)导致内存爆掉，
        # 必须 copy 成独立小数组并释放原缓冲
        arr = arr[::step, ::step].copy()
        del buf
    return arr, step


_PIX_CACHE = {}


def _get_pixels_cached(image):
    """图像像素缓存：每张图只读一次(降采样后)，悬停取色即时。"""
    try:
        key = (image.name_full, tuple(image.size))
    except Exception:
        key = (getattr(image, "name", "?"), tuple(image.size))
    ent = _PIX_CACHE.get(key)
    if ent is None:
        arr, step = _load_pixels(image)
        if arr is None:
            return None
        if len(_PIX_CACHE) > 3:
            _PIX_CACHE.clear()
        _PIX_CACHE[key] = arr
        ent = arr
    return ent


def _hit_uv(context, mouse, need_tris=False):
    """光线投射 -> (obj, image, uv_hit, tris, err)。need_tris=False 时 tris 为 None。"""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None, None, None, None, "上下文缺失"
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse)
    try:
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, _n, face_index, obj, _mw = context.scene.ray_cast(
            depsgraph, origin, direction)
    except Exception as e:
        return None, None, None, None, "光线投射失败：%s" % e
    if not hit or obj is None or obj.type != 'MESH':
        return None, None, None, None, "点击处没有命中网格物体"
    image = _find_image(obj)
    if image is None:
        return None, None, None, None, "命中物体的材质里没有图像纹理"

    ob_eval = obj.evaluated_get(depsgraph)
    try:
        me = ob_eval.to_mesh()
    except Exception:
        me = None
    if me is None:
        return None, None, None, None, "无法获取网格数据"

    uv_hit = None
    tris = [] if need_tris else None
    try:
        uv_layer = me.uv_layers.active
        if uv_layer is None or len(uv_layer.data) == 0:
            return None, None, None, None, "命中物体没有可用 UV 层"
        try:
            me.calc_loop_triangles()
        except Exception:
            pass
        if len(me.loop_triangles) == 0:
            return None, None, None, None, "网格没有三角形数据"
        inv = obj.matrix_world.inverted()
        p_local = inv @ loc
        for tri in me.loop_triangles:
            hit_tri = (tri.polygon_index == face_index)
            if not need_tris and not hit_tri:
                continue
            vs = [Vector(me.vertices[me.loops[l].vertex_index].co)
                  for l in tri.loops]
            uvs = [Vector((uv_layer.data[l].uv[0], uv_layer.data[l].uv[1], 0.0))
                   for l in tri.loops]
            if need_tris:
                tris.append((vs, uvs))
            if uv_hit is None and hit_tri:
                try:
                    r = barycentric_transform(p_local, vs[0], vs[1], vs[2],
                                              uvs[0], uvs[1], uvs[2])
                    uv_hit = (r[0], r[1])
                except Exception:
                    pass
            if not need_tris and uv_hit is not None:
                break
    finally:
        try:
            ob_eval.to_mesh_clear()
        except Exception:
            pass
    if uv_hit is None:
        return None, None, None, None, "无法计算点击处 UV"
    return obj, image, uv_hit, tris, None


def sample_color(context, mouse):
    """悬停取色：返回 (r,g,b) 0-1，取不到返回 None。"""
    obj, image, uv_hit, _tris, err = _hit_uv(context, mouse, need_tris=False)
    if err is not None:
        return None
    arr = _get_pixels_cached(image)
    if arr is None:
        return None
    H, W = arr.shape[0], arr.shape[1]
    u = min(max(uv_hit[0] % 1.0, 0.0), 1.0)
    v = min(max(uv_hit[1] % 1.0, 0.0), 1.0)
    col = min(int(u * W), W - 1)
    row = min(int(v * H), H - 1)
    px = arr[row, col]
    return (float(px[0]), float(px[1]),
            float(px[2]) if arr.shape[2] >= 3 else float(px[0]))


def wand_screen_contour(context, mouse, tolerance, invert=False):
    """
    从屏幕点击生成色块轮廓的屏幕坐标点列。
    返回 (points_2d 列表, 错误信息 or None)。
    """
    import numpy as np
    region = context.region
    rv3d = context.region_data

    obj, image, uv_hit, tris, err = _hit_uv(context, mouse, need_tris=True)
    if err is not None:
        return None, err

    # 3) 读像素 + 泛洪
    arr = _get_pixels_cached(image)
    if arr is None:
        return None, "图像无像素数据(可能未加载)"
    H, W = arr.shape[0], arr.shape[1]
    u = min(max(uv_hit[0] % 1.0, 0.0), 1.0)
    v = min(max(uv_hit[1] % 1.0, 0.0), 1.0)
    col = min(int(u * W), W - 1)
    row = min(int(v * H), H - 1)   # Blender 像素第0行在图像底部，UV v=0 也在底部，方向一致

    rgb = arr[..., :3] if arr.shape[2] >= 3 else arr
    seed_color = rgb[row, col].copy()
    dist = np.sqrt(((rgb - seed_color) ** 2).sum(axis=2))
    mask = dist <= max(float(tolerance), 1e-4) * 1.7320508  # 容差按 RGB 对角归一

    # 边缘屏障：图案描边处灰度梯度大，泛洪不得穿过 -> 选区停在封闭图形边缘
    gray = rgb.mean(axis=2)
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:] = np.abs(np.diff(gray, axis=1))
    gy[1:, :] = np.abs(np.diff(gray, axis=0))
    grad = np.maximum(gx, gy)
    mask_edge = mask & (grad < EDGE_THRESH)

    use_mask = mask_edge if mask_edge[row, col] else mask
    regionmask = span_fill(use_mask, (row, col))

    # 形态学开运算：掐掉 1-2px 的细渗漏（抗锯齿软边导致的"乱飞"）
    core = erode4(regionmask)
    if core[row, col]:
        core = span_fill(core, (row, col))
        cleaned = dilate4(core) & regionmask
        if cleaned[row, col] and int(cleaned.sum()) >= 4:
            regionmask = span_fill(cleaned, (row, col))

    if invert:
        # 反选：点击(白色)背景后，取"非背景"里最大的连通块=图案主体
        inv = erode4(~regionmask)   # 收缩1px，去掉与背景交界的抗锯齿噪点
        comp = largest_component(inv)
        regionmask = dilate4(comp)  # 膨胀回原尺寸，边界贴合图案外缘

    npix = int(regionmask.sum())
    if npix < 4:
        return None, "选区过小，试着增大容差/关闭反选"
    if npix > 0.97 * H * W:
        return None, "选区几乎覆盖整图，请减小容差"

    # 4) 轮廓 + 简化
    contour = trace_boundary(regionmask)
    if len(contour) < 3:
        return None, "无法提取轮廓"
    pts_px = [(c, r) for (r, c) in contour]  # (x=col, y=row)
    if len(pts_px) > 2400:  # 防病态长轮廓让 RDP O(n^2) 卡死
        k = len(pts_px) // 2400 + 1
        pts_px = pts_px[::k]
    pts_px = rdp(pts_px, RDP_EPS)
    if len(pts_px) < 3:
        return None, "轮廓太简单"

    # 5) 像素 -> UV -> 3D(世界) -> 屏幕
    out = []
    for (x, y) in pts_px:
        uu = (x + 0.5) / W
        vv = (y + 0.5) / H
        uv_pt = Vector((uu, vv, 0.0))
        world = None
        for vs, uvs in tris:
            try:
                if intersect_point_tri_2d(uv_pt.to_2d(), uvs[0].to_2d(),
                                          uvs[1].to_2d(), uvs[2].to_2d()):
                    local = barycentric_transform(uv_pt, uvs[0], uvs[1], uvs[2],
                                                  vs[0], vs[1], vs[2])
                    world = obj.matrix_world @ local
                    break
            except Exception:
                continue
        if world is None:
            continue
        p2 = view3d_utils.location_3d_to_region_2d(region, rv3d, world)
        if p2 is not None:
            out.append(Vector((p2[0], p2[1])))
    if len(out) < 3:
        return None, "轮廓映射回视口失败(色块可能超出参考面UV范围)"
    return out, None
