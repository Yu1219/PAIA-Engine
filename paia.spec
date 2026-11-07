# -*- mode: python ; coding: utf-8 -*-
"""
PAIA Engine — PyInstaller Spec File
Build with: pyinstaller paia.spec --noconfirm
"""

import os
import importlib

block_cipher = None

# ── Paths ──
APP_DIR = os.path.dirname(os.path.abspath(SPEC))

# ── Data files to bundle ──
app_datas = [
    (os.path.join(APP_DIR, 'app.py'), '.'),
    (os.path.join(APP_DIR, 'uniprot_fetcher.py'), '.'),
    (os.path.join(APP_DIR, 'visualizations.py'), '.'),
    (os.path.join(APP_DIR, 'annotation_details.py'), '.'),
    (os.path.join(APP_DIR, 'annotation_workflow.py'), '.'),
    (os.path.join(APP_DIR, 'gui_helpers.py'), '.'),
    (os.path.join(APP_DIR, 'test_data'), 'test_data'),
    (os.path.join(APP_DIR, 'style.css'), '.'),
]

# ── Collect entire packages that have data files ──
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

streamlit_datas, streamlit_binaries, streamlit_hiddenimports = collect_all('streamlit')
plotly_datas, plotly_binaries, plotly_hiddenimports = collect_all('plotly')

all_datas = app_datas + streamlit_datas + plotly_datas
all_binaries = streamlit_binaries + plotly_binaries

# ── Hidden imports ──
hidden_imports = streamlit_hiddenimports + plotly_hiddenimports + [
    'aiohttp',
    'annotation_details',
    'annotation_workflow',
    'gui_helpers',
    'uniprot_fetcher',
    'visualizations',
    'aiohttp.web',
    'aiosignal',
    'frozenlist',
    'multidict',
    'yarl',
    'async_timeout',
    'pandas',
    'pandas._libs',
    'pandas._libs.tslibs',
    'pyarrow',
    'openpyxl',
    'streamlit.runtime.scriptrunner',
    'streamlit.runtime.scriptrunner.script_runner',
    'streamlit.web.cli',
    'streamlit.web.server',
    'streamlit.web.bootstrap',
    'altair',
    'jinja2',
    'markupsafe',
    'packaging',
    'importlib_metadata',
    'pydeck',
    'PIL',
]

a = Analysis(
    [os.path.join(APP_DIR, 'launcher.py')],
    pathex=[APP_DIR],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'matplotlib',
        'scipy',
        'IPython',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PAIA_Engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,     # Keep console visible so users see status messages
    icon=None,        # Add a .ico file path here if you want a custom icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PAIA_Engine',
)
