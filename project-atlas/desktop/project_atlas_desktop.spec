# PyInstaller spec for the "Project Atlas" desktop application (one-folder bundle).
# Build:  scripts/build_desktop.sh   (copies the built UI into the package first)
# The bundle contains Python, all dependencies, the UI and migrations; no network access is needed at runtime.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = collect_submodules("project_atlas") + collect_submodules("uvicorn") + ["argon2._ffi", "duckdb", "pyarrow.vendored.version"]
datas = collect_data_files("project_atlas", include_py_files=True) + collect_data_files("reportlab") + collect_data_files("tzdata")

a = Analysis(["launch.py"], pathex=[], hiddenimports=hidden, datas=datas, excludes=["tkinter", "matplotlib", "IPython", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Project Atlas", icon="atlas.ico", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="Project Atlas")
