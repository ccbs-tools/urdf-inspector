"""纯 Python 读取网格（STL / OBJ / DAE）→ 顶点、面索引。

MuJoCo 在 Windows 上用 ANSI fopen 打开网格文件，遇到中文等非 ASCII 路径会失败；
这里由 Python 读文件，再通过 MjSpec 的 uservert / userface 把数据交给 MuJoCo。
"""

from __future__ import annotations

import math
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

_VERTEX_RE = re.compile(rb"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)")


def _dedup(tri_verts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """按三角形展开的顶点 (3N,3) → 去重顶点 + 面索引 (N,3)。"""
    tri_verts = np.ascontiguousarray(tri_verts, dtype=np.float64)
    uniq, inv = np.unique(tri_verts, axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3).astype(np.int32)
    return uniq, faces


def load_stl(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            rec = np.frombuffer(data, dtype=dt, count=n, offset=84)
            return _dedup(rec["v"].reshape(-1, 3))
    nums = _VERTEX_RE.findall(data)
    if not nums or len(nums) % 3 != 0:
        raise ValueError("不是有效的 STL（既非二进制也无完整 vertex 行）")
    verts = np.array(nums, dtype=np.float64)
    return _dedup(verts)


def load_obj(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    verts = []
    faces = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            parts = line.split()
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif line.startswith("f "):
            idx = []
            for tok in line.split()[1:]:
                s = tok.split("/")[0]
                if not s:
                    continue
                i = int(s)
                idx.append(i - 1 if i > 0 else len(verts) + i)
            # 多边形扇形三角化
            for k in range(1, len(idx) - 1):
                faces.append([idx[0], idx[k], idx[k + 1]])
    if not verts or not faces:
        raise ValueError("OBJ 里没有顶点或面")
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int32)


def _dae_tag(el: ET.Element) -> str:
    return el.tag.split("}", 1)[-1]


def _dae_floats(text: Optional[str]) -> np.ndarray:
    return np.array((text or "").split(), dtype=np.float64)


def _dae_node_transform(node: ET.Element) -> np.ndarray:
    """按文档顺序把 <matrix>/<translate>/<rotate>/<scale> 合成 4x4。"""
    T = np.eye(4)
    for ch in node:
        tag = _dae_tag(ch)
        if tag == "matrix":
            M = _dae_floats(ch.text).reshape(4, 4)
        elif tag == "translate":
            M = np.eye(4)
            M[:3, 3] = _dae_floats(ch.text)[:3]
        elif tag == "rotate":
            x, y, z, deg = _dae_floats(ch.text)[:4]
            axis = np.array([x, y, z])
            n = np.linalg.norm(axis)
            if n < 1e-12:
                continue
            axis /= n
            a = math.radians(deg)
            c, s = math.cos(a), math.sin(a)
            K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            M = np.eye(4)
            M[:3, :3] = c * np.eye(3) + s * K + (1 - c) * np.outer(axis, axis)
        elif tag == "scale":
            M = np.diag([*_dae_floats(ch.text)[:3], 1.0])
        else:
            continue
        T = T @ M
    return T


def load_dae(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Collada：合并场景里所有 instance_geometry 的三角形（带 node 变换、单位、up_axis）。"""
    root = ET.parse(path).getroot()
    ns = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    q = (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)

    # --- 全局：单位、up_axis ---
    unit_scale = 1.0
    up_axis = "Y_UP"
    asset = root.find(q("asset"))
    if asset is not None:
        unit = asset.find(q("unit"))
        if unit is not None and unit.get("meter"):
            unit_scale = float(unit.get("meter"))
        up_axis = (asset.findtext(q("up_axis")) or "Y_UP").strip()

    # --- 几何体：id → (verts, faces) ---
    def parse_geometry(geo: ET.Element) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        mesh = geo.find(q("mesh"))
        if mesh is None:
            return None
        sources: Dict[str, np.ndarray] = {}
        for s in mesh.findall(q("source")):
            fa = s.find(q("float_array"))
            if fa is None:
                continue
            acc = s.find(f"{q('technique_common')}/{q('accessor')}")
            stride = int(acc.get("stride", "3")) if acc is not None else 3
            arr = _dae_floats(fa.text)
            sources[s.get("id") or ""] = arr.reshape(-1, stride)[:, :3] if stride >= 3 else arr.reshape(-1, stride)
        # <vertices> 把 VERTEX 语义映射到 POSITION source
        vert_pos: Dict[str, str] = {}
        for v in mesh.findall(q("vertices")):
            for inp in v.findall(q("input")):
                if inp.get("semantic") == "POSITION":
                    vert_pos[v.get("id") or ""] = (inp.get("source") or "").lstrip("#")

        all_v: List[np.ndarray] = []
        all_f: List[np.ndarray] = []
        base = 0
        for prim in mesh:
            tag = _dae_tag(prim)
            if tag not in ("triangles", "polylist", "polygons"):
                continue
            inputs = prim.findall(q("input"))
            if not inputs:
                continue
            stride = max(int(i.get("offset", "0")) for i in inputs) + 1
            vin = next((i for i in inputs if i.get("semantic") == "VERTEX"), None)
            if vin is None:
                continue
            voff = int(vin.get("offset", "0"))
            src_id = (vin.get("source") or "").lstrip("#")
            src_id = vert_pos.get(src_id, src_id)
            if src_id not in sources:
                continue
            verts = sources[src_id]

            # 取出每个多边形的顶点索引序列
            polys: List[np.ndarray] = []
            if tag == "polygons":
                polys = [np.array(p.text.split(), dtype=np.int64)[voff::stride] for p in prim.findall(q("p"))]
            else:
                p = prim.find(q("p"))
                if p is None or not (p.text or "").strip():
                    continue
                flat = np.array(p.text.split(), dtype=np.int64)[voff::stride]
                if tag == "triangles":
                    polys = list(flat.reshape(-1, 3))
                else:  # polylist
                    vcount = np.array((prim.findtext(q("vcount")) or "").split(), dtype=np.int64)
                    pos = 0
                    for n in vcount:
                        polys.append(flat[pos:pos + n])
                        pos += n
            faces: List[List[int]] = []
            for poly in polys:
                if len(poly) == 3:
                    faces.append([int(poly[0]), int(poly[1]), int(poly[2])])
                else:
                    for k in range(1, len(poly) - 1):     # 扇形三角化
                        faces.append([int(poly[0]), int(poly[k]), int(poly[k + 1])])
            if not faces:
                continue
            all_v.append(verts)
            all_f.append(np.asarray(faces, dtype=np.int64) + base)
            base += len(verts)
        if not all_f:
            return None
        return np.vstack(all_v), np.vstack(all_f)

    geoms: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for geo in root.iter(q("geometry")):
        gid = geo.get("id") or ""
        parsed = parse_geometry(geo)
        if parsed is not None:
            geoms[gid] = parsed

    nodes_by_id: Dict[str, ET.Element] = {n.get("id") or "": n for n in root.iter(q("node")) if n.get("id")}

    # --- 场景：递归收集 instance_geometry，叠加 node 变换 ---
    out_v: List[np.ndarray] = []
    out_f: List[np.ndarray] = []
    base = 0

    def emit(gid: str, T: np.ndarray) -> None:
        nonlocal base
        if gid not in geoms:
            return
        v, f = geoms[gid]
        vh = np.hstack([v, np.ones((len(v), 1))]) @ T.T
        out_v.append(vh[:, :3])
        out_f.append(f + base)
        base += len(v)

    def walk(node: ET.Element, parent_T: np.ndarray, depth: int = 0) -> None:
        if depth > 64:
            return
        T = parent_T @ _dae_node_transform(node)
        for ig in node.findall(q("instance_geometry")):
            emit((ig.get("url") or "").lstrip("#"), T)
        for inode in node.findall(q("instance_node")):
            ref = nodes_by_id.get((inode.get("url") or "").lstrip("#"))
            if ref is not None:
                walk(ref, T, depth + 1)
        for ch in node.findall(q("node")):
            walk(ch, T, depth + 1)

    scene_nodes = root.findall(f".//{q('library_visual_scenes')}/{q('visual_scene')}/{q('node')}")
    if scene_nodes:
        for n in scene_nodes:
            walk(n, np.eye(4))
    else:  # 没有场景：把所有几何体原样合并
        for gid in geoms:
            emit(gid, np.eye(4))

    if not out_f:
        raise ValueError("DAE 里没有三角形几何")
    verts = np.vstack(out_v) * unit_scale
    faces = np.vstack(out_f).astype(np.int32)
    # URDF/MuJoCo 约定 Z 朝上；Collada 默认 Y_UP 时按 ROS 惯例转成 Z_UP
    if up_axis.upper() == "Y_UP":
        verts = verts[:, [0, 2, 1]] * np.array([1.0, -1.0, 1.0])
    elif up_axis.upper() == "X_UP":
        verts = verts[:, [1, 2, 0]]
    return np.ascontiguousarray(verts), faces


def load_mesh(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (verts (N,3) float64, faces (M,3) int32)。不支持的格式抛 ValueError。"""
    suffix = path.suffix.lower()
    if suffix == ".stl":
        return load_stl(path)
    if suffix == ".obj":
        return load_obj(path)
    if suffix == ".dae":
        return load_dae(path)
    raise ValueError(f"不支持的网格格式：{suffix}")


def resolve_mesh_path(file: str, search_dirs: Iterable[Path]) -> Optional[Path]:
    """把 URDF 里的网格路径（可能带 package:// / file://、相对路径）解析成实际文件。"""
    if not file:
        return None
    f = file.strip()
    for prefix in ("file://", "package://", "model://"):
        if f.startswith(prefix):
            f = f[len(prefix):]
            break
    p = Path(f)
    if p.is_absolute() and p.is_file():
        return p
    dirs = list(search_dirs)
    for d in dirs:
        cand = (d / f).resolve()
        if cand.is_file():
            return cand
    # package://pkg/meshes/x.stl 这类：去掉包名后再在各目录（含上级）里找
    parts = Path(f).parts
    if len(parts) > 1:
        tail = Path(*parts[1:])
        for d in dirs:
            for base in (d, *d.parents):
                cand = (base / tail).resolve()
                if cand.is_file():
                    return cand
                cand = (base / parts[0] / tail).resolve()
                if cand.is_file():
                    return cand
    return None


def inject_mesh_data(spec, search_dirs: Iterable[Path]) -> int:
    """把 spec.meshes 里带文件名的网格改为 uservert/userface。返回成功注入的个数。

    失败（找不到文件 / 不支持格式）时保留 file 字段，交给 MuJoCo 自己处理。"""
    dirs = [Path(d) for d in search_dirs]
    count = 0
    for m in spec.meshes:
        file = m.file or ""
        if not file:
            continue
        path = resolve_mesh_path(file, dirs)
        if path is None:
            continue
        try:
            verts, faces = load_mesh(path)
        except Exception:  # noqa: BLE001
            continue
        m.uservert = verts.reshape(-1).tolist()
        m.userface = faces.reshape(-1).tolist()
        m.file = ""
        count += 1
    return count
