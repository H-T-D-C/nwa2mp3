# Windows x64, one-folder application bundle. Build from the repository root.
from pathlib import Path

root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(root / "nwa_gui.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "resources" / "tool_catalog.json"), "resources"),
        (str(root / "THIRD_PARTY_NOTICES.md"), "."),
        (str(root / "README.md"), "."),
        (str(root / "docs" / "SETUP.md"), "docs"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nwa2Mp3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Nwa2Mp3",
)
