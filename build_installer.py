"""Build SiliconForgeVLSI.exe and SiliconForgeVLSI_Setup.exe."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
DIST_APP = ROOT / "dist" / "SiliconForgeVLSI"
PAYLOAD_ZIP = ROOT / "build" / "payload.zip"
ICON_PATH = ROOT / "assets" / "siliconforge.ico"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main() -> None:
    # 1. Generate application icon
    run([str(PYTHON), str(ROOT / "installer" / "make_icon.py")])

    # 2. Build standalone app directory with PyInstaller (fast startup, no temp unpack delay)
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    run([
        str(PYTHON), "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name", "SiliconForgeVLSI",
        "--icon", str(ICON_PATH),
        "--add-data", "examples;examples",
        "--add-data", "assets;assets",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebEngineQuick",
        "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.QtPdfWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.Qt3DRender",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml",
        "main.py",
    ])

    # 3. Package dist/SiliconForgeVLSI into build/payload.zip
    PAYLOAD_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in DIST_APP.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(DIST_APP))

    # 4. Build single-file Setup.exe using Tkinter (excludes PySide6 so Setup.exe stays lean)
    run([
        str(PYTHON), "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--name", "SiliconForgeVLSI_Setup",
        "--icon", str(ICON_PATH),
        "--add-data", f"{PAYLOAD_ZIP};.",
        "--exclude-module", "PySide6",
        "--exclude-module", "shiboken6",
        "--exclude-module", "pytest",
        str(ROOT / "installer" / "setup_gui.py"),
    ])

    setup_exe = ROOT / "dist" / "SiliconForgeVLSI_Setup.exe"
    print(f"\nDONE! Installer built at: {setup_exe} ({setup_exe.stat().st_size / (1024*1024):.1f} MB)")


if __name__ == "__main__":
    main()
