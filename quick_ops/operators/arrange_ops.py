# -*- coding: utf-8 -*-
"""
自动铺陈排列 v6
==============
关键算法：
  父子层级同时在选中集时，按深度先移父后移子：
    根节点：  obj.location = world_origin_target
    子节点：  obj.location = rot_inv @ (target_child - target_parent)
  不依赖 matrix_world 刷新，不需要 view_layer.update()。
"""

import bpy, math, json
from mathutils import Vector
from collections import defaultdict


# ── 包围盒 ──────────────────────────────────────────────────────────────────
def _world_bbox_obj(obj, depsgraph=None):
    """
    物体的世界空间轴对齐包围盒。
    优先用【评估后网格】的顶点（含阵列/镜像/曲线等生成式修改器产生的几何），
    这样带 Array/Mirror 的物体边界会覆盖修改器生成的部分，避免排列重叠。
    评估失败时回退到 obj.bound_box（原始网格）。
    """
    mw = obj.matrix_world
    # 尝试用评估网格顶点求真实边界
    if depsgraph is not None:
        try:
            eval_obj = obj.evaluated_get(depsgraph)
            me = eval_obj.to_mesh()
            if me is not None and len(me.vertices) > 0:
                xs=[]; ys=[]; zs=[]
                for v in me.vertices:
                    w = mw @ v.co
                    xs.append(w.x); ys.append(w.y); zs.append(w.z)
                eval_obj.to_mesh_clear()
                if xs:
                    return min(xs),min(ys),min(zs),max(xs),max(ys),max(zs)
            else:
                try: eval_obj.to_mesh_clear()
                except Exception: pass
        except Exception:
            pass
    # 回退：原始 bound_box
    if hasattr(obj,'bound_box') and obj.type in {
            'MESH','CURVE','SURFACE','FONT','META','LIGHT','CAMERA'}:
        try:
            cs = [mw @ Vector(c) for c in obj.bound_box]
            xs=[v.x for v in cs]; ys=[v.y for v in cs]; zs=[v.z for v in cs]
            return min(xs),min(ys),min(zs),max(xs),max(ys),max(zs)
        except Exception: pass
    l = mw.translation
    return l.x,l.y,l.z,l.x,l.y,l.z


def _group_bbox(objs):
    mn=mx=None
    for o in objs:
        a=_world_bbox_obj(o)
        mn=(min(mn[i],a[i]) for i in range(3)) if mn else a[:3]
        mx=(max(mx[i],a[i+3]) for i in range(3)) if mx else a[3:]
    if mn is None: return (0,0,0),(0,0,0)
    return tuple(mn),tuple(mx)


# ── 分组 ────────────────────────────────────────────────────────────────────
def _roots_in(objs):
    ns={o.name for o in objs}
    return [o for o in objs if not o.parent or o.parent.name not in ns]



def _reunite_children_to_parent_collection(objs, scene=None):
    """
    集合模式下：若某物体的父级在选中集里但不在同一场景集合，
    把该子物体移动到父级所在的集合（先 unlink 原集合，再 link 父级集合），
    使父子被视为同一集合的整体。返回被移动的物体名列表。
    """
    sc_name = None
    try:
        if scene:
            sc_name = scene.collection.name
    except Exception:
        pass
    names = {o.name for o in objs}
    moved = []
    for o in objs:
        p = o.parent
        if not p or p.name not in names:
            continue
        # 父的“最佳集合”（非场景根）
        p_colls = [c for c in p.users_collection if c.name != sc_name]
        o_colls = [c for c in o.users_collection]
        if not p_colls:
            continue
        target = p_colls[0]
        if target.name in {c.name for c in o_colls}:
            continue  # 已同集合
        # 移动：unlink 全部，link 父集合
        try:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            target.objects.link(o)
            moved.append(o.name)
        except Exception:
            pass
    return moved


def _build_groups(objs, use_parent, use_collection, scene=None):
    if use_collection:
        sc_name=None
        try: sc_name=scene.collection.name if scene else None
        except: pass
        def best(o):
            cs=[c for c in o.users_collection if c.name!=sc_name]
            return max(cs,key=lambda c:len(c.name)).name if cs else None
        gmap={}
        for o in objs: gmap.setdefault(best(o) or "_"+o.name,[]).append(o)
        return [{'roots':_roots_in(g),'all':g} for g in gmap.values()]
    if use_parent:
        sel={o.name for o in objs}
        def root(o): return o if(not o.parent or o.parent.name not in sel) else root(o.parent)
        gmap={}
        for o in objs:
            r=root(o); gmap.setdefault(r.name,{'roots':[r],'all':[]})['all'].append(o)
        return list(gmap.values())
    return [{'roots':[o],'all':[o]} for o in objs]


# ── 快照 ────────────────────────────────────────────────────────────────────
def _take_snapshot(objs, depsgraph=None):
    snap={}
    for o in objs:
        bb=_world_bbox_obj(o, depsgraph)
        try: wloc=list(o.matrix_world.translation)
        except: wloc=[o.location.x,o.location.y,o.location.z]
        snap[o.name]={
            'loc':[o.location.x,o.location.y,o.location.z],  # 父局部坐标
            'bb':list(bb),      # 世界包围盒 [xmin,ymin,zmin,xmax,ymax,zmax]
            'wloc':wloc,        # 世界原点坐标
        }
    return json.dumps(snap)


def _restore_from_snapshot(snap_json):
    if not snap_json: return
    try: snap=json.loads(snap_json)
    except: return
    for name,d in snap.items():
        obj=bpy.data.objects.get(name)
        if obj: x,y,z=d['loc']; obj.location.x=x; obj.location.y=y; obj.location.z=z


def _groups_from_snapshot(snap_json, use_parent, use_collection, scene=None):
    if not snap_json: return []
    try: snap=json.loads(snap_json)
    except: return []
    objs=[bpy.data.objects.get(n) for n in snap]
    objs=[o for o in objs if o]
    if not objs: return []
    groups=_build_groups(objs,use_parent,use_collection,scene)
    items=[]
    for g in groups:
        mn=[1e18]*3; mx=[-1e18]*3
        for o in g['all']:
            if o.name not in snap: continue
            bb=snap[o.name]['bb']
            for i in range(3): mn[i]=min(mn[i],bb[i]); mx[i]=max(mx[i],bb[i+3])
        w=max(mx[0]-mn[0],1e-6); h=max(mx[1]-mn[1],1e-6)
        items.append({'roots':g['roots'],'w':w,'h':h,
                      'cx':(mn[0]+mx[0])/2,'cy':(mn[1]+mx[1])/2,
                      'minz':mn[2],'area':w*h})
    return items


# ── 算子 ────────────────────────────────────────────────────────────────────
class QOPS_OT_auto_arrange(bpy.types.Operator):
    """将选中物体在 XY 平面自动铺陈排列"""
    bl_idname="qops.auto_arrange"; bl_label="自动铺陈排列"
    bl_options={'REGISTER','UNDO'}

    arr_mode:    bpy.props.EnumProperty(name="模式",items=[('COLS',"按列数",""),('ROWS',"按行数","")],default='COLS')
    cols:        bpy.props.IntProperty(name="列数",default=5,min=1,max=100)
    rows:        bpy.props.IntProperty(name="行数",default=3,min=1,max=100)
    padding:     bpy.props.FloatProperty(name="间距",description="相邻包围盒边界间空隙",default=0.1,min=0.0,soft_max=5.0)
    sort_by:     bpy.props.EnumProperty(name="排序",items=[('SIZE_ASC',"由小到大",""),('SIZE_DESC',"由大到小",""),('NONE',"不排序","")],default='SIZE_ASC')
    align_ground:bpy.props.BoolProperty(name="底部贴地",description="包围盒最低点对齐 Z=0",default=True)
    use_parent:  bpy.props.BoolProperty(default=False,options={'HIDDEN'})
    use_collection:bpy.props.BoolProperty(default=False,options={'HIDDEN'})
    pos_json:    bpy.props.StringProperty(default='',options={'HIDDEN'})

    @classmethod
    def poll(cls,ctx): return bool(ctx.selected_objects)

    def invoke(self,ctx,event):
        sc=ctx.scene
        self.arr_mode      =getattr(sc,'qops_arr_mode','COLS')
        self.cols          =getattr(sc,'qops_arr_cols',5)
        self.rows          =getattr(sc,'qops_arr_rows',3)
        self.padding       =getattr(sc,'qops_arr_padding',0.1)
        self.sort_by       =getattr(sc,'qops_arr_sort','SIZE_ASC')
        self.align_ground  =getattr(sc,'qops_arr_ground',True)
        self.use_parent    =getattr(sc,'qops_arr_use_parent',False)
        self.use_collection=getattr(sc,'qops_arr_use_collection',False)
        try:
            dg=ctx.evaluated_depsgraph_get()
        except Exception:
            dg=None
        self.pos_json=_take_snapshot(ctx.selected_objects, dg)
        return self.execute(ctx)

    def execute(self,ctx):
        if not self.pos_json:
            try:
                dg=ctx.evaluated_depsgraph_get()
            except Exception:
                dg=None
            self.pos_json=_take_snapshot(ctx.selected_objects, dg)

        # ①' 集合模式：父子跨集合时，先把子物体移到父级所在集合
        if self.use_collection:
            try:
                _reunite_children_to_parent_collection(
                    list(ctx.selected_objects), ctx.scene)
            except Exception:
                pass

        # ① 还原
        _restore_from_snapshot(self.pos_json)

        # ② 分组 + 包围盒（来自快照，与当前位置无关）
        items=_groups_from_snapshot(self.pos_json,self.use_parent,self.use_collection,ctx.scene)
        if not items:
            self.report({'WARNING'},"没有可排列的物体"); return {'CANCELLED'}

        # ③ 排序
        if self.sort_by=='SIZE_ASC':   items.sort(key=lambda b:b['area'])
        elif self.sort_by=='SIZE_DESC':items.sort(key=lambda b:b['area'],reverse=True)

        # ④ 计算网格
        n=len(items)
        if self.arr_mode=='COLS':
            ncols=max(1,self.cols); nrows=math.ceil(n/ncols)
        else:
            nrows=max(1,self.rows); ncols=math.ceil(n/nrows)
        col_w=[0.0]*ncols; row_h=[0.0]*nrows
        for idx,b in enumerate(items):
            r,c=divmod(idx,ncols)
            if r<nrows: col_w[c]=max(col_w[c],b['w']); row_h[r]=max(row_h[r],b['h'])
        pad=max(0.0,self.padding)
        total_w=sum(col_w)+pad*max(ncols-1,0); total_h=sum(row_h)+pad*max(nrows-1,0)
        col_xs=[]; cx=-total_w/2
        for cw in col_w: col_xs.append(cx+cw/2); cx+=cw+pad
        row_ys=[]; cy=total_h/2
        for rh in row_h: row_ys.append(cy-rh/2); cy-=rh+pad

        # ⑤ 计算每个物体目标「世界原点坐标」
        #    target_world_origin = 目标槽位包围盒中心 - (原始世界包围盒中心 - 原始世界原点)
        #                        = 目标槽位中心 - bbox_to_origin_offset
        try: snap=json.loads(self.pos_json)
        except: snap={}

        world_tgt={}   # name → Vector (目标世界原点)
        for idx,b in enumerate(items):
            r,c=divmod(idx,ncols)
            if r>=nrows: break
            # 整组统一位移：组包围盒中心 → 槽位中心；组内所有根节点加同一位移
            delta_x=col_xs[c]-b['cx']
            delta_y=row_ys[r]-b['cy']
            dz=(-b['minz']) if self.align_ground else 0.0
            for obj in b['roots']:
                sd=snap.get(obj.name,{})
                wloc=sd.get('wloc',sd.get('loc',[0,0,0]))
                world_tgt[obj.name]=Vector((
                    wloc[0]+delta_x,
                    wloc[1]+delta_y,
                    wloc[2]+dz
                ))

        all_names=set(world_tgt)
        grouped=(self.use_parent or self.use_collection)

        if grouped:
            # ── 分组模式（v0.11.11 逻辑）：组内 roots 施加同一世界位移 ──
            #    roots 已由 _build_groups 挑出，子物体随父自然移动，不碰
            for name in all_names:
                obj=bpy.data.objects.get(name)
                if not obj: continue
                tgt=world_tgt[name]
                sd=snap.get(name,{})
                orig_loc=sd.get('loc',[0,0,0])
                wloc=sd.get('wloc',orig_loc)
                # 世界位移量（组统一）→ 直接加到局部 location（父不在组内 roots，无需转换）
                obj.location.x=orig_loc[0]+(tgt.x-wloc[0])
                obj.location.y=orig_loc[1]+(tgt.y-wloc[1])
                obj.location.z=orig_loc[2]+(tgt.z-wloc[2])
        else:
            # ── 独立模式：每个物体单独一格，先父后子 ──
            #    对任意有父级的物体用 parent.matrix_world.inverted() @ 世界目标 求局部坐标；
            #    每个深度层之间刷新矩阵，保证父级新位置对子级可见。
            def _depth(obj):
                d=0; p=obj.parent
                while p and p.name in all_names: d+=1; p=p.parent
                return d
            by_depth=defaultdict(list)
            for n2 in all_names:
                obj=bpy.data.objects.get(n2)
                if obj: by_depth[_depth(obj)].append(obj)

            # 先整体刷新一次（restore 后矩阵回到原始）
            try: ctx.view_layer.update()
            except Exception: pass

            for depth in sorted(by_depth.keys()):
                for obj in by_depth[depth]:
                    tgt=world_tgt[obj.name]   # 世界目标原点
                    # 直接赋值 matrix_world：Blender 自动按父级当前矩阵反算 location，
                    # 正确处理 matrix_parent_inverse，无需手动求逆。
                    try:
                        mw=obj.matrix_world.copy()
                        mw.translation=tgt
                        obj.matrix_world=mw
                    except Exception:
                        obj.location.x=tgt.x; obj.location.y=tgt.y; obj.location.z=tgt.z
                # 本层移完刷新矩阵，供下一层子物体读取父级新位置
                try: ctx.view_layer.update()
                except Exception: pass

        self.report({'INFO'},"已排列 %d 组 %d行×%d列"%(n,nrows,ncols))
        return {'FINISHED'}

    def draw(self,ctx):
        layout=self.layout
        layout.prop(self,"arr_mode")
        layout.prop(self,"cols") if self.arr_mode=='COLS' else layout.prop(self,"rows")
        layout.prop(self,"padding"); layout.prop(self,"sort_by"); layout.prop(self,"align_ground")


classes=(QOPS_OT_auto_arrange,)


def register_extra():
    bpy.types.Scene.qops_arr_use_parent=bpy.props.BoolProperty(name="保持父子级相对位置",description="有父子关系的物体作为整体排列",default=False)
    bpy.types.Scene.qops_arr_use_collection=bpy.props.BoolProperty(name="保持集合内相对位置",description="同集合物体作为整体排列",default=False)
    bpy.types.Scene.qops_arr_mode=bpy.props.EnumProperty(name="模式",items=[('COLS',"按列数",""),('ROWS',"按行数","")],default='COLS')
    bpy.types.Scene.qops_arr_cols=bpy.props.IntProperty(name="列数",default=5,min=1,max=100)
    bpy.types.Scene.qops_arr_rows=bpy.props.IntProperty(name="行数",default=3,min=1,max=100)
    bpy.types.Scene.qops_arr_padding=bpy.props.FloatProperty(name="间距",default=0.1,min=0.0)
    bpy.types.Scene.qops_arr_sort=bpy.props.EnumProperty(name="排序",items=[('SIZE_ASC',"由小到大",""),('SIZE_DESC',"由大到小",""),('NONE',"不排序","")],default='SIZE_ASC')
    bpy.types.Scene.qops_arr_ground=bpy.props.BoolProperty(name="底部贴地",default=True)


def unregister_extra():
    for p in("qops_arr_use_parent","qops_arr_use_collection","qops_arr_mode","qops_arr_cols","qops_arr_rows","qops_arr_padding","qops_arr_sort","qops_arr_ground"):
        try: delattr(bpy.types.Scene,p)
        except: pass
