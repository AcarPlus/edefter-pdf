"""Exe derlemesi ve GitHub release.

    .venv/Scripts/python build.py            # derle → build/eDefterPDF-windows.zip (+ .sha256)
    .venv/Scripts/python build.py --release  # derle + gh ile v<sürüm> release'i oluştur

Sürüm numarası version.py'den okunur; yeni sürümden önce orayı artırın.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from version import REPO, __version__  # noqa: E402

BUILD = ROOT / "build"
DIST = BUILD / "dist" / "eDefterPDF"
ZIP = BUILD / "eDefterPDF-windows.zip"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041F04B0', [
      StringStruct('CompanyName', 'AcarPlus'),
      StringStruct('FileDescription', 'e-Defter PDF'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'eDefterPDF'),
      StringStruct('LegalCopyright', 'AcarPlus'),
      StringStruct('OriginalFilename', 'eDefterPDF.exe'),
      StringStruct('ProductName', 'e-Defter PDF'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x041F, 1200])])
  ]
)
"""


def build() -> None:
    BUILD.mkdir(exist_ok=True)
    nums = [int(x) for x in __version__.split(".")] + [0] * 4
    vfile = BUILD / "version_info.txt"
    vfile.write_text(VERSION_INFO.format(t=tuple(nums[:4]), v=__version__), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "assets" / "make_icon.py")], check=True)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "eDefterPDF", "--icon", str(ROOT / "assets" / "app.ico"),
        "--version-file", str(vfile),
        "--add-data", f"{ROOT / 'xslt'};xslt", "--add-data", f"{ROOT / 'assets' / 'app.png'};assets",
        "--collect-all", "saxonche",
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        str(ROOT / "main.py"),
    ], check=True)


def package() -> None:
    ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(DIST.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(DIST.parent))
    digest = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    (BUILD / (ZIP.name + ".sha256")).write_text(f"{digest}  {ZIP.name}\n", encoding="ascii")
    print(f"Hazır: {ZIP} ({ZIP.stat().st_size // 1048576} MB)  sha256={digest[:16]}…")


def release(notes: str | None) -> None:
    body = notes or f"e-Defter PDF {__version__}"
    subprocess.run(["gh", "release", "create", f"v{__version__}", str(ZIP), str(BUILD / (ZIP.name + ".sha256")),
                    "--repo", REPO, "--title", f"e-Defter PDF v{__version__}", "--notes", body], check=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--notes-file")
    ap.add_argument("--skip-build", action="store_true")
    a = ap.parse_args()
    if not a.skip_build:
        build()
    package()
    if a.release:
        release(Path(a.notes_file).read_text(encoding="utf-8") if a.notes_file else None)
