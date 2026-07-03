# -*- coding: utf-8 -*-
"""
3DCoat 互导 · 发送 / 取回算子
=============================
严格按官方 io_coat3D 的 vox（体素）工作流实现，只保留两件事：
把选中网格作为体素物体发送到 3DCoat；从 3DCoat 取回更新后的模型。

协议要点（照官方源码）：
- 发送：FBX 导出到 ApplinkObjects/3DC000.fbx；写 Exchange/import.txt，内容三行：
    <fbx路径>
    <fbx路径>
    [vox]                 <- 关键：指令类型必须带方括号
  发送前先删掉 Exchange/export.txt（避免旧的回传标志干扰）。
- 取回：3DCoat 更新后会写 Exchange/export.txt；检测到就导入对应 FBX，
  导入后删除 export.txt。

缩放：
- 发送缩放 S（默认 0.01，与官方一致）；取回缩放独立可调（默认 0.01，官方值）。
  两者都在偏好设置里可改，用户可据实际往返结果自行标定，无需改代码。
"""

import os
import bpy

from .. import coat3d_link as link


def _prefs():
    return link.get_prefs()


def _send_scale():
    p = _prefs()
    s = getattr(p, "coat_send_scale", 0.01) if p else 0.01
    try:
        s = float(s)
    except Exception:
        s = 0.01
    return s if s > 0.0 else 0.01


def _getback_scale():
    p = _prefs()
    s = getattr(p, "coat_getback_scale", 0.01) if p else 0.01
    try:
        s = float(s)
    except Exception:
        s = 0.01
    return s if s > 0.0 else 0.01


def _send_to_origin():
    p = _prefs()
    return bool(getattr(p, "coat_send_to_origin", True)) if p else True


def _exchange(context):
    p = _prefs()
    manual = getattr(p, "coat_exchange_folder", "") if p else ""
    return link.resolve_exchange_folder(manual)


def _material_has_texture(mat):
    """材质是否含任何图像纹理节点。无纹理 = 3DCoat 的默认占位材质。"""
    if mat is None:
        return False
    try:
        if not mat.use_nodes or mat.node_tree is None:
            return False
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, "image", None) is not None:
                return True
    except Exception:
        return True  # 读不出来时保守保留
    return False


def _strip_empty_materials(obj):
    """清除物体上所有“无纹理”的材质槽（3DCoat 未上材质时的默认材质）。
    返回清除的数量。"""
    removed = 0
    try:
        slots = list(obj.material_slots)
    except Exception:
        return 0
    # 若所有材质都无纹理，则清空全部材质槽
    if slots and all(not _material_has_texture(sl.material) for sl in slots):
        try:
            obj.data.materials.clear()
            removed = len(slots)
        except Exception:
            removed = 0
    return removed


class QOPS_OT_coat_send(bpy.types.Operator):
    """把选中的网格作为体素物体发送到 3DCoat"""
    bl_idname = "qops.coat_send"
    bl_label = "发送到 3DCoat"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(
            o.type == 'MESH' for o in context.selected_objects
        )

    def execute(self, context):
        exchange = _exchange(context)
        if not exchange:
            self.report({'ERROR'},
                        "未找到 3DCoat 交换文件夹，请在偏好设置里手动指定路径")
            return {'CANCELLED'}
        if not os.path.isdir(exchange):
            self.report({'ERROR'}, "交换文件夹不存在：%s" % exchange)
            return {'CANCELLED'}

        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({'WARNING'}, "请选中至少一个网格物体")
            return {'CANCELLED'}

        # 复刻官方握手：Exchange/Blender/ 下的 run.txt/extension.txt/preset.txt
        link.ensure_blender_handshake(exchange)

        # 发送前删掉旧的 export.txt（官方做法，避免旧回传标志干扰取回）
        old_export = os.path.join(exchange, "export.txt")
        try:
            if os.path.isfile(old_export):
                os.remove(old_export)
        except Exception:
            pass

        # 每个网格需要有 UV，否则 3DCoat 端可能异常（官方也会补 UV）
        for o in meshes:
            try:
                if len(o.data.uv_layers) == 0:
                    o.data.uv_layers.new(name='UVMap', do_init=False)
            except Exception:
                pass

        fbx_path = link.next_object_fbx_path()
        s = _send_scale()

        # 发送到原点：把选中物体的“几何中心”临时移到世界原点再导出，
        # 使模型在 3DCoat 里对齐到空间坐标原点；导出后还原 Blender 里的位置。
        # 用几何中心(世界包围盒中心)而非 location，这样物体原点(pivot)不在
        # 几何中心、或多物体时也能正确居中对齐。
        saved_locations = []
        if _send_to_origin():
            try:
                xs = []; ys = []; zs = []
                for o in meshes:
                    mw = o.matrix_world
                    for corner in o.bound_box:
                        wc = mw @ Vector((corner[0], corner[1], corner[2]))
                        xs.append(wc.x); ys.append(wc.y); zs.append(wc.z)
                if xs:
                    gx = (max(xs) + min(xs)) / 2.0
                    gy = (max(ys) + min(ys)) / 2.0
                    gz = (max(zs) + min(zs)) / 2.0
                    for o in meshes:
                        saved_locations.append((o, o.location.copy()))
                        o.location = (o.location[0] - gx,
                                      o.location[1] - gy,
                                      o.location[2] - gz)
            except Exception:
                pass

        try:
            # 参数与官方 io_coat3D 的 vox 导出行逐字一致（不传 object_types）
            bpy.ops.export_scene.fbx(
                filepath=fbx_path,
                global_scale=s,
                use_selection=True,
                use_mesh_modifiers=True,
                axis_forward='-Z',
                axis_up='Y',
            )
        except Exception as e:
            # 出错也要先还原位置
            for o, loc in saved_locations:
                try:
                    o.location = loc
                except Exception:
                    pass
            self.report({'ERROR'}, "FBX 导出失败：%s" % e)
            return {'CANCELLED'}

        # 还原物体在 Blender 里的原始位置
        for o, loc in saved_locations:
            try:
                o.location = loc
            except Exception:
                pass

        # 写 import.txt —— 与实测能用的 v0.6.3 完全一致：
        #   路径 + "\n路径" + "\n[vox]"，即行间带 \n、结尾【不】带换行。
        # 落点：默认按物体在 Blender 的世界坐标；勾选“发送到原点”则落到画布中心。
        import_txt = os.path.join(exchange, "import.txt")
        try:
            with open(import_txt, "w", encoding="utf-8") as f:
                f.write("%s" % fbx_path)
                f.write("\n%s" % fbx_path)
                f.write("\n[vox]")
        except Exception as e:
            self.report({'ERROR'}, "写入交换文件失败：%s" % e)
            return {'CANCELLED'}

        # 记录来源信息到第一个物体，便于日后扩展
        try:
            meshes[0].qops_coat.applink_name = meshes[0].name
            meshes[0].qops_coat.applink_scale = s
            meshes[0].qops_coat.applink_address = fbx_path
        except Exception:
            pass

        self.report({'INFO'},
                    "已发送 %d 个物体到 3DCoat（体素） | import.txt: %s"
                    % (len(meshes), import_txt))
        return {'FINISHED'}


class QOPS_OT_coat_getback(bpy.types.Operator):
    """从 3DCoat 取回已更新的模型（手动触发）"""
    bl_idname = "qops.coat_getback"
    bl_label = "从 3DCoat 取回"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        exchange = _exchange(context)
        if not exchange:
            self.report({'ERROR'},
                        "未找到 3DCoat 交换文件夹，请在偏好设置里手动指定路径")
            return {'CANCELLED'}

        export_txt = os.path.join(exchange, "export.txt")
        blender_export = os.path.join(exchange, "Blender", "export.txt")

        trigger = None
        if os.path.isfile(export_txt):
            trigger = export_txt
        elif os.path.isfile(blender_export):
            trigger = blender_export
        if trigger is None:
            self.report({'WARNING'}, "3DCoat 尚未发回模型（未找到 export.txt）")
            return {'CANCELLED'}

        # 确定要导入哪个 FBX（照官方 io_coat3D 做法）：
        # 读 export.txt 第一行，就是 3DCoat 保存回来的那个 fbx 的绝对路径。
        fbx_path = ""
        try:
            with open(trigger, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    cand = line.strip()
                    if cand:
                        # 有的行可能带 [xxx] 标记，只认 .fbx 结尾的路径
                        if cand.lower().endswith(".fbx") and os.path.isfile(cand):
                            fbx_path = cand
                            break
        except Exception:
            pass

        # 回退：export.txt 里没给出可用路径时，取对象目录里最新的 fbx
        if not fbx_path:
            d = link.applink_objects_dir()
            newest_t = -1
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    if fn.lower().endswith(".fbx"):
                        fp = os.path.join(d, fn)
                        try:
                            t = os.path.getmtime(fp)
                        except Exception:
                            continue
                        if t > newest_t:
                            newest_t = t
                            fbx_path = fp

        if not fbx_path or not os.path.isfile(fbx_path):
            self.report({'ERROR'}, "找不到 3DCoat 回传的 FBX 文件")
            return {'CANCELLED'}

        s = _getback_scale()
        before = set(bpy.data.objects.keys())
        try:
            bpy.ops.import_scene.fbx(
                filepath=fbx_path,
                global_scale=s,
                axis_forward='X',
                use_custom_normals=False,
            )
        except Exception as e:
            self.report({'ERROR'}, "FBX 导入失败：%s" % e)
            return {'CANCELLED'}

        after = set(bpy.data.objects.keys())
        new_names = list(after - before)
        p = _prefs()
        strip = bool(getattr(p, "coat_strip_empty_material", True)) if p else True

        new_objs = []
        for name in new_names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            new_objs.append(obj)
            try:
                obj.qops_coat.applink_mesh = True
            except Exception:
                pass
            if strip and obj.type == 'MESH':
                _strip_empty_materials(obj)

        # 取回后删除触发文件，避免重复导入
        for t in (export_txt, blender_export):
            try:
                if os.path.isfile(t):
                    os.remove(t)
            except Exception:
                pass

        self.report({'INFO'}, "已从 3DCoat 取回：%s" % os.path.basename(fbx_path))
        return {'FINISHED'}


class QOPS_OT_coat_detect_exchange(bpy.types.Operator):
    """自动探测 3DCoat 交换文件夹并填入设置"""
    bl_idname = "qops.coat_detect_exchange"
    bl_label = "自动探测交换文件夹"
    bl_options = {'REGISTER'}

    def execute(self, context):
        found = link.auto_detect_exchange()
        if not found:
            self.report({'WARNING'}, "未探测到默认交换文件夹，请手动指定")
            return {'CANCELLED'}
        p = _prefs()
        if p:
            p.coat_exchange_folder = found
        self.report({'INFO'}, "已找到：%s" % found)
        return {'FINISHED'}


classes = (
    QOPS_OT_coat_send,
    QOPS_OT_coat_getback,
    QOPS_OT_coat_detect_exchange,
)
