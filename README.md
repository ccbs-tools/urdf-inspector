# urdf inspector

**English** | [中文](README.zh.md)

Drag a URDF into a self-drawn Qt window to inspect it (MuJoCo off-screen rendering, no native
`mujoco.viewer`). Pick a link's visual/collision to highlight it in the sim and preview its STL,
drag joint sliders, and toggle coordinate frames / grid. The menu bar switches between English and
Chinese at runtime.

| Empty window (drop target) | URDF loaded |
|---|---|
| ![Empty view](assets/soft-empty-view.png) | ![Loaded view](assets/open-urdf-view.png) |

### Demo

https://private-user-images.githubusercontent.com/34444109/694283238-976c9b32-3dbb-42fb-b1d3-9996dcee1c40.mp4

Dependencies: mujoco (4.x), numpy, PySide6, loguru. Python 3.12.
Open-source repo: [ccbs-tools/urdf-inspector](https://github.com/ccbs-tools/urdf-inspector).

## Download

Grab the latest `urdf-inspector-vX.Y.Z-windows-x64.zip` from
[Releases](https://github.com/ccbs-tools/urdf-inspector/releases), unzip anywhere and run
`urdf-inspector.exe`. No installation required; `SHA256SUMS.txt` next to it lets you verify the download.

Requirements: Windows 10/11 x64.

## Install

Needs [uv](https://docs.astral.sh/uv/) (it will fetch Python 3.12 itself, see `.python-version`):

```powershell
git clone https://github.com/ccbs-tools/urdf-inspector.git
cd urdf-inspector
uv sync
```

## Run

```powershell
uv run urdf-inspector
# or
uv run python -m urdf_inspector path/to/robot.urdf
```

## Layout

- **Left** (vertical scroll): display options → link geometry tree (click to highlight and preview the matching STL) → joint sliders
- **Top-right**: MuJoCo URDF simulation viewport (drop a `.urdf`, or File → Open)
- **Bottom-right**: STL preview (origin XYZ axes + ground grid)

## Controls

Both viewports: left drag rotate, right drag pan, wheel zoom, double-click reset.
The STL preview also supports `F` fit, `W` wireframe, `G` grid, `A` axes.
A `.urdf` can be dropped anywhere on the window; `Ctrl+O` opens the file dialog.

## Package (onedir)

```powershell
uv sync --group dev
uv run pyinstaller main.spec --noconfirm
# Output: dist/urdf-inspector/urdf-inspector.exe, with dependencies in urdf-inspector-lib/
```

## Structure

```
urdf_inspector/
  __main__.py        entry point main()
  main_window.py     main window: options / geometry tree / joints / help menu
  viewport.py        MuJoCo URDF simulation viewport
  stl_view.py        STL preview (off-screen render)
  model.py           URDF → MuJoCo model build, view options
  meshio.py          mesh loading (STL / DAE …)
  i18n.py            language strings and runtime switching
  icons.py           application icon
  log.py             loguru logging (%APPDATA%\ccbs\urdf-inspector\logs\app.log)
  changelog.py       version history & update check
  version_dialogs.py version info / update-check dialogs
assets/              icon.ico / icon.png and README screenshots
run.py               PyInstaller entry
main.spec            PyInstaller config
.github/workflows/build.yml  Windows packaging & Release
```
