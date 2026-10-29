"""PySide6 arayüzü: sürükle-bırak, aşamalı ilerleme, sonuç özeti, ayarlar ve otomatik güncelleme."""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QMarginsF, QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

import edefter
import excel
import updater
from version import __version__

APP_NAME = "e-Defter PDF"
PARALLEL = 3  # aynı anda basılan belge sayısı
PAGE_LAYOUT = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                          QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)
STEPS = ["Okunuyor", "PDF", "Excel", "Paketleme"]

ACCENT = "#1f6f6b"
QSS = f"""
QWidget#root {{ background: #f3f5f7; }}
QLabel {{ color: #1d2733; }}
QLabel#title {{ font-size: 21px; font-weight: 600; }}
QLabel#subtitle, QLabel#muted {{ color: #5b6876; }}
QLabel#badge {{ color: {ACCENT}; background: #e3f1ee; border-radius: 9px; padding: 2px 9px; font-size: 11px; }}
QFrame#card {{ background: #ffffff; border: 1px solid #e1e6eb; border-radius: 12px; }}
QFrame#drop {{ background: #fbfcfd; border: 2px dashed #b7c2cc; border-radius: 12px; }}
QFrame#drop[hover="true"] {{ background: #eaf5f2; border-color: {ACCENT}; }}
QLabel#dropTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#cardTitle {{ font-size: 13px; font-weight: 600; color: #34414e; }}
QLabel#stageTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#doneTitle {{ font-size: 18px; font-weight: 600; color: {ACCENT}; }}
QLabel#step {{ color: #8a96a3; background: #eef1f4; border-radius: 11px; padding: 3px 12px; }}
QLabel#step[state="active"] {{ color: #ffffff; background: {ACCENT}; }}
QLabel#step[state="done"] {{ color: {ACCENT}; background: #e3f1ee; }}
QFrame#tile {{ background: #f6f8fa; border: 1px solid #e6eaee; border-radius: 10px; }}
QLabel#tileValue {{ font-size: 22px; font-weight: 600; color: #1d2733; }}
QLabel#tileLabel {{ color: #5b6876; font-size: 11px; }}
QPushButton {{ background: #ffffff; border: 1px solid #c9d2da; border-radius: 8px; padding: 7px 16px; color: #1d2733; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #a3adb7; border-color: #e1e6eb; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; font-weight: 600; }}
QPushButton#primary:hover {{ background: #18595a; color: #ffffff; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 2px 4px; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QProgressBar {{ background: #e8ecf0; border: none; border-radius: 6px; height: 12px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QFrame#banner {{ background: #fff6e0; border: 1px solid #f1d58a; border-radius: 10px; }}
QFrame#banner[kind="ok"] {{ background: #e6f4ec; border-color: #9fd3b4; }}
QPlainTextEdit {{ background: #ffffff; border: 1px solid #e1e6eb; border-radius: 8px; color: #34414e; }}
QCheckBox {{ color: #1d2733; spacing: 8px; }}
"""


def _label(text="", name=None, wrap=False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def _card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return f, lay


def _restyle(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class Bridge(QObject):
    """Arka plan iş parçacığından ana iş parçacığına sonuç taşır."""
    ok = Signal(object)
    err = Signal(str)
    progress = Signal(int, int)


def run_bg(parent, fn, on_ok, on_err, on_progress=None):
    b = Bridge(parent)
    b.ok.connect(on_ok)
    b.err.connect(on_err)
    if on_progress:
        b.progress.connect(on_progress)

    def work():
        try:
            res = fn(b) if on_progress else fn()
            b.ok.emit(res)
        except Exception as exc:  # noqa: BLE001 — kullanıcıya mesaj olarak gösterilir
            b.err.emit(str(exc) or exc.__class__.__name__)
    threading.Thread(target=work, daemon=True).start()
    return b


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
        self.busy: dict[QWebEnginePage, int] = {}

    def start(self, docs, work: Path, out_root: Path):
        if self.transformer is None:
            self.transformer = edefter.Transformer()
        self.docs, self.work, self.out_root = docs, work, out_root
        self.next_i = 0
        self.busy = {}
        self.done: set[int] = set()
        self.failed: list[tuple[edefter.Doc, str]] = []
        self.cancelled = False
        (work / "html").mkdir(parents=True, exist_ok=True)
        (work / "pdf").mkdir(parents=True, exist_ok=True)  # printToPdf klasör oluşturmaz
        for page in self.pages:
            self._feed(page)

    def cancel(self):
        self.cancelled = True

    def _feed(self, page):
        while not self.cancelled and self.next_i < len(self.docs):
            i = self.next_i
            self.next_i += 1
            doc = self.docs[i]
            try:
                html = self.transformer.to_html(doc)
                html_path = self.work / "html" / f"{i}.html"
                html_path.write_text(html, encoding="utf-8")
            except Exception as exc:  # bozuk XML vb. — diğerlerine devam
                self._fail(i, f"XSLT hatası: {exc}")
                continue
            self.busy[page] = i
            page.load(QUrl.fromLocalFile(str(html_path)))
            return
        self.busy.pop(page, None)
        if not self.busy:
            QTimer.singleShot(0, lambda: self.w.pdf_finished(self.done, self.failed, self.cancelled))

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
            self.w.pdf_progress(len(self.done) + len(self.failed), f"{doc.year}/{doc.month} · {doc.title}")
        else:
            self._fail(i, "PDF basılamadı")
        self._feed(page)

    def _fail(self, i, msg):
        doc = self.docs[i]
        self.failed.append((doc, msg))
        self.w.log(f"HATA  {doc.src.name}: {msg}")
        self.w.pdf_progress(len(self.done) + len(self.failed), None)


class DropZone(QFrame):
    def __init__(self, on_archive, on_folder):
        super().__init__()
        self.setObjectName("drop")
        self.setMinimumHeight(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_archive = on_archive
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 26, 24, 24)
        lay.setSpacing(6)
        icon = QLabel("⤓")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 38px; color: {ACCENT}; background: transparent; border: none;")
        t = _label("e-Defter arşivini veya klasörünü buraya bırakın", "dropTitle")
        sub = _label(".zip · .rar · .7z · açılmış klasör", "muted")
        for w in (t, sub):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setStyleSheet("background: transparent; border: none;")
        b1 = QPushButton("Arşiv seç…")
        b1.setObjectName("primary")
        b1.clicked.connect(on_archive)
        b2 = QPushButton("Klasör seç…")
        b2.clicked.connect(on_folder)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        lay.addStretch(1)
        lay.addWidget(icon)
        lay.addWidget(t)
        lay.addWidget(sub)
        lay.addSpacing(10)
        lay.addLayout(row)
        lay.addStretch(1)

    def set_hover(self, on: bool):
        self.setProperty("hover", "true" if on else "false")
        _restyle(self)

    def mousePressEvent(self, event):
        self._on_archive()


class MainWindow(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.auto = Path(args.archive) if args.archive else None
        self.settings = QSettings("AcarPlus", "eDefterPDF")
        self.setObjectName("root")
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setAcceptDrops(True)
        self.resize(780, 700)
        self.setMinimumSize(640, 600)
        self.out_folder: Path | None = None
        self.work: Path | None = None
        self.excel_files: list[Path] = []
        self.zip_path: Path | None = None
        self.staged_update: Path | None = None
        self.update_info: dict | None = None
        self.running = False
        self._bridges = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)

        # Başlık
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(edefter.APP_DIR / "assets" / "app.png")).pixmap(44, 44))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(_label(APP_NAME, "title"))
        titles.addWidget(_label("Yevmiye, Kebir, beratlar ve defter raporunu GİB şablonlarıyla PDF ve Excel'e çevirir",
                                "subtitle", wrap=True))
        head.addWidget(logo)
        head.addSpacing(8)
        head.addLayout(titles, 1)
        head.addWidget(_label(f"v{__version__}", "badge"), 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        # Güncelleme bandı
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 10, 8)
        self.banner_text = _label("", wrap=True)
        self.banner_btn = QPushButton()
        self.banner_btn.setObjectName("primary")
        self.banner_btn.clicked.connect(self._banner_action)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.banner_btn)
        self.banner.hide()
        root.addWidget(self.banner)

        # Durum sayfaları
        self.stack = QStackedWidget()
        self.drop = DropZone(self._choose_archive, self._choose_folder)
        self.stack.addWidget(self.drop)
        self.stack.addWidget(self._build_progress())
        self.stack.addWidget(self._build_done())
        root.addWidget(self.stack, 1)

        # Seçenekler
        opt, ol = _card()
        ol.addWidget(_label("Seçenekler", "cardTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.cb_excel = QCheckBox("Excel: her yıl için Yevmiye, Kebir, Mizan")
        self.cb_merge = QCheckBox("Her ay için birleşik PDF (Tümü.pdf)")
        self.cb_zip = QCheckBox("Sonucu ayrıca .zip olarak kaydet")
        self.cb_excel.setChecked(self._flag("excel", not args.no_excel))
        self.cb_merge.setChecked(self._flag("merge", args.merge))
        self.cb_zip.setChecked(self._flag("zip", not args.no_zip))
        for cb, key in ((self.cb_excel, "excel"), (self.cb_merge, "merge"), (self.cb_zip, "zip")):
            cb.toggled.connect(lambda v, k=key: self._save(k, v))
        grid.addWidget(self.cb_excel, 0, 0)
        grid.addWidget(self.cb_merge, 0, 1)
        grid.addWidget(self.cb_zip, 1, 0)
        ol.addLayout(grid)
        out_row = QHBoxLayout()
        self.out_label = _label("", "muted")
        self.out_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        b_change = QPushButton("Değiştir…")
        b_change.clicked.connect(self._choose_out)
        self.b_reset = QPushButton("Varsayılan")
        self.b_reset.setObjectName("link")
        self.b_reset.clicked.connect(lambda: self._set_out(""))
        out_row.addWidget(_label("Kayıt yeri:"))
        out_row.addWidget(self.out_label, 1)
        out_row.addWidget(self.b_reset)
        out_row.addWidget(b_change)
        ol.addLayout(out_row)
        self.options = opt
        root.addWidget(opt)
        self._set_out(args.out if args.out else (self.settings.value("out_dir", "") if not self.auto else ""),
                      save=not self.auto)

        # Ayrıntılar
        self.btn_log = QPushButton("▸ Ayrıntılar")
        self.btn_log.setObjectName("link")
        self.btn_log.setCheckable(True)
        self.btn_log.toggled.connect(self._toggle_log)
        self.logbox = QPlainTextEdit(readOnly=True)
        self.logbox.setFont(QFont("Consolas", 9))
        self.logbox.setMinimumHeight(110)
        self.logbox.hide()
        root.addWidget(self.btn_log, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.logbox)

        # Alt bilgi
        foot = QHBoxLayout()
        foot.addWidget(_label("🔒 Belgeleriniz bu bilgisayardan dışarı gönderilmez.", "muted"))
        foot.addStretch(1)
        self.cb_update = QCheckBox("Güncellemeleri otomatik denetle")
        self.cb_update.setChecked(self._flag("auto_update", True))
        self.cb_update.toggled.connect(lambda v: self._save("auto_update", v))
        self.cb_update.setVisible(updater.is_frozen())
        foot.addWidget(self.cb_update)
        root.addLayout(foot)

        self.converter = Converter(self)
        updater.cleanup()
        if args.updated:
            self._show_banner(f"Uygulama v{__version__} sürümüne güncellendi.", None, ok=True)
            QTimer.singleShot(6000, self.banner.hide)
        if self.auto:
            QTimer.singleShot(0, lambda: self.start(str(self.auto)))
        elif updater.is_frozen() and self.cb_update.isChecked():
            QTimer.singleShot(1500, self._check_update)
        if args.screenshot and not self.auto:
            QTimer.singleShot(900, lambda: (self.grab().save(args.screenshot), QApplication.exit(0)))

    # ------------------------------------------------------------ sayfalar
    def _build_progress(self) -> QWidget:
        card, lay = _card()
        steps = QHBoxLayout()
        self.step_labels = []
        for i, s in enumerate(STEPS):
            lb = _label(f"{i + 1}  {s}", "step")
            self.step_labels.append(lb)
            steps.addWidget(lb)
        steps.addStretch(1)
        self.stage_title = _label("", "stageTitle")
        self.src_label = _label("", "muted")
        self.bar = QProgressBar()
        self.bar.setFixedHeight(12)
        self.count_label = _label("", "muted")
        self.file_label = _label("", "muted")
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.clicked.connect(self._cancel)
        row = QHBoxLayout()
        row.addWidget(self.file_label, 1)
        row.addWidget(self.count_label)
        lay.addLayout(steps)
        lay.addSpacing(8)
        lay.addWidget(self.stage_title)
        lay.addWidget(self.src_label)
        lay.addSpacing(6)
        lay.addWidget(self.bar)
        lay.addLayout(row)
        lay.addStretch(1)
        lay.addWidget(self.btn_cancel, 0, Qt.AlignmentFlag.AlignRight)
        return card

    def _build_done(self) -> QWidget:
        card, lay = _card()
        self.done_title = _label("", "doneTitle")
        self.done_sub = _label("", "muted", wrap=True)
        lay.addWidget(self.done_title)
        lay.addWidget(self.done_sub)
        tiles = QHBoxLayout()
        self.tiles = {}
        for key, name in (("pdf", "PDF"), ("excel", "Excel"), ("months", "Ay"), ("cancelled", "İptal edilen belge")):
            f = QFrame()
            f.setObjectName("tile")
            tl = QVBoxLayout(f)
            tl.setContentsMargins(14, 10, 14, 10)
            v = _label("0", "tileValue")
            tl.addWidget(v)
            tl.addWidget(_label(name, "tileLabel"))
            self.tiles[key] = v
            tiles.addWidget(f)
        lay.addSpacing(4)
        lay.addLayout(tiles)
        self.done_warn = _label("", wrap=True)
        self.done_warn.setStyleSheet("color: #a5461c;")
        lay.addWidget(self.done_warn)
        lay.addStretch(1)
        btns = QHBoxLayout()
        self.btn_open = QPushButton("Klasörü aç")
        self.btn_open.setObjectName("primary")
        self.btn_open.clicked.connect(lambda: self._open(self.out_folder))
        self.btn_excel = QPushButton("Excel'i aç")
        self.btn_excel.clicked.connect(lambda: self._open(self.excel_files[0] if len(self.excel_files) == 1
                                                          else self.excel_files[0].parent.parent))
        self.btn_zipshow = QPushButton("ZIP'i göster")
        self.btn_zipshow.clicked.connect(lambda: self._open(self.zip_path.parent))
        b_new = QPushButton("Yeni dönüştürme")
        b_new.clicked.connect(self._reset)
        btns.addWidget(self.btn_open)
        btns.addWidget(self.btn_excel)
        btns.addWidget(self.btn_zipshow)
        btns.addStretch(1)
        btns.addWidget(b_new)
        lay.addLayout(btns)
        return card

    # ------------------------------------------------------------ ayarlar
    def _flag(self, key, default: bool) -> bool:
        if self.auto:  # otomasyon modunda yalnızca komut satırı geçerli
            return default
        v = self.settings.value(key)
        return default if v is None else str(v).lower() in ("true", "1")

    def _save(self, key, value):
        if not self.auto:
            self.settings.setValue(key, value)

    def _set_out(self, path: str, save=True):
        self.out_dir = path or ""
        self.out_label.setText(self.out_dir or "Kaynak dosyanın yanına")
        self.out_label.setToolTip(self.out_dir)
        self.b_reset.setVisible(bool(self.out_dir))
        if save:
            self._save("out_dir", self.out_dir)

    def _choose_out(self):
        p = QFileDialog.getExistingDirectory(self, "Çıktıların kaydedileceği klasör", self.out_dir or "")
        if p:
            self._set_out(p)

    # ------------------------------------------------------------ yardımcılar
    def log(self, text: str):
        self.logbox.appendPlainText(text)
        if self.auto:
            print(text, flush=True)

    def _toggle_log(self, on):
        self.logbox.setVisible(on)
        self.btn_log.setText(("▾" if on else "▸") + " Ayrıntılar")

    def _open(self, path: Path | None):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _set_step(self, idx: int, title: str):
        for i, lb in enumerate(self.step_labels):
            lb.setProperty("state", "done" if i < idx else "active" if i == idx else "")
            _restyle(lb)
        self.stage_title.setText(title)

    def _busy(self, on: bool):
        self.running = on
        self.options.setEnabled(not on)
        self.banner_btn.setEnabled(not on or self.staged_update is None)

    @staticmethod
    def _free_path(p: Path) -> Path:
        if not p.exists():
            return p
        n = 2
        while (q := p.with_name(f"{p.name} ({n})")).exists():
            n += 1
        return q

    def _choose_archive(self):
        if self.running:
            return
        p, _ = QFileDialog.getOpenFileName(self, "e-Defter arşivi seç", "", "Arşiv (*.zip *.rar *.7z)")
        if p:
            self.start(p)

    def _choose_folder(self):
        if self.running:
            return
        p = QFileDialog.getExistingDirectory(self, "e-Defter klasörü seç")
        if p:
            self.start(p)

    # ------------------------------------------------------------ sürükle-bırak (tüm pencere)
    @staticmethod
    def _dropped(event) -> str | None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            p = urls[0].toLocalFile()
            if Path(p).is_dir() or Path(p).suffix.lower() in edefter.ARCHIVE_EXTS:
                return p
        return None

    def dragEnterEvent(self, event):
        if not self.running and self._dropped(event):
            event.acceptProposedAction()
            self.stack.setCurrentIndex(0)
            self.drop.set_hover(True)

    def dragLeaveEvent(self, event):
        self.drop.set_hover(False)

    def dropEvent(self, event):
        self.drop.set_hover(False)
        p = self._dropped(event)
        if p:
            self.start(p)

    # ------------------------------------------------------------ akış
    def start(self, source_path: str):
        if self.running:
            return
        src_path = Path(source_path)
        self.is_dir = src_path.is_dir()
        self._busy(True)
        self.logbox.clear()
        self.t0 = time.time()
        self.excel_files, self.zip_path = [], None
        parent = Path(self.out_dir) if self.out_dir else src_path.parent
        self.out_folder = self._free_path(parent / f"{src_path.name if self.is_dir else src_path.stem} - PDF")
        self.log(f"{'Klasör' if self.is_dir else 'Arşiv'}: {src_path}")
        self.stack.setCurrentIndex(1)
        self._set_step(0, "Klasör okunuyor…" if self.is_dir else "Arşiv açılıyor…")
        self.src_label.setText(src_path.name)
        self.bar.setRange(0, 0)  # belirsiz
        self.count_label.setText("")
        self.file_label.setText("")
        self.btn_cancel.setEnabled(True)
        self.cancel_requested = False
        self.work = Path(tempfile.mkdtemp(prefix="edefter_"))
        work_src = self.work / "src"

        def prepare():
            if self.is_dir:
                # Kullanıcının klasörüne dokunmamak için kopya üzerinde çalışılır (iç zip'ler oraya açılır)
                edefter.copy_folder(src_path, work_src)
            else:
                edefter.extract_archive(src_path, work_src)
            edefter.expand_nested_zips(work_src)
            return edefter.scan(work_src)

        self._bridges.append(run_bg(self, prepare, self._prepared,
                                    lambda e: self._abort(f"{'Klasör okunamadı' if self.is_dir else 'Arşiv açılamadı'}:\n{e}")))

    def _prepared(self, scan):
        if self.cancel_requested:
            return self._cancelled()
        if not scan.docs:
            return self._abort(f"Bu {'klasörde' if self.is_dir else 'arşivde'} e-Defter XML dosyası bulunamadı.\n"
                               "(Beklenen ad örneği: 1234567890-202401-Y-000000.xml)")
        self.scan = scan
        months = len({(d.vkn, d.year, d.month) for d in scan.docs})
        cancelled = sum(d.cancelled for d in scan.docs)
        self.stats = {"months": months, "cancelled": cancelled}
        self.log(f"{len(scan.docs)} belge bulundu ({months} ay"
                 + (f", {cancelled} iptal edilen" if cancelled else "") + f"); {scan.duplicates} kopya atlandı.")
        try:
            self.out_folder.mkdir(parents=True)
            for src_pdf, rel in scan.extra_pdfs:
                target = self.out_folder / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_pdf, target)
        except OSError as exc:
            return self._abort(f"Çıktı klasörü oluşturulamadı:\n{exc}")
        self._set_step(1, "PDF'ler hazırlanıyor…")
        self.bar.setRange(0, len(scan.docs))
        self.bar.setValue(0)
        self.count_label.setText(f"0 / {len(scan.docs)}")
        try:
            self.converter.start(scan.docs, self.work, self.out_folder)
        except Exception as exc:
            self._abort(f"Dönüştürücü başlatılamadı:\n{exc}")

    def pdf_progress(self, n: int, name: str | None):
        self.bar.setValue(n)
        self.count_label.setText(f"{n} / {self.bar.maximum()}")
        if name:
            self.file_label.setText(name)

    def pdf_finished(self, done: set[int], failed, cancelled: bool):
        if cancelled:
            return self._cancelled()
        self.pdf_done, self.pdf_failed = done, failed
        self.btn_cancel.setEnabled(False)  # kalan adımlar kısa
        self.file_label.setText("")
        self._set_step(2, "Excel dosyaları oluşturuluyor…" if self.cb_excel.isChecked() else "Excel atlandı")
        self.bar.setRange(0, 0)
        merge, make_excel, make_zip = self.cb_merge.isChecked(), self.cb_excel.isChecked(), self.cb_zip.isChecked()
        out, docs = self.out_folder, self.scan.docs

        def finish_work():
            msgs, excel_files, zip_path = [], [], None
            if make_excel:
                excel_files = excel.export(out, docs)
                msgs.append(f"{len(excel_files)} Excel dosyası oluşturuldu.")
            if merge and done:
                made = edefter.merge_monthly(out, docs, done)
                msgs.append(f"{len(made)} aylık birleşik PDF oluşturuldu.")
            if make_zip and done:
                zip_path = self._free_path(out.with_name(out.name + ".zip"))
                edefter.zip_folder(out, zip_path)
            return msgs, excel_files, zip_path

        self._bridges.append(run_bg(self, finish_work, self._finished,
                                    lambda e: self._finished(([f"HATA  son adım: {e}"], [], None))))
        QTimer.singleShot(400, lambda: self.running and self._set_step(3, "Paketleniyor…"))

    def _finished(self, res):
        msgs, self.excel_files, self.zip_path = res
        for m in msgs:
            self.log(m)
        done, failed = self.pdf_done, self.pdf_failed
        secs = int(time.time() - self.t0)
        self.log(f"\nBitti: {len(done)} PDF, {len(failed)} hata, {secs} sn.")
        self.log(f"Klasör: {self.out_folder}")
        if self.zip_path:
            self.log(f"ZIP:    {self.zip_path}")
        self.tiles["pdf"].setText(str(len(done)))
        self.tiles["excel"].setText(str(len(self.excel_files)))
        self.tiles["months"].setText(str(self.stats["months"]))
        self.tiles["cancelled"].setText(str(self.stats["cancelled"]))
        self.done_title.setText("✓  Dönüştürme tamamlandı")
        self.done_sub.setText(f"{secs} saniye sürdü · Kayıt yeri: {self.out_folder}")
        warn = [m for m in msgs if m.startswith("HATA")]
        if failed:
            warn.insert(0, f"{len(failed)} belge dönüştürülemedi — ayrıntılar için aşağıya bakın.")
        self.done_warn.setText("\n".join(warn))
        self.done_warn.setVisible(bool(warn))
        self.btn_excel.setVisible(bool(self.excel_files))
        self.btn_zipshow.setVisible(bool(self.zip_path))
        self.stack.setCurrentIndex(2)
        self._cleanup()
        self._busy(False)
        if self.auto:
            if self.args.screenshot:
                self.grab().save(self.args.screenshot)
            QApplication.exit(1 if failed else 0)

    def _cancel(self):
        self.cancel_requested = True
        self.btn_cancel.setEnabled(False)
        self.stage_title.setText("İptal ediliyor…")
        self.converter.cancel()

    def _cancelled(self):
        self.log("İptal edildi; yarım kalan çıktı silindi.")
        if self.out_folder and self.out_folder.exists():
            shutil.rmtree(self.out_folder, ignore_errors=True)
        self._cleanup()
        self._busy(False)
        self.stack.setCurrentIndex(0)
        if self.auto:
            QApplication.exit(3)

    def _reset(self):
        self.stack.setCurrentIndex(0)

    def _abort(self, msg: str):
        self.log(msg)
        self._cleanup()
        self._busy(False)
        self.stack.setCurrentIndex(0)
        if self.auto:
            QApplication.exit(2)
        else:
            QMessageBox.warning(self, APP_NAME, msg)

    def _cleanup(self):
        if self.work:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None

    # ------------------------------------------------------------ güncelleme
    def _show_banner(self, text, button: str | None, ok=False):
        self.banner.setProperty("kind", "ok" if ok else "")
        _restyle(self.banner)
        self.banner_text.setText(text)
        self.banner_btn.setVisible(bool(button))
        if button:
            self.banner_btn.setText(button)
        self.banner.show()

    def _check_update(self):
        self._bridges.append(run_bg(self, updater.check, self._update_found,
                                    lambda e: updater.log(f"denetim başarısız: {e}")))

    def _update_found(self, info):
        if not info:
            return
        self.update_info = info
        if not updater.can_self_update():
            self._show_banner(f"Yeni sürüm v{info['version']} yayında.", "İndir")
            return
        self._show_banner(f"Yeni sürüm v{info['version']} indiriliyor…", None)

        def dl(bridge):
            return updater.download(info, lambda d, t: bridge.progress.emit(d >> 20, t >> 20))

        def prog(done_mb, total_mb):
            if total_mb:
                self.banner_text.setText(f"Yeni sürüm v{info['version']} indiriliyor… {done_mb} / {total_mb} MB")

        self._bridges.append(run_bg(self, dl, self._update_ready, self._update_failed, prog))

    def _update_ready(self, exe: Path):
        self.staged_update = exe
        self._show_banner(f"v{self.update_info['version']} hazır. Uygulamayı kapattığınızda otomatik kurulur.",
                          "Şimdi yeniden başlat")
        self.banner_btn.setEnabled(not self.running)

    def _update_failed(self, err: str):
        updater.log(f"indirme başarısız: {err}")
        self._show_banner(f"Güncelleme indirilemedi: {err}", "Sayfayı aç")

    def _banner_action(self):
        if self.staged_update and not self.running:
            updater.launch_apply(self.staged_update, restart=True)
            self.staged_update = None
            QApplication.quit()
        elif self.update_info:
            QDesktopServices.openUrl(QUrl(updater.RELEASES_PAGE))

    def closeEvent(self, event):
        if self.running and not self.auto:
            ans = QMessageBox.question(self, APP_NAME, "Dönüştürme sürüyor. Yine de kapatılsın mı?")
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.converter.cancel()
            if self.out_folder:
                shutil.rmtree(self.out_folder, ignore_errors=True)
        self._cleanup()
        if self.staged_update:
            updater.launch_apply(self.staged_update, restart=False)
        event.accept()


def run(args) -> int:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    # Windows koyu temasında açık renkli kartlar okunmuyor; hep açık tema
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(str(edefter.APP_DIR / "assets" / "app.png")))
    app.setStyleSheet(QSS)
    w = MainWindow(args)
    w.show()
    return app.exec()
