"""GitHub Releases üzerinden otomatik güncelleme.

Akış: son sürüm denetlenir → zip arka planda indirilip SHA-256 ile doğrulanır → geçici klasöre açılır.
Uygulama kapanırken (veya "Yeniden başlat" ile) yeni exe `--apply-update` ile çalıştırılır; eski süreç
bitince kurulum klasöründeki dosyaları değiştirir. Yalnızca paketlenmiş (exe) sürümde çalışır.
Belge içeriği hiçbir zaman gönderilmez; internete sadece sürüm bilgisi ve güncelleme dosyası için çıkılır.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import zipfile
from pathlib import Path

from version import REPO, __version__

EXE_NAME = "eDefterPDF.exe"
ASSET = "eDefterPDF-windows.zip"
# EDEFTER_UPDATE_API yalnızca güncelleme akışını yerel sunucuyla test etmek içindir
API = os.environ.get("EDEFTER_UPDATE_API") or f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
STAGE_ROOT = Path(tempfile.gettempdir()) / "eDefterPDF-update"
LOG = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "eDefterPDF" / "update.log"


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> bool:
    """Kurulum klasörü yazılabilir mi (ör. Program Files değilse)?"""
    if not is_frozen():
        return False
    probe = install_dir() / ".update-probe"
    try:
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def _get(url: str, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": f"eDefterPDF/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check() -> dict | None:
    """Daha yeni bir sürüm varsa bilgisini döndürür."""
    with _get(API) as r:
        data = json.load(r)
    tag = data.get("tag_name", "")
    if not tag or parse_version(tag) <= parse_version(__version__):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    if ASSET not in assets or ASSET + ".sha256" not in assets:
        return None
    return {"version": tag.lstrip("vV"), "zip": assets[ASSET], "sha": assets[ASSET + ".sha256"],
            "notes": data.get("body") or ""}


def download(info: dict, progress=lambda done, total: None) -> Path:
    """Zip'i indirir, doğrular, açar; açılan yeni exe'nin yolunu döndürür."""
    base = STAGE_ROOT / info["version"]
    exe = base / "app" / "eDefterPDF" / EXE_NAME
    if (base / "ready").exists() and exe.exists():
        return exe
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    with _get(info["sha"]) as r:
        expected = r.read().decode("ascii", "replace").split()[0].lower()
    zpath = base / ASSET
    h = hashlib.sha256()
    with _get(info["zip"], timeout=60) as r, open(zpath, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            out.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, total)
    if h.hexdigest() != expected:
        shutil.rmtree(base, ignore_errors=True)
        raise RuntimeError("İndirilen güncelleme doğrulanamadı (SHA-256 uyuşmuyor)")
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(base / "app")
    zpath.unlink()
    if not exe.exists():
        raise RuntimeError("Güncelleme paketinde uygulama bulunamadı")
    (base / "ready").write_text(info["version"])
    log(f"{info['version']} indirildi ve doğrulandı")
    return exe


def launch_apply(staged_exe: Path, restart: bool) -> None:
    args = [str(staged_exe), "--apply-update", str(install_dir()), "--wait-pid", str(os.getpid())]
    if not restart:
        args.append("--no-restart")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True, cwd=str(staged_exe.parent))
    log(f"güncelleme başlatıldı → {install_dir()}")


def _wait_pid(pid: int, timeout_ms=60000) -> None:
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        k32.WaitForSingleObject(handle, timeout_ms)
        k32.CloseHandle(handle)
    time.sleep(0.5)


def apply_update(target: Path, wait_pid: int, restart: bool) -> int:
    """Yeni (geçici klasördeki) exe içinde, Qt başlamadan çalışır."""
    try:
        _wait_pid(wait_pid)
        src = install_dir()
        if not (target / EXE_NAME).exists() or not (target / "_internal").is_dir():
            raise RuntimeError(f"Hedef bir e-Defter PDF kurulumu değil: {target}")
        old_int, old_exe = target / "_internal.old", target / (EXE_NAME + ".old")
        shutil.rmtree(old_int, ignore_errors=True)
        old_exe.unlink(missing_ok=True)
        for attempt in range(20):  # dosyalar hâlâ kilitliyse biraz bekle
            try:
                os.replace(target / "_internal", old_int)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Eski dosyalar kilitli, güncelleme yapılamadı")
        try:
            os.replace(target / EXE_NAME, old_exe)
            shutil.copytree(src / "_internal", target / "_internal")
            shutil.copy2(src / EXE_NAME, target / EXE_NAME)
        except Exception:
            # geri al
            shutil.rmtree(target / "_internal", ignore_errors=True)
            os.replace(old_int, target / "_internal")
            if old_exe.exists():
                (target / EXE_NAME).unlink(missing_ok=True)
                os.replace(old_exe, target / EXE_NAME)
            raise
        log(f"güncelleme uygulandı: {__version__}")
        if restart:
            subprocess.Popen([str(target / EXE_NAME), "--updated"], cwd=str(target),
                             creationflags=0x00000008, close_fds=True)
        return 0
    except Exception:
        log("güncelleme HATASI:\n" + traceback.format_exc())
        return 1


def cleanup() -> None:
    """Önceki güncellemeden kalan yedekleri ve eski indirmeleri siler."""
    if not is_frozen():
        return
    d = install_dir()
    shutil.rmtree(d / "_internal.old", ignore_errors=True)
    try:
        (d / (EXE_NAME + ".old")).unlink(missing_ok=True)
    except OSError:
        pass
    if STAGE_ROOT.exists():
        for p in STAGE_ROOT.iterdir():
            if parse_version(p.name) <= parse_version(__version__):
                shutil.rmtree(p, ignore_errors=True)
