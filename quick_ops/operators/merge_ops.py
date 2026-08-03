# -*- coding: utf-8 -*-
"""
一键合并导出
============
把选中的一堆（含错综复杂父子级 / 布尔 / 镜像 / 阵列修改器、且可能是关联复制的）
物体，安全地合并成一个独立网格物体，供整体导出。

流程：
1. 备份选择
2. make_single_user：打断关联(linked)数据，使关联复制的物体互相独立
   （否则对其中一个应用修改器会连带改变其它共享数据的物体）
3. 逐个 convert(target='MESH')：按修改器栈顺序应用全部修改器
   （镜像/阵列这类改变几何位置的会先按栈顺序烘焙，无需手动排序；
     被当作镜像参考的物体只要还在场景中，转换时就会正确烘焙）
4. join：合并为一个物体
5. 把合并物体的原点移到包围盒【底部中心】
"""

import bpy
from mathutils import Vector
from .boolean_ops import iter_boolean_targets


# 可被转换为网格的物体类型
_CONVERTIBLE = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}


def _set_origin_to_bottom(context, obj):
    """把 obj 的原点移到其世界包围盒的底部中心（X/Y 居中，Z 最低）。"""
    try:
        mw = obj.matrix_world
        corners = [mw @ Vector(c) for c in obj.bound_box]
        xs = [v.x for v in corners]
        ys = [v.y for v in corners]
        zs = [v.z for v in corners]
        target = Vector(((min(xs) + max(xs)) / 2.0,
                         (min(ys) + max(ys)) / 2.0,
                         min(zs)))
        scene = context.scene
        cursor = scene.cursor
        old_loc = cursor.location.copy()
        old_rot_mode = cursor.rotation_mode
        cursor.location = target
        # 仅当前物体为活动+选中，执行 origin_set 到游标
        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        cursor.location = old_loc
        cursor.rotation_mode = old_rot_mode
        return True
    except Exception:
        return False




def _ensure_realize_instances(obj):
    """
    对物体的每个几何节点修改器，在其节点树 Group Output 的几何输入前插入
    一个 Realize Instances 节点，使 convert(MESH) 时实例几何被实体化。
    - 无实例的节点树插入它也是无害的 pass-through
    - 已有 Realize Instances 且直连 Output 则跳过
    - node_group 若被多个对象共享，先复制一份避免影响其他使用者
    """
    for mod in obj.modifiers:
        if mod.type != 'NODES' or not mod.node_group:
            continue
        ng = mod.node_group

        # 找 Group Output 节点
        output_node = next((n for n in ng.nodes if n.type == 'GROUP_OUTPUT'), None)
        if output_node is None:
            continue
        # 找第一个 GEOMETRY 类型输入插槽（不靠名字，靠类型，兼容改名/多语言）
        geo_socket = next((s for s in output_node.inputs
                           if getattr(s, 'type', '') == 'GEOMETRY'), None)
        if geo_socket is None or not geo_socket.is_linked:
            continue
        incoming = [lnk for lnk in ng.links if lnk.to_socket == geo_socket]
        if not incoming:
            continue
        src_node = incoming[0].from_socket.node
        # 已经是 Realize Instances 直连 → 跳过
        if src_node.type == 'REALIZE_INSTANCES':
            continue

        # 共享数据先复制
        if ng.users > 1:
            try:
                mod.node_group = ng.copy()
                ng = mod.node_group
                output_node = next((n for n in ng.nodes if n.type == 'GROUP_OUTPUT'), None)
                geo_socket = next((s for s in output_node.inputs
                                   if getattr(s, 'type', '') == 'GEOMETRY'), None)
                incoming = [lnk for lnk in ng.links if lnk.to_socket == geo_socket]
                if not incoming or output_node is None or geo_socket is None:
                    continue
            except Exception:
                continue

        try:
            realize = ng.nodes.new('GeometryNodeRealizeInstances')
            realize.location = (output_node.location.x - 220, output_node.location.y)
            src = incoming[0].from_socket
            ng.links.remove(incoming[0])
            ng.links.new(src, realize.inputs[0])
            ng.links.new(realize.outputs[0], geo_socket)
        except Exception:
            pass


def _find_controlling_objects(obj):
    """
    返回"控制"该物体位置/形状的关联对象集合（主要是曲线）。
    检测范围：
    - Array 修改器的 curve 属性
    - Curve 修改器的 object 属性
    - GeometryNodes 修改器中 Object 类型输入属性
    """
    related = set()
    for mod in obj.modifiers:
        # Array 修改器 → 曲线路径
        if mod.type == 'ARRAY':
            c = getattr(mod, 'curve', None)
            if c: related.add(c)
        # Curve 修改器
        elif mod.type == 'CURVE':
            c = getattr(mod, 'object', None)
            if c: related.add(c)
        # Shrinkwrap / Lattice 等
        elif mod.type in {'SHRINKWRAP', 'LATTICE'}:
            c = getattr(mod, 'target', None)
            if c: related.add(c)
        # GeometryNodes：遍历修改器 ID 属性找 Object 引用
        elif mod.type == 'NODES' and mod.node_group:
            ng = mod.node_group
            # 找 Object 类型的 socket 标识符
            obj_keys = set()
            try:
                # Blender 4.0+ interface
                for item in ng.interface.items_tree:
                    if (hasattr(item, 'socket_type') and
                            item.socket_type == 'NodeSocketObject'):
                        obj_keys.add(item.identifier)
            except AttributeError:
                pass
            try:
                # Blender 3.x inputs
                for inp in ng.inputs:
                    if getattr(inp, 'type', '') == 'OBJECT':
                        obj_keys.add(inp.identifier)
            except Exception:
                pass
            # 直接遍历修改器的 ID 属性（兼容两代 API）
            try:
                for key in mod.keys():
                    val = mod[key]
                    if isinstance(val, bpy.types.Object):
                        related.add(val)
            except Exception:
                pass
            # 通过 identifier 精确取值
            for k in obj_keys:
                try:
                    val = getattr(mod, k, None) or mod.get(k)
                    if isinstance(val, bpy.types.Object):
                        related.add(val)
                except Exception:
                    pass
    return {o for o in related if o is not None}


def _collect_boolean_cutters(objs):
    """
    收集 objs 中被【任意选中物体的布尔修改器】引用的运算体名字。
    这些是切割工具，合并时应排除，否则会被当成几何一起并进来。
    """
    cutters = set()
    for o in objs:
        for tgt in iter_boolean_targets(o):
            if tgt is not None:
                cutters.add(tgt.name)
    return cutters


class QOPS_OT_merge_export(bpy.types.Operator):
    """一键合并：打断关联数据→应用全部修改器→合并为单一网格→原点置于底部中心"""
    bl_idname = "qops.merge_export"
    bl_label = "一键合并（导出用）"
    bl_options = {'REGISTER', 'UNDO'}

    origin_bottom: bpy.props.BoolProperty(
        name="原点置于底部中心",
        description="合并后把物体原点移到包围盒底部中心",
        default=True)

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT'
                and len([o for o in context.selected_objects
                         if o.type in _CONVERTIBLE]) >= 1)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        raw = [o for o in context.selected_objects if o.type in _CONVERTIBLE]
        # 排除被用作布尔切割工具的运算体（否则会被当几何一起合并）
        cutters = _collect_boolean_cutters(context.selected_objects)
        sel = [o for o in raw if o.name not in cutters]
        skipped = len(raw) - len(sel)
        if not sel:
            self.report({'WARNING'}, "没有可合并的物体（选中的都是布尔切割体？）")
            return {'CANCELLED'}

        view_layer = context.view_layer

        # ── 1. 打断关联数据（关联复制互相独立）──────────────────────────
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except Exception:
            pass
        for o in sel:
            try:
                o.select_set(True)
            except Exception:
                pass
        if sel:
            view_layer.objects.active = sel[0]
        try:
            bpy.ops.object.make_single_user(
                type='SELECTED_OBJECTS',
                object=True, obdata=True, material=False, animation=False)
        except Exception as e:
            self.report({'WARNING'}, "打断关联数据失败：%s" % e)

        # 重新收集（make_single_user 后引用仍有效，但保险起见按名称重取）
        targets = [o for o in context.selected_objects
                   if o.type in _CONVERTIBLE]
        if not targets:
            self.report({'WARNING'}, "合并中断：无有效目标")
            return {'CANCELLED'}

        # ── 2. 逐个 convert 到网格（按栈顺序应用全部修改器）───────────
        for o in list(targets):
            try:
                # 几何节点：先插 RealizeInstances，否则实例在 convert 时消失
                _ensure_realize_instances(o)
                bpy.ops.object.select_all(action='DESELECT')
                o.select_set(True)
                view_layer.objects.active = o
                if o.type != 'MESH' or o.modifiers:
                    bpy.ops.object.convert(target='MESH')
            except Exception:
                pass

        # convert 后当前场景中这些物体已是纯网格；重新收集仍存在的
        mesh_objs = [o for o in context.selected_objects if o.type == 'MESH']
        # convert 可能只保留了活动对象在选择里，兜底用名称集合重取
        if len(mesh_objs) < 2:
            mesh_objs = [o for o in view_layer.objects
                         if o in set(targets) and o.type == 'MESH']

        # ── 3. join 合并为一个物体 ─────────────────────────────────────
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except Exception:
            pass
        alive = [o for o in mesh_objs if o.name in bpy.data.objects]
        if not alive:
            self.report({'WARNING'}, "合并失败：转换后无网格物体")
            return {'CANCELLED'}
        for o in alive:
            try:
                o.select_set(True)
            except Exception:
                pass
        active = alive[0]
        view_layer.objects.active = active
        if len(alive) >= 2:
            try:
                bpy.ops.object.join()
            except Exception as e:
                self.report({'WARNING'}, "合并(join)失败：%s" % e)

        merged = view_layer.objects.active

        # ── 4. 原点置于底部中心 ────────────────────────────────────────
        if self.origin_bottom and merged is not None:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                merged.select_set(True)
                view_layer.objects.active = merged
            except Exception:
                pass
            _set_origin_to_bottom(context, merged)

        msg = "已合并为单一网格：%s" % (merged.name if merged else "?")
        if skipped:
            msg += "（已忽略 %d 个布尔切割体）" % skipped
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class QOPS_OT_clear_materials(bpy.types.Operator):
    """一键清空所选物体的所有材质槽"""
    bl_idname = "qops.clear_materials"
    bl_label = "清空材质槽"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT'
                and any(getattr(o, "material_slots", None)
                        for o in context.selected_objects))

    def execute(self, context):
        count = 0
        for o in context.selected_objects:
            slots = getattr(o, "material_slots", None)
            if not slots:
                continue
            try:
                o.data.materials.clear()   # 清空该数据块的全部材质槽
                count += 1
            except Exception:
                # 回退：逐个移除
                try:
                    while o.material_slots:
                        context.view_layer.objects.active = o
                        bpy.ops.object.material_slot_remove()
                    count += 1
                except Exception:
                    pass
        self.report({'INFO'}, "已清空 %d 个物体的材质槽" % count)
        return {'FINISHED'}


class QOPS_OT_select_controlling_objects(bpy.types.Operator):
    """选中控制当前物体的关联对象（曲线路径、几何节点输入对象等）"""
    bl_idname = "qops.select_controlling_objects"
    bl_label = "选中控制曲线/物体"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT'
                and bool(context.selected_objects))

    def execute(self, context):
        found = set()
        for o in context.selected_objects:
            found.update(_find_controlling_objects(o))
        if not found:
            self.report({'WARNING'}, "未找到控制曲线/物体（无 Array/Curve/几何节点输入引用）")
            return {'CANCELLED'}
        for o in found:
            try:
                o.select_set(True)
            except Exception:
                pass
        # 设最后找到的为活动物体
        last = list(found)[-1]
        try:
            context.view_layer.objects.active = last
        except Exception:
            pass
        self.report({'INFO'}, "已选中 %d 个控制物体：%s"
                    % (len(found), ", ".join(o.name for o in found)))
        return {'FINISHED'}


classes = (
    QOPS_OT_merge_export,
    QOPS_OT_clear_materials,
    QOPS_OT_select_controlling_objects,
)
