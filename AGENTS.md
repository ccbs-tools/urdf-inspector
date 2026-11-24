# urdf-inspector — AI 协作说明

本项目遵循 CCBS 桌面工具统一规范（Python + PySide6 + uv + PyInstaller + GitHub Actions），
本项目的组织取值（规范 §0）：ORG = `ccbs`，GH_ORG = `ccbs-tools`。

- 完整规范：`../dev-rules/CONVENTIONS.md`（与本仓库同级的 `dev-rules` 目录）。
- 可复制的模板文件：`../dev-rules/templates/`。
- 如果 `../dev-rules` 不存在：`git clone https://github.com/ccbs-tools/dev-rules.git ../dev-rules`。

改动涉及下列内容前先读规范对应章节：界面文案（i18n）、日志、版本号与 `changelog.py`、`main.spec` 打包、`.github/workflows/build.yml`、README 结构。

要点速记：

- 界面文字全部走 `urdf_inspector/i18n.py` 的 `tr()`，中英两张表键一致；控件文字在 `retranslate()` 里设置。
- 日志用 `from .log import logger`，文本英文，不记录任何秘密。
- 发版改三处版本号：`urdf_inspector/__init__.py`、`pyproject.toml`、`changelog.py` 的 `RELEASES`；推 `vX.Y.Z` tag 触发 CI。
- 代码注释与 docstring 用中文。

## 与规范的差异

只记当前仍存在、有意保留的差异；每条注明违反的章节与原因，对齐后删除。迁移说明写 `changelog.py` 的 `RELEASES`。

- §4 文案键名：除规范列出的 `menu.*` / `dialog.*` / `status.*` / `chg.*` / `upd.*` 外，还按功能区用了 `opts.*`（显示选项）、`geom.*`（连杆几何）、`joints.*`、`path.*`、`stl.*`（STL 预览）、`view.*`（仿真视口）。键已稳定、含义清楚，不为改名而改名。
- §4 少量技术术语不翻译、直接写在代码里：几何树的 `visual` / `collision`（URDF 标签名）、STL 预览标题里的 `faces`。
- §10 `meshio.py` 抛出的 `ValueError` 文本是中文，会经 `stl.load_fail_box` / `stl.load_fail_status` 显示给用户，没有走 `tr()`。这些是底层读网格的错误，出现频率低，暂不拆成文案键。
- §11 仿真视口只有鼠标操作和双击复位，没有 `F` / `W` / `G` / `A` / `R` 快捷键（STL 预览有）；仿真视口的线框、网格开关没有对应功能。
- §11 不设置 `QSurfaceFormat`：本工具不用 `QOpenGLWidget`，两个视口都是 MuJoCo 离屏渲染后用 `QPainter` 贴图（Qt 的 GL 上下文会和 MuJoCo 的 GLFW 上下文互抢，见 `stl_view.py` 开头）。
- 入口与模板不同：`__main__.py` 用 `argparse` 解析可选的 `[file]` 参数（模板直接取 `argv[0]`），主窗口构造不带初始文件、由入口调用 `load_model()`。

## 本项目特有的注意点

- Python 固定 3.12（`.python-version`），本地 uv 和 CI 的 `uv sync` 都读它；`requires-python` 仍按规范写 `>=3.12`。
- mujoco 4.x 拆成 `mujoco-core` / `mujoco-studio` 等包并装进同一个 `mujoco/` 目录；`main.spec` 里的 `_MJ_DROP` 把 Studio、文档、头文件等剔出打包。升级 mujoco 后要重新打包并实际运行一次 exe 确认。
- 模型按 XML 根标签分两条路（`model.detect_format()`）：URDF 走 `_build_urdf()`，按本工具的约定重建；MJCF 走 `_build_mjcf()`，只看不动——只允许加不影响物理的显示内容，不要在这里改碰撞位、执行器、阻尼、关键帧，也不要给 MJCF 加关节滑条 / 物理步进（要支持得另外设计：模型自带执行器、速度环、自由关节、`weld` 约束都要处理）。
- `viewport.close_renderer()` 依赖 `mujoco.Renderer` 的私有属性 `_gl_context`（4.0.1 仍存在），升级 mujoco 时留意。
