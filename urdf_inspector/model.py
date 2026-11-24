"""URDF / MJCF → MuJoCo 模型（选项开关对应 mujoco_view.py 的可选项）。

入口是 build_model()，按 XML 根标签分两条路：

- URDF（<robot>）：按本工具的约定重建——统一碰撞位、给每个关节加位置伺服、覆盖阻尼等，
  可拖关节、可开物理。
- MJCF（<mujoco>）：只看不动——原样加载，不改碰撞位 / 执行器 / 阻尼 / 关键帧，
  只加不影响物理的显示内容（地面、灯光、坐标系标记），不提供关节滑条和物理步进。
"""

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

# 位置伺服增益：太小开物理时拖滑块会"软绵绵"追目标；太大易数值抖
DEFAULT_KP = 200.0
DEFAULT_KV_RATIO = 0.1

# MJCF 的离屏帧缓冲至少要这么大：视口按控件尺寸渲染，上限 1920×1200（见 viewport.py）
MJCF_OFF_W = 1920
MJCF_OFF_H = 1200


class ModelFormatError(ValueError):
    """文件不是能单独加载的 URDF / MJCF。

    code 对应界面文案键 `dialog.err_<code>`，params 是该文案的占位参数。"""

    def __init__(self, code: str, **params: str) -> None:
        super().__init__(f"{code} {params}" if params else code)
        self.code = code
        self.params = params


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
    mesh_id: int = -1   # 仅 MJCF：编译后模型里的网格 id，STL 预览用 mesh_arrays() 直接取数据


@dataclass
class BuiltModel:
    model: mujoco.MjModel
    data: mujoco.MjData
    joints: List[JointInfo] = field(default_factory=list)  # 可控制（不含 mimic 从动）
    all_joints: List[JointInfo] = field(default_factory=list)
    geoms: List[GeomInfo] = field(default_factory=list)
    path: Path = Path()
    kind: str = "urdf"  # urdf | mjcf（mjcf 只看不动：joints 为空，不步进物理）
    # 编译刚完成时的外观快照，高亮可恢复
    rgba_base: Optional[np.ndarray] = None
    group_base: Optional[np.ndarray] = None


def _geom_info(model: mujoco.MjModel, i: int, kind: str) -> GeomInfo:
    name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
    body_id = int(model.geom_bodyid[i])
    body_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id) or f"body{body_id}"
    mesh = ""
    mesh_id = -1
    if int(model.geom_type[i]) == int(mujoco.mjtGeom.mjGEOM_MESH):
        mesh_id = int(model.geom_dataid[i])
        if mesh_id >= 0:
            mesh = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh_id) or ""
    return GeomInfo(
        geom_id=i,
        body_name=body_name,
        kind=kind,
        name=name,
        label=name or mesh or f"geom_{i}",
        mesh=mesh,
        mesh_id=mesh_id,
    )


def catalogue_geoms(model: mujoco.MjModel) -> List[GeomInfo]:
    """URDF：按 body 归类 visual / collision（跳过地面等辅助 geom）。"""
    out: List[GeomInfo] = []
    for i in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or ""
        if name == "floor":
            continue
        contype = int(model.geom_contype[i])
        conaffinity = int(model.geom_conaffinity[i])
        # 我们的约定：碰撞 contype≠0；纯视觉 contype=conaffinity=0；地面等其它跳过
        if contype != 0:
            kind = "collision"
        elif conaffinity == 0:
            kind = "visual"
        else:
            continue
        info = _geom_info(model, i, kind)
        info.mesh_id = -1  # URDF 的 STL 预览走文件路径（mesh_path）
        out.append(info)
    return out


def catalogue_mjcf_geoms(model: mujoco.MjModel) -> List[GeomInfo]:
    """MJCF：按 body 归类，顺序就是模型里的顺序；平面（地面）不列。

    MJCF 没有 visual / collision 标签，这里按"默认看不看得见"来分：参与碰撞且放在默认
    不画的分组（group ≥ 3）里的算 collision，其余算 visual——包括既显示又参与碰撞的 geom。
    """
    out: List[GeomInfo] = []
    for i in range(model.ngeom):
        gtype = int(model.geom_type[i])
        if gtype == int(mujoco.mjtGeom.mjGEOM_PLANE):
            continue
        collides = int(model.geom_contype[i]) != 0 or int(model.geom_conaffinity[i]) != 0
        hidden = int(model.geom_group[i]) >= 3
        info = _geom_info(model, i, "collision" if collides and hidden else "visual")
        if not info.name and not info.mesh:
            # 没名字的基本形状：用形状名代替 geom_12 这种编号，树上好认
            shape = mujoco.mjtGeom(gtype).name.removeprefix("mjGEOM_").lower()
            info.label = f"{shape}_{i}"
        out.append(info)
    return out


def mesh_arrays(model: mujoco.MjModel, mesh_id: int) -> Tuple[np.ndarray, np.ndarray]:
    """取编译后模型里一个网格的 (verts (N,3) float64, faces (M,3) int32)，坐标同网格文件。

    编译时 MuJoCo 把顶点挪到了网格自己的惯性系（平移 mesh_pos、旋转 mesh_quat），这里还原回去，
    所以预览里的原点就是 geom 的坐标系原点。"""
    va, vn = int(model.mesh_vertadr[mesh_id]), int(model.mesh_vertnum[mesh_id])
    fa, fn = int(model.mesh_faceadr[mesh_id]), int(model.mesh_facenum[mesh_id])
    verts = np.array(model.mesh_vert[va:va + vn], dtype=np.float64)
    faces = np.array(model.mesh_face[fa:fa + fn], dtype=np.int32)
    rot = np.zeros(9)
    mujoco.mju_quat2Mat(rot, model.mesh_quat[mesh_id])
    verts = verts @ rot.reshape(3, 3).T + model.mesh_pos[mesh_id]
    return np.ascontiguousarray(verts), faces


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


def _add_com_markers(spec: mujoco.MjSpec, *, named: bool = True) -> None:
    """named=False：标记不起名（MJCF 用，避免和模型自带的 site 重名）。下面两个函数同理。"""
    model = spec.compile()
    for b in range(1, model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b)
        if not name:
            continue
        body = spec.body(name)
        if body is None or model.body_mass[b] <= 0.0:
            continue
        site = body.add_site()
        if named:
            site.name = f"com_{name}"
        site.type = mujoco.mjtGeom.mjGEOM_SPHERE
        site.size = [0.007, 0.0, 0.0]
        site.pos = model.body_ipos[b]
        site.rgba = [0.0, 0.0, 0.0, 1.0]
        site.group = 1


def _add_frame_markers(
    spec: mujoco.MjSpec, length: float = 0.06, radius: float = 0.0025, *, named: bool = True
) -> None:
    for body in spec.bodies:
        if body.name == "world" or (named and not body.name):
            continue
        for axis, rgba, quat in FRAME_AXES:
            site = body.add_site()
            if named:
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


def _add_world_frame(
    spec: mujoco.MjSpec, length: float = 0.5, radius: float = 0.004, *, named: bool = True
) -> None:
    for axis, rgba, quat in FRAME_AXES:
        site = spec.worldbody.add_site()
        if named:
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


def detect_format(path: Path) -> str:
    """按 XML 根标签判断格式：<robot> → "urdf"，<mujoco> → "mjcf"。

    不看扩展名（URDF 也有用 .xml 的）。<mujocoinclude> 片段、其它根标签抛 ModelFormatError。"""
    tag = ""
    try:
        with path.open("rb") as f:
            for _, el in ET.iterparse(f, events=("start",)):
                tag = el.tag.rsplit("}", 1)[-1]  # 去掉可能的命名空间前缀
                break
    except ET.ParseError as exc:
        raise ModelFormatError("bad_xml", err=str(exc)) from exc
    if tag == "robot":
        return "urdf"
    if tag == "mujoco":
        return "mjcf"
    if tag == "mujocoinclude":
        raise ModelFormatError("fragment")
    raise ModelFormatError("unknown_root", tag=tag)


def build_model(path: Path, opts: ViewOptions) -> BuiltModel:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if detect_format(path) == "mjcf":
        return _build_mjcf(path, opts)
    return _build_urdf(path, opts)


def _bake_material_rgba(model: mujoco.MjModel) -> None:
    """把材质颜色写进 geom_rgba，渲染结果不变。

    geom 用材质且自己的 rgba 是默认值时，颜色取自材质；之后只要改 geom_rgba 的任一分量
    （调透明度、高亮时压暗），MuJoCo 就改用 geom_rgba，颜色会变成默认的灰。先写进去就不会。"""
    default = np.array([0.5, 0.5, 0.5, 1.0], dtype=model.geom_rgba.dtype)
    use_mat = (model.geom_matid >= 0) & (model.geom_rgba == default).all(axis=1)
    model.geom_rgba[use_mat] = model.mat_rgba[model.geom_matid[use_mat]]


def _build_mjcf(path: Path, opts: ViewOptions) -> BuiltModel:
    """MJCF 只看不动：原样加载，只加不影响物理的显示内容。gravity 选项在这里不起作用。"""
    # 用 from_file 而不是读成字符串：<include> / <model file=...> / meshdir 都相对文件所在目录
    spec = mujoco.MjSpec.from_file(str(path))

    if opts.color_joints:
        _color_by_joint(spec)

    plane = int(mujoco.mjtGeom.mjGEOM_PLANE)
    added_floor = not any(int(g.type) == plane for g in spec.geoms)
    if added_floor:
        floor = spec.worldbody.add_geom()  # 不起名，避免和模型里的名字撞
        floor.type = mujoco.mjtGeom.mjGEOM_PLANE
        floor.size = [1.0, 1.0, 0.05]
        floor.rgba = [0.85, 0.85, 0.85, 1.0]
        floor.group = 2
        floor.contype, floor.conaffinity = 0, 0
    if not list(spec.lights):
        # 平行光：模型大小不定，不像 URDF 那样把点光源放在固定位置
        light = spec.worldbody.add_light()
        light.type = mujoco.mjtLightType.mjLIGHT_DIRECTIONAL
        light.dir = [-0.4, -0.4, -1.0]
        light.castshadow = True
    glob = spec.visual.global_
    glob.offwidth = max(int(glob.offwidth), MJCF_OFF_W)
    glob.offheight = max(int(glob.offheight), MJCF_OFF_H)

    if opts.show_com:
        _add_com_markers(spec, named=False)
    if opts.show_frames:
        _add_frame_markers(spec, named=False)
    if opts.world_frame:
        _add_world_frame(spec, named=False)

    model = spec.compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    is_plane = model.geom_type == plane
    if added_floor:
        # 我们加的地面按模型范围放大（平面的显示大小在渲染时取 geom_size）
        model.geom_size[is_plane, :2] = max(1.0, float(model.stat.extent))

    _bake_material_rgba(model)
    alpha = opts.alpha
    if (opts.show_com or opts.show_frames) and alpha >= 0.99:
        alpha = 0.35
    if alpha < 0.99:
        # 乘而不是直接设：保留模型里本来就半透明 / 全透明的 geom 的相对透明度
        model.geom_rgba[~is_plane, 3] *= float(min(max(alpha, 0.05), 1.0))

    geoms = catalogue_mjcf_geoms(model)
    if opts.show_collision:
        # 分组只影响显示，不影响物理
        for g in geoms:
            if g.kind == "collision":
                model.geom_group[g.geom_id] = 0

    return BuiltModel(
        model=model,
        data=data,
        geoms=geoms,
        path=path,
        kind="mjcf",
        rgba_base=np.array(model.geom_rgba, copy=True),
        group_base=np.array(model.geom_group, copy=True),
    )


def _merge_compiler_tag(tag: str, attrs: Dict[str, str]) -> str:
    """把 attrs 合并进已有的 <compiler ...> 标签（同名属性以 attrs 为准）。"""
    existing = dict(re.findall(r'([\w:]+)="([^"]*)"', tag))
    existing.update(attrs)
    body = " ".join(f'{k}="{v}"' for k, v in existing.items())
    return f"<compiler {body}/>"


def _ensure_urdf_mujoco_compiler(xml: str, meshdir: str) -> str:
    """保证 URDF 里有且仅有一个带 meshdir 等属性的 <mujoco><compiler/>。

    文件里已有 <mujoco> 时合并进现有 <compiler>（没有则插入），避免 MuJoCo 报
    repeated element: 'mujoco'。"""
    attrs = {
        "discardvisual": "false",
        "meshdir": meshdir,
        "strippath": "false",
        "balanceinertia": "true",
        "fusestatic": "false",
    }
    compiler = _merge_compiler_tag("<compiler/>", attrs)
    if re.search(r"<mujoco[\s>]", xml):
        if re.search(r"<compiler\b", xml):
            return re.sub(
                r"<compiler\b[^>]*?/?>",
                lambda m: _merge_compiler_tag(m.group(0), attrs),
                xml,
                count=1,
            )
        return re.sub(r"(<mujoco\b[^>]*>)", r"\1" + compiler, xml, count=1)
    return re.sub(
        r"(<robot[^>]*>)",
        r"\1" + f"<mujoco>{compiler}</mujoco>",
        xml,
        count=1,
    )


def _build_urdf(urdf: Path, opts: ViewOptions) -> BuiltModel:
    mimics = parse_mimics(urdf)
    xml = urdf.read_text(encoding="utf-8")
    meshdir = urdf.parent.as_posix()
    xml = _ensure_urdf_mujoco_compiler(xml, meshdir)
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
        path=urdf,
        rgba_base=np.array(model.geom_rgba, copy=True),
        group_base=np.array(model.geom_group, copy=True),
    )
