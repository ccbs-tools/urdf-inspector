"""PyInstaller 打包入口（等价于 python -m urdf_inspector）。"""

from urdf_inspector.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
