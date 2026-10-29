"""e-Defter PDF — e-Defter arşivini (zip/rar) bilgisayardan çıkmadan PDF'e çevirir."""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QMarginsF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

import edefter

APP_NAME = "e-Defter PDF"
PARALLEL = 3  # aynı anda basılan belge sayısı
PAGE_LAYOUT = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                          QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)


class DropArea(QLabel):
    fileChosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(170)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._idle_text()
        self._style(False)

    def _idle_text(self):
        self.setText("e-Defter arşivini (.zip / .rar) buraya sürükleyip bırakın\n\nveya seçmek için tıklayın")

    def _style(self, hover: bool):
        border = "#2f7d4f" if hover else "#9aa5b1"
        bg = "#eaf6ee" if hover else "#f7f9fb"
        self.setStyleSheet(f"QLabel {{ border: 2px dashed {border}; border-radius: 12px; background: {bg};"
                           f" color: #333; font-size: 15px; padding: 16px; }}")

    @staticmethod
    def _archive(event) -> str | None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            p = urls[0].toLocalFile()
            if Path(p).suffix.lower() in edefter.ARCHIVE_EXTS:
                return p
        return None

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._archive(event):
            event.acceptProposedAction()
            self._style(True)

    def dragLeaveEvent(self, event):
        self._style(False)

    def dropEvent(self, event):
        self._style(False)
        p = self._archive(event)
        if p:
            self.fileChosen.emit(p)

    def mousePressEvent(self, event):
        if not self.isEnabled():
            return
        p, _ = QFileDialog.getOpenFileName(self, "e-Defter arşivi seç", "", "Arşiv (*.zip *.rar *.7z)")
        if p:
            self.fileChosen.emit(p)


class Converter:
    """Belgeleri sırayla HTML'e çevirip birkaç sayfa üzerinde paralel PDF'e basar."""

    def __init__(self, window: "MainWindow"):
        self.w = window
        self.profile = QWebEngineProfile(window)  # isimsiz = iz bırakmayan (off-the-record) profil
        self.pages: list[QWebEnginePage] = []
        for _ in range(PARALLEL):
            page = QWebEnginePage(self.profile, window)
            s = page.settings()
            # Gizlilik: yerel sayfa internetten hiçbir şey çekemesin
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            s.setAttribute(QWebEngineSettings.WebAttribute.PrintElementBackgrounds, True)
            page.loadFinished.connect(lambda ok, pg=page: self._loaded(pg, ok))
            page.pdfPrintingFinished.connect(lambda path, ok, pg=page: self._printed(pg, path, ok))
            self.pages.append(page)
        self.transformer: edefter.Transformer | None = None

    def start(self, docs, work: Path, out_root: Path):
        if self.transformer is None:
            self.transformer = edefter.Transformer()
        self.docs, self.work, self.out_root = docs, work, out_root
        self.next_i = 0
        self.busy: dict[QWebEnginePage, int] = {}
        self.done: set[int] = set()
        self.failed: list[tuple[edefter.Doc, str]] = []
        (work / "html").mkdir(parents=True, exist_ok=True)
        (work / "pdf").mkdir(parents=True, exist_ok=True)  # printToPdf klasör oluşturmaz
        for page in self.pages:
            self._feed(page)

    def _feed(self, page):
        while self.next_i < len(self.docs):
            i = self.next_i
            self.next_i += 1
            doc = self.docs[i]
            try:
                html = self.transformer.to_html(doc)
                html_path = self.work / "html" / f"{i}.html"
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html, encoding="utf-8")
            except Exception as exc:  # bozuk XML vb. — diğerlerine devam
                self._fail(i, f"XSLT hatası: {exc}")
                continue
            self.busy[page] = i
            page.load(QUrl.fromLocalFile(str(html_path)))
            return
        self.busy.pop(page, None)
        if not self.busy:
            self.w.conversion_finished(self.done, self.failed)

    def _loaded(self, page, ok):
        i = self.busy.get(page)
        if i is None:
            return
        if not ok:
            self._fail(i, "sayfa yüklenemedi")
            self._feed(page)
            return
        page.printToPdf(str(self.work / "pdf" / f"{i}.pdf"), PAGE_LAYOUT)

    def _printed(self, page, path, ok):
        i = self.busy.get(page)
        if i is None:
            return
        doc = self.docs[i]
        if ok:
            target = self.out_root / doc.out_dir / doc.out_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, target)
            self.done.add(i)
            self.w.progress(len(self.done) + len(self.failed), f"{doc.out_dir.as_posix()}/{doc.out_name}")
        else:
            self._fail(i, "PDF basılamadı")
        self._feed(page)

    def _fail(self, i, msg):
        doc = self.docs[i]
        self.failed.append((doc, msg))
        self.w.log(f"HATA  {doc.src.name}: {msg}")
        self.w.progress(len(self.done) + len(self.failed), None)


class MainWindow(QWidget):
    def __init__(self, auto: Path | None = None, out_parent: Path | None = None, merge=False, make_zip=True):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(720, 560)
        self.auto = auto
        self.out_parent_override = out_parent
        self.out_folder: Path | None = None
        self.work: Path | None = None

        title = QLabel("e-Defter → PDF")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        sub = QLabel("Yevmiye, Kebir, beratlar ve defter raporu GİB şablonlarıyla PDF'e çevrilir. "
                     "Dosyalar bu bilgisayardan dışarı çıkmaz, internet gerekmez.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #555;")

        self.drop = DropArea()
        self.drop.fileChosen.connect(self.start)

        self.cb_merge = QCheckBox("Her ay için ayrıca tek birleşik PDF oluştur (\"Tümü.pdf\")")
        self.cb_merge.setChecked(merge)
        self.cb_zip = QCheckBox("Sonucu ayrıca .zip olarak da kaydet")
        self.cb_zip.setChecked(make_zip)

        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v / %m")
        self.bar.hide()
        self.status = QLabel("")
        self.status.setStyleSheet("color: #333;")

        self.logbox = QPlainTextEdit(readOnly=True)
        self.logbox.setFont(QFont("Consolas", 9))
        self.logbox.setFrameShape(QFrame.Shape.StyledPanel)

        self.btn_open = QPushButton("Klasörü aç")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_folder))))
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.btn_open)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addWidget(self.drop)
        lay.addWidget(self.cb_merge)
        lay.addWidget(self.cb_zip)
        lay.addWidget(self.bar)
        lay.addLayout(row)
        lay.addWidget(self.logbox, 1)

        self.converter = Converter(self)
        if auto:
            QTimer.singleShot(0, lambda: self.start(str(auto)))

    # ------------------------------------------------------------ yardımcılar
    def log(self, text: str):
        self.logbox.appendPlainText(text)
        if self.auto:
            print(text, flush=True)

    def progress(self, n: int, name: str | None):
        self.bar.setValue(n)
        if name:
            self.status.setText(f"Hazırlanıyor… {name}")

    def _busy(self, on: bool):
        self.drop.setEnabled(not on)
        self.cb_merge.setEnabled(not on)
        self.cb_zip.setEnabled(not on)

    @staticmethod
    def _free_path(p: Path) -> Path:
        if not p.exists():
            return p
        n = 2
        while (q := p.with_name(f"{p.name} ({n})")).exists():
            n += 1
        return q

    # ------------------------------------------------------------ akış
    def start(self, archive_path: str):
        archive = Path(archive_path)
        self._busy(True)
        self.btn_open.setEnabled(False)
        self.logbox.clear()
        self.t0 = time.time()
        self.archive = archive
        parent = self.out_parent_override or archive.parent
        self.out_folder = self._free_path(parent / f"{archive.stem} - PDF")
        self.log(f"Arşiv: {archive.name}")
        self.status.setText("Arşiv açılıyor…")
        QApplication.processEvents()
        try:
            self.work = Path(tempfile.mkdtemp(prefix="edefter_"))
            src = self.work / "src"
            edefter.extract_archive(archive, src)
            edefter.expand_nested_zips(src)
            scan = edefter.scan(src)
        except Exception as exc:
            self._abort(f"Arşiv açılamadı:\n{exc}")
            return
        if not scan.docs:
            self._abort("Bu arşivde e-Defter XML dosyası bulunamadı.\n"
                        "(Beklenen ad örneği: 1234567890-202401-Y-000000.xml)")
            return
        months = len({(d.vkn, d.year, d.month) for d in scan.docs})
        cancelled = sum(d.cancelled for d in scan.docs)
        self.log(f"{len(scan.docs)} belge bulundu ({months} ay"
                 + (f", {cancelled} iptal edilen" if cancelled else "") + f"); {scan.duplicates} kopya atlandı.")
        self.scan = scan
        self.out_folder.mkdir(parents=True)
        for src_pdf, rel in scan.extra_pdfs:
            target = self.out_folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_pdf, target)
        self.bar.setRange(0, len(scan.docs))
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText("PDF'ler hazırlanıyor…")
        try:
            self.converter.start(scan.docs, self.work, self.out_folder)
        except Exception as exc:
            self._abort(f"Dönüştürücü başlatılamadı:\n{exc}")

    def conversion_finished(self, done: set[int], failed):
        try:
            if self.cb_merge.isChecked() and done:
                self.status.setText("Aylık birleşik PDF'ler oluşturuluyor…")
                QApplication.processEvents()
                made = edefter.merge_monthly(self.out_folder, self.scan.docs, done)
                self.log(f"{len(made)} aylık birleşik PDF oluşturuldu.")
            zip_path = None
            if self.cb_zip.isChecked() and done:
                self.status.setText("ZIP hazırlanıyor…")
                QApplication.processEvents()
                zip_path = self._free_path(self.out_folder.with_name(self.out_folder.name + ".zip"))
                edefter.zip_folder(self.out_folder, zip_path)
        except Exception as exc:
            self.log(f"HATA  son adım: {exc}")
            zip_path = None
        secs = int(time.time() - self.t0)
        self.log(f"\nBitti: {len(done)} PDF, {len(failed)} hata, {secs} sn.")
        self.log(f"Klasör: {self.out_folder}")
        if zip_path:
            self.log(f"ZIP:    {zip_path}")
        self.status.setText(f"Bitti — {len(done)} PDF" + (f", {len(failed)} hata" if failed else ""))
        self.btn_open.setEnabled(True)
        self._cleanup()
        self._busy(False)
        if self.auto:
            QApplication.exit(1 if failed else 0)

    def _abort(self, msg: str):
        self.log(msg)
        self.status.setText("İşlem yapılamadı")
        self._cleanup()
        self._busy(False)
        if self.auto:
            QApplication.exit(2)
        else:
            QMessageBox.warning(self, APP_NAME, msg)

    def _cleanup(self):
        if self.work:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None


def main():
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("archive", nargs="?", help="Doğrudan işlenecek arşiv (test/otomasyon)")
    ap.add_argument("--out", help="Çıktı klasörünün konacağı yer (varsayılan: arşivin yanı)")
    ap.add_argument("--merge", action="store_true", help="Aylık birleşik PDF de üret")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Windows koyu temasında açık renkli bırakma alanı ve gri yazılar okunmuyor; hep açık tema
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    w =MainWindow(Path(args.archive) if args.archive else None,
                   Path(args.out) if args.out else None, args.merge, not args.no_zip)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
