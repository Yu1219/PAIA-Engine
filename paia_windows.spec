# -*- mode: python ; coding: utf-8 -*-
"""Reproducible onedir entry point for the Python 3.14 source distribution."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / name), ".") for name in (
    "app.py", "annotation_details.py", "annotation_workflow.py", "gui_helpers.py",
    "uniprot_fetcher.py", "visualizations.py", "style.css")]
datas.append((str(root / "test_data"), "test_data"))
binaries = []
hiddenimports = ["aiohttp", "pandas", "numpy", "pyarrow", "openpyxl", "xlrd",
                 "annotation_details", "annotation_workflow", "gui_helpers",
                 "uniprot_fetcher", "visualizations"]
for package in ("streamlit", "plotly"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("streamlit", recursive=True)

a = Analysis([str(root / "launcher.py")], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             excludes=["pytest", "tkinter", "matplotlib", "scipy", "IPython", "notebook"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PAIA_Engine",
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PAIA_Engine")
