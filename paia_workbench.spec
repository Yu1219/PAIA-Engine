# -*- mode: python ; coding: utf-8 -*-
"""Build on the destination OS. No web assets or Python are fetched at runtime."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
datas = [(str(root / "desktop_ui"), "desktop_ui"), (str(root / "test_data"), "test_data")]
datas += collect_data_files("certifi")
a = Analysis([str(root / "paia_desktop.py")], pathex=[str(root)], datas=datas,
             hiddenimports=["openpyxl", "xlrd", "aiohttp.resolver"],
             excludes=["streamlit", "plotly", "pyarrow", "pytest", "tkinter", "matplotlib",
                       "scipy", "IPython", "notebook", "PyQt5", "PyQt6", "PySide6"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PAIA_Workbench",
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PAIA_Workbench")
