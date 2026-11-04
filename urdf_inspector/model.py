"""URDF → MuJoCo 模型（选项开关对应 mujoco_view.py 的可选项）。"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import mujoco
import numpy as np

from .meshio import inject_mesh_data, resolve_mesh_path

JOINT_COLORS = [
    [0.90, 0.20, 0.20, 1.0],
    [0.95, 0.55, 0.10, 1.0],
    [0.95, 0.90, 0.15, 1.0],
    [0.20, 0.75, 0.30, 1.0],
    [0.20, 0.45, 0.95, 1.0],
    [0.65, 0.30, 0.85, 1.0],
    [0.20, 0.80, 0.80, 1.0],
    [0.90, 0.40, 0.70, 1.0],
]

FRAME_AXES = (
    ("x", [1.0, 0.15, 0.15, 1.0], [0.7071068, 0.0, 0.7071068, 0.0]),
    ("y", [0.15, 0.85, 0.15, 1.0], [0.7071068, -0.7071068, 0.0, 0.0]),
    ("z", [0.15, 0.35, 1.0, 1.0], [1.0, 0.0, 0.0, 0.0]),
)

DEFAULT_KP = 80.0
DEFAULT_KV_RATIO = 0.1


@dataclass
class ViewOptions:
    show_collision: bool = False
    gravity: bool = True
    color_joints: bool = False
    show_com: bool = False
    show_frames: bool = False
    world_frame: bool = True
    alpha: float = 1.0  # 1 = 不透明；com/frames 时可自行调低


@dataclass
class JointInfo:
    name: str
    jtype: str          # hinge / slide / ...
    qposadr: int
    range: Tuple[float, float]
    is_angle: bool      # hinge → 度显示
    mimic_of: Optional[str] = None
    mimic_mult: float = 1.0
    mimic_offset: float = 0.0


@dataclass
class GeomInfo:
    """编译后的单个 geom，供按 link 浏览 / 高亮。"""

    geom_id: int
    body_name: str
    kind: str           # visual | collision
    name: str           # MuJoCo geom 名（可能为空）
    label: str          # 树上显示用
    mesh: str = ""
    mesh_path: Optional[Path] = None  # URDF 里的网格绝对路径（若有）


@dataclass
class BuiltModel:
    model: mujoco.MjModel
    data: mujoco.MjData
    joints: List[JointInfo] = field(default_factory=list)  # 可控制（不含 mimic 从动）
    all_joints: List[JointInfo] = field(default_factory=list)
    geoms: List[GeomInfo] = field(default_factory=list)
    urdf: Path = Path()
    # 编译刚完成时的外观快照，高亮可恢复
    rgba_base: Optional[np.ndarray] = None
    group_base: Optional[np.ndarray] = None


def catalogue_geoms(model: mujoco.MjModel) -> List[GeomInfo]:
    """按 body 归类 visual / collision（跳过地面等辅助 geom）。"""
    out: List[GeomInfo] = []
    for i in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
        if name == "floor":
            continue
        body_id = int(model.geom_bodyid[i])
        body_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id) or f"body{body_id}"
        contype = int(model.geom_contype[i])
        conaffinity = int(model.geom_conaffinity[i])
        # 我们的约定：碰撞 contype≠0；纯视觉 contype=conaffinity=0；地面等其它跳过
        if contype != 0:
            kind = "collision"
        elif conaffinity == 0:
            kind = "visual"
        else:
            continue

        mesh = ""
        if int(model.geom_type[i]) == int(mujoco.mjtGeom.mjGEOM_MESH):
            mid = int(model.geom_dataid[i])
            if mid >= 0:
                mesh = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mid) or ""

        label = name or mesh or f"geom_{i}"
        if not name and mesh:
            label = mesh
        out.append(
            GeomInfo(
                geom_id=i,
                body_name=body_name,
                kind=kind,
                name=name,
                label=label,
                mesh=mesh,
            )
        )
    return out


@dataclass
class LinkGeomEntry:
    label: str
    mesh_path: Optional[Path] = None


@dataclass
class LinkGeomOrder:
    """URDF 里一个 link 的 visual / collision 出现顺序。"""

    link: str
    visuals: List[LinkGeomEntry] = field(default_factory=list)
    collisions: List[LinkGeomEntry] = field(default_factory=list)


def _mesh_filename(geom_el: Optional[ET.Element]) -> str:
    if geom_el is None:
        return ""
    mesh = geom_el.find("mesh")
    if mesh is None:
        return ""
    return mesh.get("filename") or ""


def _resolve_mesh(urdf: Path, filename: str) -> Optional[Path]:
    if not filename:
        return None
    found = resolve_mesh_path(filename, [urdf.parent])
    if found is not None:
        return found
    return (urdf.parent / filename).resolve()


def parse_urdf_geom_order(urdf: Path) -> List[LinkGeomOrder]:
    """按 URDF 文档顺序：link 自上而下，其内 visual / collision 也按出现顺序。"""
    root = ET.parse(urdf).getroot()
    out: List[LinkGeomOrder] = []
    for link in root.findall("link"):
        name = link.get("name") or ""
        if not name:
            continue
        visuals: List[LinkGeomEntry] = []
        for v in link.findall("visual"):
            fn = _mesh_filename(v.find("geometry"))
            stem = Path(fn).stem if fn else ""
            vn = (v.get("name") or "").strip()
            visuals.append(
                LinkGeomEntry(
                    label=vn or stem or f"visual_{len(visuals)}",
                    mesh_path=_resolve_mesh(urdf, fn),
                )
            )
        collisions: List[LinkGeomEntry] = []
        for c in link.findall("collision"):
            fn = _mesh_filename(c.find("geometry"))
            stem = Path(fn).stem if fn else ""
            cn = (c.get("name") or "").strip()
            collisions.append(
                LinkGeomEntry(
                    label=cn or stem or f"collision_{len(collisions)}",
                    mesh_path=_resolve_mesh(urdf, fn),
                )
            )
        out.append(LinkGeomOrder(link=name, visuals=visuals, collisions=collisions))
    return out


def sort_geoms_by_urdf(geoms: List[GeomInfo], orders: List[LinkGeomOrder]) -> List[GeomInfo]:
    """把编译后的 geom 排成与 URDF 一致的顺序，并填上 mesh_path。"""
    if not orders:
        return geoms

    link_rank = {o.link: i for i, o in enumerate(orders)}
    v_rank: Dict[Tuple[str, str], int] = {}
    c_rank: Dict[Tuple[str, str], int] = {}
    v_path: Dict[Tuple[str, str], Optional[Path]] = {}
    c_path: Dict[Tuple[str, str], Optional[Path]] = {}
    for o in orders:
        for i, e in enumerate(o.visuals):
            v_rank[(o.link, e.label)] = i
            v_path[(o.link, e.label)] = e.mesh_path
        for i, e in enumerate(o.collisions):
            c_rank[(o.link, e.label)] = i
            c_path[(o.link, e.label)] = e.mesh_path

    def _keys(g: GeomInfo) -> List[str]:
        keys: List[str] = []
        for k in (g.label, g.name, g.mesh):
            if k and k not in keys:
                keys.append(k)
            if k:
                stem = Path(k).stem
                if stem and stem not in keys:
                    keys.append(stem)
        return keys

    def rank(g: GeomInfo) -> Tuple[int, int, int, int]:
        lr = link_rank.get(g.body_name, 10_000 + g.geom_id)
        table = v_rank if g.kind == "visual" else c_rank
        kind_ord = 0 if g.kind == "visual" else 1
        for k in _keys(g):
            if (g.body_name, k) in table:
                return (lr, kind_ord, table[(g.body_name, k)], g.geom_id)
        return (lr, kind_ord, 9_999, g.geom_id)

    ordered = sorted(geoms, key=rank)
    for g in ordered:
        paths = v_path if g.kind == "visual" else c_path
        for k in _keys(g):
            if (g.body_name, k) in paths:
                g.mesh_path = paths[(g.body_name, k)]
                break
    return ordered


def parse_mimics(urdf: Path) -> Dict[str, Tuple[str, float, float]]:
    """从动关节名 → (主关节, multiplier, offset)。"""
    out: Dict[str, Tuple[str, float, float]] = {}
    root = ET.parse(urdf).getroot()
    for j in root.findall("joint"):
        m = j.find("mimic")
        if m is None:
            continue
        name = j.get("name") or ""
        master = m.get("joint") or ""
        if not name or not master:
            continue
        out[name] = (master, float(m.get("multiplier", "1")), float(m.get("offset", "0")))
    return out


def _color_by_joint(spec: mujoco.MjSpec) -> None:
    idx = 0

    def walk(body, rgba):
        nonlocal idx
        for j in body.joints:
            if j.name:
                rgba = JOINT_COLORS[idx % len(JOINT_COLORS)]
                idx += 1
        if rgba is not None:
            for g in body.geoms:
                g.rgba = rgba
        for child in body.bodies:
            walk(child, rgba)

    walk(spec.worldbody, None)


def _set_alpha(spec: mujoco.MjSpec, alpha: float) -> None:
    a = float(min(max(alpha, 0.05), 1.0))
    for g in spec.geoms:
        if g.name == "floor":
            continue
        g.rgba = [g.rgba[0], g.rgba[1], g.rgba[2], a]


def _add_com_markers(spec: mujoco.MjSpec) -> None:
    model = spec.compile()
    for b in range(1, model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b)
        body = spec.body(name)
        if body is None or model.body_mass[b] <= 0.0:
            continue
        site = body.add_site()
        site.name = f"com_{name}"
        site.type = mujoco.mjtGeom.mjGEOM_SPHERE
        site.size = [0.007, 0.0, 0.0]
        site.pos = model.body_ipos[b]
        site.rgba = [0.0, 0.0, 0.0, 1.0]
        site.group = 1


def _add_frame_markers(spec: mujoco.MjSpec, length: float = 0.06, radius: float = 0.0025) -> None:
    for body in spec.bodies:
        if not body.name or body.name == "world":
            continue
        for axis, rgba, quat in FRAME_AXES:
            site = body.add_site()
            site.name = f"frame_{body.name}_{axis}"
            site.type = mujoco.mjtGeom.mjGEOM_CYLINDER
            site.size = [radius, length / 2, 0.0]
            site.pos = [
                length / 2 if axis == "x" else 0.0,
                length / 2 if axis == "y" else 0.0,
                length / 2 if axis == "z" else 0.0,
            ]
            site.quat = quat
            site.rgba = rgba
            site.group = 1


def _add_world_frame(spec: mujoco.MjSpec, length: float = 0.5, radius: float = 0.004) -> None:
    for axis, rgba, quat in FRAME_AXES:
        site = spec.worldbody.add_site()
        site.name = f"world_{axis}"
        site.type = mujoco.mjtGeom.mjGEOM_CYLINDER
        site.size = [radius, length / 2, 0.0]
        site.pos = [
            length / 2 if axis == "x" else 0.0,
            length / 2 if axis == "y" else 0.0,
            length / 2 if axis == "z" else radius,
        ]
        site.quat = quat
        site.rgba = rgba
        site.group = 1


def build_model(urdf: Path, opts: ViewOptions) -> BuiltModel:
    urdf = urdf.resolve()
    if not urdf.is_file():
        raise FileNotFoundError(urdf)

    mimics = parse_mimics(urdf)
    xml = urdf.read_text(encoding="utf-8")
    meshdir = urdf.parent.as_posix()
    inj = (
        f'<mujoco><compiler discardvisual="false" meshdir="{meshdir}" '
        f'strippath="false" balanceinertia="true" fusestatic="false"/></mujoco>'
    )
    xml = re.sub(r"(<robot[^>]*>)", r"\1" + inj, xml, count=1)
    spec = mujoco.MjSpec.from_string(xml)
    spec.modelname = urdf.stem

    # 由 Python 读网格并注入，绕过 MuJoCo 不支持中文/非 ASCII 路径的问题
    inject_mesh_data(spec, [urdf.parent])

    for g in spec.geoms:
        if g.contype != 0 or g.conaffinity != 0:
            g.contype, g.conaffinity = 1, 0
            if not opts.show_collision:
                g.group = 3

    if opts.color_joints:
        _color_by_joint(spec)

    alpha = opts.alpha
    if (opts.show_com or opts.show_frames) and alpha >= 0.99:
        alpha = 0.35
    if alpha < 0.99:
        _set_alpha(spec, alpha)

    floor = spec.worldbody.add_geom()
    floor.name = "floor"
    floor.type = mujoco.mjtGeom.mjGEOM_PLANE
    floor.size = [1.0, 1.0, 0.05]
    floor.rgba = [0.85, 0.85, 0.85, 1.0]
    floor.group = 2
    floor.contype, floor.conaffinity = 0, 1

    light = spec.worldbody.add_light()
    light.pos = [0.6, 0.6, 1.5]
    light.dir = [-0.4, -0.4, -1.0]
    light.castshadow = True
    spec.visual.headlight.ambient = [0.4, 0.4, 0.4]
    spec.visual.global_.offwidth = 1920
    spec.visual.global_.offheight = 1080

    joints_by_name = {j.name: j for j in spec.joints if j.name}

    # 给每个非固定、非 mimic 从动关节加位置伺服
    for name, j in joints_by_name.items():
        if name in mimics:
            continue
        # MjSpec joint type: 0 free, 1 ball, 2 slide, 3 hinge ...
        if int(j.type) not in (
            int(mujoco.mjtJoint.mjJNT_HINGE),
            int(mujoco.mjtJoint.mjJNT_SLIDE),
        ):
            continue
        kp = DEFAULT_KP
        kv = kp * DEFAULT_KV_RATIO
        act = spec.add_actuator()
        act.name = name
        act.target = name
        act.trntype = mujoco.mjtTrn.mjTRN_JOINT
        act.gaintype = mujoco.mjtGain.mjGAIN_FIXED
        act.biastype = mujoco.mjtBias.mjBIAS_AFFINE
        act.gainprm[0] = kp
        act.biasprm[1] = -kp
        act.biasprm[2] = -kv
        act.ctrlrange = j.range

    for slave, (master, mult, off) in mimics.items():
        if slave not in joints_by_name or master not in joints_by_name:
            continue
        eq = spec.add_equality()
        eq.type = mujoco.mjtEq.mjEQ_JOINT
        eq.name1 = master
        eq.name2 = slave
        eq.data[0:5] = [off, mult, 0.0, 0.0, 0.0]
        eq.name = f"mimic_{slave}"

    if opts.show_com:
        _add_com_markers(spec)
    if opts.show_frames:
        _add_frame_markers(spec)
    if opts.world_frame:
        _add_world_frame(spec)

    key = spec.add_key()
    key.name = "home"

    model = spec.compile()
    model.dof_armature[:] = 0.01
    model.dof_damping[:] = 0.2
    if not opts.gravity:
        model.opt.gravity[:] = 0.0

    data = mujoco.MjData(model)
    all_joints: List[JointInfo] = []
    controllable: List[JointInfo] = []

    for i in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i) or f"jnt{i}"
        jtype_id = int(model.jnt_type[i])
        if jtype_id not in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
            continue
        lo, hi = float(model.jnt_range[i][0]), float(model.jnt_range[i][1])
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            if jtype_id == int(mujoco.mjtJoint.mjJNT_HINGE):
                lo, hi = -math.pi, math.pi
            else:
                lo, hi = -0.2, 0.2
        is_angle = jtype_id == int(mujoco.mjtJoint.mjJNT_HINGE)
        mim = mimics.get(name)
        info = JointInfo(
            name=name,
            jtype="hinge" if is_angle else "slide",
            qposadr=int(model.jnt_qposadr[i]),
            range=(lo, hi),
            is_angle=is_angle,
            mimic_of=mim[0] if mim else None,
            mimic_mult=mim[1] if mim else 1.0,
            mimic_offset=mim[2] if mim else 0.0,
        )
        all_joints.append(info)
        if info.mimic_of is None:
            controllable.append(info)

    mujoco.mj_forward(model, data)
    model.key_qpos[0] = data.qpos
    if model.nu > 0:
        # 把当前 qpos 同步到 ctrl
        for info in controllable:
            aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, info.name)
            if aid >= 0:
                data.ctrl[aid] = data.qpos[info.qposadr]
        model.key_ctrl[0] = data.ctrl

    geoms = sort_geoms_by_urdf(catalogue_geoms(model), parse_urdf_geom_order(urdf))
    return BuiltModel(
        model=model,
        data=data,
        joints=controllable,
        all_joints=all_joints,
        geoms=geoms,
        urdf=urdf,
        rgba_base=np.array(model.geom_rgba, copy=True),
        group_base=np.array(model.geom_group, copy=True),
    )
