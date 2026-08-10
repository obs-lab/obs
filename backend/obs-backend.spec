from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

datas = []
binaries = []
hiddenimports = []

datas += [("../frontend", "frontend")]
datas += [("../docker", "docker")]

for pkg in ["torch", "faiss", "sentence_transformers", "transformers",
            "tokenizers", "safetensors", "scipy", "sklearn", "spacy",
            "thinc", "srsly", "catalogue", "blis", "cymem", "preshed",
            "wasabi", "umap", "numba", "llvmlite", "huggingface_hub"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

hiddenimports += collect_submodules("sklearn")
hiddenimports += collect_submodules("scipy")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.tests", "PyQt5", "PySide2"],
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
    name="obs-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="obs-backend",
)
