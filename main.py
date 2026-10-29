"""e-Defter PDF — e-Defter arşivini (zip/rar) veya klasörünü bilgisayardan çıkmadan PDF'e ve Excel'e çevirir."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import updater

APP_NAME = "e-Defter PDF"


def main():
    # Güncelleyici modu Qt yüklenmeden çalışır (yeni exe eski kurulumun üzerine yazar)
    if "--apply-update" in sys.argv:
        ap = argparse.ArgumentParser()
        ap.add_argument("--apply-update", required=True)
        ap.add_argument("--wait-pid", type=int, required=True)
        ap.add_argument("--no-restart", action="store_true")
        a = ap.parse_args()
        sys.exit(updater.apply_update(Path(a.apply_update), a.wait_pid, not a.no_restart))

    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("archive", nargs="?", help="Doğrudan işlenecek arşiv veya klasör (test/otomasyon)")
    ap.add_argument("--out", help="Çıktı klasörünün konacağı yer (varsayılan: kaynağın yanı)")
    ap.add_argument("--merge", action="store_true", help="Aylık birleşik PDF de üret")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--no-excel", action="store_true")
    ap.add_argument("--updated", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--screenshot", help=argparse.SUPPRESS)
    args = ap.parse_args()

    from ui import run  # Qt yalnızca arayüz modunda yüklenir
    sys.exit(run(args))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
