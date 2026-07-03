# -*- coding: utf-8 -*-
"""
3DCoat 互导桥接 · 公共逻辑
==========================
复刻并简化 3DCoat 官方 AppLink 的通信机制，用于 Blender 与 3DCoat 4.5+ 之间
通过 FBX 双向互导（本插件只做“发送体素网格物体 / 取回”两件事）。

关键事实（据官方 io_coat3D 源码核实）：
- 通信靠一个 Exchange 交换文件夹。Blender 写 import.txt 让 3DCoat 打开模型；
  3DCoat 更新后写 export.txt（靠其修改时间 mtime 判断有无新数据）。
- 模型 FBX 不放在 Exchange 里，而是放独立对象目录，命名 3DC000.fbx / 3DC001.fbx …
- 缩放：官方那套“导出×0.01 / 导入×0.01 再除以存储 scale”在 3DCoat 逐对象自动
  缩放时不守恒，导致 0.07/0.017 这类漂移。本插件改为对称缩放：
  导出用 global_scale=S，取回用 global_scale=1/S，数学上保证往返尺寸守恒。
  配合 3DCoat 端 Fixed Scene Scale=100 + 米制，即可无需手动调缩放。

所有路径探测只用“我的文档”规律 + 手动指定兜底，不依赖环境变量/注册表
（官方也是这么做的）。
"""

import os
import bpy


# 插件自己的工作目录（缓存交换路径 + 存放导出的 FBX 对象文件）
def base_work_dir():
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    root = docs if os.path.isdir(docs) else home
    return os.path.join(root, "JPanel_3DCoat")


def official_dc2_dir():
    """官方 applink 的工作目录 ~/Documents/3DC2Blender（Win/mac）或 ~/3DC2Blender（Linux）。"""
    home = os.path.expanduser("~")
    if os.sys.platform in ('win32', 'darwin'):
        return os.path.join(home, "Documents", "3DC2Blender")
    return os.path.join(home, "3DC2Blender")


def official_exchange_cache_file():
    """官方 applink 缓存交换路径的文件；若官方 applink 用过，这里就是最准的来源。"""
    return os.path.join(official_dc2_dir(), "Exchange_folder.txt")


def applink_objects_dir():
    """导出的 FBX 模型存放目录（沿用官方 3DC2Blender/ApplinkObjects）。"""
    d = os.path.join(official_dc2_dir(), "ApplinkObjects")
    return d


def _exchange_cache_file():
    return os.path.join(base_work_dir(), "Exchange_folder.txt")


def _candidate_exchange_folders():
    """按官方命名规律列出候选 Exchange 目录（优先级从高到低）。"""
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    cands = []
    # 2021+ 固定位置
    cands.append(os.path.join(docs, "AppLinks", "3D-Coat", "Exchange"))
    # 旧版本号内嵌命名：3D-CoatV48 / V4 / V3 等（枚举常见）
    for ver in ("3D-CoatV48", "3D-CoatV49", "3D-CoatV4", "3D-CoatV3", "3D-CoatV2021"):
        cands.append(os.path.join(docs, ver, "Exchange"))
    # Linux 老规律（无 Documents）
    for ver in ("3D-CoatV4", "3D-CoatV3"):
        cands.append(os.path.join(home, ver, "Exchange"))
    return cands


def _read_path_file(f):
    try:
        if os.path.isfile(f):
            with open(f, "r", encoding="utf-8") as fp:
                # 官方写入时可能带行尾换行，strip 掉
                p = fp.read().strip()
            if p and os.path.isdir(p):
                return p
    except Exception:
        pass
    return ""


def read_cached_exchange():
    """
    读取已缓存的交换目录。优先级：
      1) 官方 applink 的缓存 ~/Documents/3DC2Blender/Exchange_folder.txt
         （若你的官方 applink 能用，这就是和它完全一致的正确路径）
      2) 本插件自己的缓存
    """
    p = _read_path_file(official_exchange_cache_file())
    if p:
        return p
    return _read_path_file(_exchange_cache_file())


def write_cached_exchange(path):
    try:
        os.makedirs(base_work_dir(), exist_ok=True)
        with open(_exchange_cache_file(), "w", encoding="utf-8") as fp:
            fp.write(os.path.abspath(path))
        return True
    except Exception:
        return False


def auto_detect_exchange():
    """探测磁盘上存在的 Exchange 目录；找到则返回路径并缓存，否则返回空串。"""
    for cand in _candidate_exchange_folders():
        if os.path.isdir(cand):
            write_cached_exchange(cand)
            return cand
    return ""


def resolve_exchange_folder(manual_path=""):
    """
    统一入口，按优先级返回可用的 Exchange 目录：
      1) 用户手动指定（存在即用）
      2) 插件缓存
      3) 自动探测默认位置
    找不到返回空串。
    """
    if manual_path:
        p = bpy.path.abspath(manual_path)
        if os.path.isdir(p):
            write_cached_exchange(p)
            return p
    cached = read_cached_exchange()
    if cached:
        return cached
    return auto_detect_exchange()


def get_prefs():
    """获取本插件的 AddonPreferences（可能为 None）。"""
    try:
        addon = bpy.context.preferences.addons.get(__package__)
        return addon.preferences if addon else None
    except Exception:
        return None


def next_object_fbx_path():
    """生成下一个不冲突的对象 FBX 路径（3DC000.fbx / 3DC001.fbx …）。"""
    d = applink_objects_dir()
    os.makedirs(d, exist_ok=True)
    i = 0
    while True:
        p = os.path.join(d, "3DC%.3d.fbx" % i)
        if not os.path.isfile(p):
            return p
        i += 1
        if i > 999:
            return os.path.join(d, "3DC999.fbx")


# -----------------------------------------------------------------------------
# 每物体附加数据（记录 applink 状态）
# -----------------------------------------------------------------------------
class QOPS_CoatObjectProps(bpy.types.PropertyGroup):
    applink_name: bpy.props.StringProperty(name="Applink 名称", default="")
    applink_address: bpy.props.StringProperty(name="FBX 路径", default="")
    applink_mesh: bpy.props.BoolProperty(name="来自3DCoat", default=False)
    applink_scale: bpy.props.FloatProperty(name="发送缩放", default=0.01)


def register_props():
    bpy.utils.register_class(QOPS_CoatObjectProps)
    bpy.types.Object.qops_coat = bpy.props.PointerProperty(type=QOPS_CoatObjectProps)


def unregister_props():
    try:
        del bpy.types.Object.qops_coat
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(QOPS_CoatObjectProps)
    except Exception:
        pass


def ensure_blender_handshake(exchange_folder):
    """
    复刻官方 folders.py：在 Exchange/Blender/ 下创建握手文件，
    让 3DCoat 把这次导入识别为完整的 Blender applink 会话
    （run.txt / extension.txt=fbx / preset.txt=Blender Cycles）。
    """
    try:
        blender_folder = os.path.join(exchange_folder, "Blender")
        if not os.path.isdir(blender_folder):
            os.makedirs(blender_folder)
        run_txt = os.path.join(blender_folder, "run.txt")
        if not os.path.isfile(run_txt):
            open(run_txt, "w").close()
        ext_txt = os.path.join(blender_folder, "extension.txt")
        with open(ext_txt, "w", encoding="utf-8") as f:
            f.write("fbx")
        preset_txt = os.path.join(blender_folder, "preset.txt")
        with open(preset_txt, "w", encoding="utf-8") as f:
            f.write("Blender Cycles")
        return True
    except Exception:
        return False
