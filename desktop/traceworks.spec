# PyInstaller spec for the TraceWorks desktop app. Run through build.ps1,
# which builds the UI into userpage/out first.
#   pyinstaller desktop/traceworks.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH)
ROOT = HERE.parent
SERVER = ROOT / "serverside"
import sys
sys.path.insert(0, str(SERVER))  # so collect_submodules can find grbl/tracer

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("grbl", filter=lambda m: True)
    + collect_submodules("tracer", filter=lambda m: True)
    + ["sqlite_store", "multipart", "python_multipart"]
)

a = Analysis(
    [str(HERE / "app.py")],
    pathex=[str(SERVER)],
    datas=[(str(ROOT / "userpage" / "out"), "ui")],
    hiddenimports=hidden,
    # The CLI's preview plots and the test suite are not part of the app.
    excludes=["matplotlib", "tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TraceWorks",
    icon=str(HERE / "traceworks.ico"),
    console=False,
    upx=False,
)

# One folder, not one file: a one-file exe unpacks itself to %TEMP% on every
# launch, which is slow for a bundle with OpenCV and scikit-image in it. The
# installer hides the folder anyway.
coll = COLLECT(exe, a.binaries, a.datas, name="TraceWorks", upx=False)
