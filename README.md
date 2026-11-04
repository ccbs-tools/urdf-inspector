# urdf inspector

**English** | [中文](README.zh.md)

Drag a URDF into a self-drawn Qt window to inspect it (MuJoCo off-screen rendering, no native
`mujoco.viewer`). Pick a link's visual/collision to highlight it in the sim and preview its STL,
drag joint sliders, and toggle coordinate frames / grid. The menu bar switches between English and
Chinese at runtime.

Dependencies: mujoco, numpy, PySide6.

## Install

```bash
cd path/to/urdf-inspector
uv venv && uv pip install -e .
```

## Run

```bash
urdf-inspector
# or
python -m urdf_inspector path/to/robot.urdf
```

## Layout

- **Left** (vertical scroll): display options → link geometry tree (click to highlight and preview the matching STL) → joint sliders
- **Top-right**: MuJoCo URDF simulation viewport (drop a `.urdf`, or File → Open)
- **Bottom-right**: STL preview (origin XYZ axes + ground grid)

## Controls

Both viewports: left drag rotate, right drag pan, wheel zoom, double-click reset.
The STL preview also supports `F` fit, `W` wireframe, `G` grid, `A` axes.

## Package (onedir)

```bash
uv pip install pyinstaller
uv run pyinstaller urdf_inspector.spec --noconfirm
```

## Structure

```
urdf_inspector/
  __main__.py     entry point main()
  main_window.py  main window: options / geometry tree / joint control
  viewport.py     MuJoCo URDF simulation viewport
  stl_view.py     STL preview (off-screen render)
  model.py        URDF → MuJoCo model build, view options
  meshio.py       mesh loading (STL / DAE …)
  i18n.py         language strings and runtime switching
run.py            PyInstaller entry
urdf_inspector.spec  PyInstaller config
```
