# urdf inspector

[English](README.md) | **中文**

拖放 URDF 到自绘 Qt 窗口查看（MuJoCo 离屏渲染，不用原生 `mujoco.viewer`）。点选某个连杆的
visual/collision 可在仿真中高亮并预览对应 STL，拖动关节滑条，开关坐标系/网格。菜单栏支持中英文实时切换。
也可以拖入 MuJoCo 的 MJCF（`.xml`），以只看模式打开（见下文）。

| 空窗口（拖放区） | 已加载 URDF |
|---|---|
| ![空视图](assets/soft-empty-view.png) | ![加载视图](assets/open-urdf-view.png) |

### 演示

https://private-user-images.githubusercontent.com/34444109/694283238-976c9b32-3dbb-42fb-b1d3-9996dcee1c40.mp4

依赖：mujoco（4.x）、numpy、PySide6、loguru，Python 3.12。开源仓库：[ccbs-tools/urdf-inspector](https://github.com/ccbs-tools/urdf-inspector)。

## 下载

到 [Releases](https://github.com/ccbs-tools/urdf-inspector/releases) 下载最新的
`urdf-inspector-vX.Y.Z-windows-x64.zip`，解压到任意位置运行 `urdf-inspector.exe`。免安装；旁边的 `SHA256SUMS.txt` 可用来校验。

要求：Windows 10/11 x64。

## 安装

需要 [uv](https://docs.astral.sh/uv/)（会自动下载 Python 3.12，见 `.python-version`）：

```powershell
git clone https://github.com/ccbs-tools/urdf-inspector.git
cd urdf-inspector
uv sync
```

## 运行

```powershell
uv run urdf-inspector
# 或
uv run python -m urdf_inspector path/to/robot.urdf
# MJCF 同理
uv run python -m urdf_inspector path/to/scene.xml
```

## 布局

- **左**（竖向滚动）：显示选项 → 连杆几何树（点选高亮并预览对应 STL）→ 关节滑条
- **右上**：MuJoCo 仿真视口（拖入 `.urdf` / MJCF 的 `.xml`，或 文件 → 打开）
- **右下**：STL 预览（原点 XYZ 轴 + 地面网格）

## 操作

两个视口均可左键旋转、右键平移、滚轮缩放、双击复位；STL 预览还支持 `F` 适配、`W` 线框、`G` 网格、`A` 坐标轴。
`.urdf` / `.xml` 可以拖到窗口任意位置；`Ctrl+O` 打开文件对话框。

### MJCF（只看模式）

按文件的 XML 根标签区分格式：`<robot>` 是 URDF，`<mujoco>` 是 MJCF（与扩展名无关）。MJCF 以只看模式打开：

- 模型原样加载，不改碰撞设置、执行器、阻尼；没有关节滑条，「重力」「物理步进」「复位关节」不可用。
- 相机、几何树点选高亮、STL 预览可用；「显示碰撞体」「按关节染色」「质心」「坐标系」「透明度」也可用，它们只改显示。
- `<include>`、`<attach>` 的子模型、网格和贴图按文件所在目录解析。`<mujocoinclude>` 片段不能单独打开，请打开引用它的主文件。
- MJCF 没有 visual / collision 标签，几何树按默认是否显示来分：参与碰撞且在 group ≥ 3 的算 collision，其余算 visual。
- STL 预览直接取编译后模型里的网格；基本形状（box、cylinder 等）没有预览。
- 模型里没有地面或灯光时，会补一个只用于显示的地面 / 平行光。

## 打包（onedir）

```powershell
uv sync --group dev
uv run pyinstaller main.spec --noconfirm
# 输出 dist/urdf-inspector/urdf-inspector.exe，依赖在 urdf-inspector-lib/ 下
```

## 结构

```
urdf_inspector/
  __main__.py        入口 main()
  main_window.py     主窗口：显示选项 / 连杆几何树 / 关节控制 / 帮助菜单
  viewport.py        MuJoCo 仿真视口（URDF / MJCF）
  stl_view.py        STL 预览（离屏渲染）
  model.py           URDF / MJCF → MuJoCo 模型构建、显示选项
  meshio.py          网格读取（STL / DAE …）
  i18n.py            多语言字符串与运行时切换
  icons.py           应用图标
  log.py             loguru 日志（%APPDATA%\ccbs\urdf-inspector\logs\app.log）
  changelog.py       版本历史与检查更新
  version_dialogs.py 版本介绍 / 检查更新对话框
assets/              icon.ico / icon.png 与 README 截图
run.py               PyInstaller 入口
main.spec            PyInstaller 配置
.github/workflows/build.yml  Windows 打包与 Release
```
