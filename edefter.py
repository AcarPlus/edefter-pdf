"""e-Defter arşivini (zip/rar) açar, belgeleri bulur ve GİB XSLT'leriyle HTML'e çevirir.

Qt'den bağımsızdır; PDF basımı main.py'de yapılır.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    APP_DIR = Path(__file__).resolve().parent
BUNDLED_XSLT = APP_DIR / "xslt"

ARCHIVE_EXTS = {".zip", ".rar", ".7z"}

# 1234567890-202404-Y-000000.xml, GIB-1234567890-202404-KB-000000.xml, "... (1).xml"
DOC_RE = re.compile(
    r"^(?P<gib>GIB-)?(?P<vkn>\d{10,11})-(?P<year>\d{4})(?P<month>\d{2})-"
    r"(?P<kind>YB|KB|DR|Y|K)-(?P<part>\d{6})(?P<suffix>.*)\.xml$",
    re.IGNORECASE,
)

KIND_NAMES = {
    "Y": "Yevmiye Defteri",
    "K": "Kebir Defteri",
    "YB": "Yevmiye Beratı",
    "KB": "Kebir Beratı",
    "DR": "Defter Raporu",
}
KIND_XSLT = {"Y": "yevmiye.xslt", "K": "kebir.xslt", "YB": "berat.xslt", "KB": "berat.xslt", "DR": "defterraporu.xslt"}
# Aylık birleşik PDF'teki sıra
KIND_ORDER = {("Y", False): 0, ("YB", False): 1, ("YB", True): 2, ("K", False): 3, ("KB", False): 4, ("KB", True): 5, ("DR", False): 6}

PI_RE = re.compile(rb'<\?xml-stylesheet[^>]*href="([^"]+)"')
CANCEL_RE = re.compile(r"iptal|İptal|IPTAL|silin", re.IGNORECASE)


@dataclass
class Doc:
    src: Path
    vkn: str
    year: str
    month: str
    kind: str
    part: int
    gib: bool
    suffix: str
    cancelled: bool
    xslt: Path | None = None

    @property
    def title(self) -> str:
        name = ("GİB " if self.gib else "") + KIND_NAMES[self.kind]
        if self.part:
            name += f" (Kısım {self.part + 1})"
        suffix = self.suffix.strip()
        return f"{name} {suffix}" if suffix else name

    @property
    def out_dir(self) -> Path:
        d = Path(self.vkn) / self.year / self.month
        return d / "İptal edilenler" if self.cancelled else d

    @property
    def out_name(self) -> str:
        return f"{self.year}-{self.month} {self.title}.pdf"

    @property
    def sort_key(self):
        return (self.vkn, self.year, self.month, self.cancelled, KIND_ORDER.get((self.kind, self.gib), 9), self.part, self.suffix)


@dataclass
class Scan:
    docs: list[Doc] = field(default_factory=list)
    extra_pdfs: list[tuple[Path, Path]] = field(default_factory=list)  # (kaynak, hedef göreli yol)
    duplicates: int = 0


# ---------------------------------------------------------------- arşiv açma

def _safe_target(root: Path, name: str) -> Path | None:
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    if not parts:
        return None
    target = root.joinpath(*parts).resolve()
    return target if str(target).startswith(str(root.resolve())) else None


def _zip_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    try:  # Türkçe Windows zip'leri isimleri cp857 ile yazar
        return info.filename.encode("cp437").decode("cp857")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def extract_zip(path: Path, dest: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = _safe_target(dest, _zip_name(info))
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def _system_tar() -> str:
    win_tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    return str(win_tar) if win_tar.exists() else "tar"


def extract_archive(path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".zip":
        extract_zip(path, dest)
        return
    # RAR / 7z: Windows'un kendi tar.exe'si (libarchive) açabiliyor
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    res = subprocess.run([_system_tar(), "-xf", str(path), "-C", str(dest)],
                         capture_output=True, text=True, creationflags=flags)
    if res.returncode != 0:
        raise RuntimeError(f"Arşiv açılamadı: {res.stderr.strip() or res.returncode}")


def expand_nested_zips(root: Path, max_depth: int = 3) -> None:
    """İçteki zip'leri yanlarına '<ad>.__zip' klasörüne açar (tekrarlar sonra elenir)."""
    done: set[Path] = set()
    for _ in range(max_depth):
        found = [p for p in root.rglob("*.zip") if p not in done]
        if not found:
            return
        for z in found:
            done.add(z)
            try:
                extract_zip(z, z.with_name(z.name + ".__zip"))
            except zipfile.BadZipFile:
                pass


# ---------------------------------------------------------------- tarama

def _find_xslt(doc_path: Path, root: Path, kind: str) -> Path | None:
    with open(doc_path, "rb") as f:
        m = PI_RE.search(f.read(2048))
    name = os.path.basename(m.group(1).decode("utf-8", "replace")) if m else KIND_XSLT[kind]
    d = doc_path.parent
    while True:
        cand = d / name
        if cand.is_file():
            return cand
        if d == root or root not in d.parents:
            break
        d = d.parent
    bundled = BUNDLED_XSLT / name
    if bundled.is_file():
        return bundled
    bundled = BUNDLED_XSLT / KIND_XSLT[kind]
    return bundled if bundled.is_file() else None


def _rank(p: Path, root: Path) -> tuple:
    rel = p.relative_to(root).parts
    in_copy = any(x.endswith(".__zip") or x.lower() == "paketler" for x in rel)
    return (in_copy, len(rel), str(p))


def scan(root: Path) -> Scan:
    result = Scan()
    candidates = []
    for p in root.rglob("*.xml"):
        m = DOC_RE.match(p.name)
        if m:
            candidates.append((p, m))
    candidates.sort(key=lambda c: _rank(c[0], root))

    seen: set[str] = set()
    dir_month: dict[Path, Path] = {}
    for p, m in candidates:
        digest = hashlib.sha1(p.read_bytes()).hexdigest()
        if digest in seen:
            result.duplicates += 1
            continue
        seen.add(digest)
        rel_dirs = p.relative_to(root).parts[:-1]
        cancelled = any(CANCEL_RE.search(x) for x in rel_dirs)
        kind = m["kind"].upper()
        doc = Doc(src=p, vkn=m["vkn"], year=m["year"], month=m["month"], kind=kind,
                  part=int(m["part"]), gib=bool(m["gib"]), suffix=m["suffix"], cancelled=cancelled)
        doc.xslt = _find_xslt(p, root, kind)
        result.docs.append(doc)
        dir_month.setdefault(p.parent, Path(doc.vkn) / doc.year / doc.month)

    result.docs.sort(key=lambda d: d.sort_key)

    # Muhasebe programının bıraktığı PDF'ler (ör. e-Defter raporu) aynı ay klasörüne eklenir
    for pdf in root.rglob("*.pdf"):
        if any(x.endswith(".__zip") for x in pdf.relative_to(root).parts):
            continue
        month_dir = dir_month.get(pdf.parent)
        target = (month_dir / f"Ek - {pdf.name}") if month_dir else (Path("Diğer") / pdf.name)
        result.extra_pdfs.append((pdf, target))
    return result


# ---------------------------------------------------------------- XSLT

class Transformer:
    """Tek bir Saxon işlemcisi; derlenmiş XSLT'ler içeriğe göre önbelleklenir.

    Dosya yollarında Türkçe karakter sorunu yaşamamak için Saxon'a her şey metin olarak verilir.
    """

    def __init__(self):
        from saxonche import PySaxonProcessor
        self._proc = PySaxonProcessor(license=False)
        self._xslt = self._proc.new_xslt30_processor()
        self._cache: dict[str, object] = {}

    def _executable(self, xslt_path: Path):
        text = xslt_path.read_bytes().decode("utf-8-sig")
        key = hashlib.sha1(text.encode()).hexdigest()
        exe = self._cache.get(key)
        if exe is None:
            exe = self._xslt.compile_stylesheet(stylesheet_text=text)
            self._cache[key] = exe
        return exe

    def to_html(self, doc: Doc) -> str:
        if doc.xslt is None:
            raise RuntimeError("Uygun XSLT şablonu bulunamadı")
        exe = self._executable(doc.xslt)
        node = self._proc.parse_xml(xml_text=doc.src.read_bytes().decode("utf-8-sig"))
        html = exe.transform_to_string(xdm_node=node)
        if not html:
            raise RuntimeError(exe.error_message or "XSLT boş çıktı üretti")
        # Chromium thead/tfoot'u her sayfada tekrarlıyor; Kebir'de hesap TOPLAM'ı sayfa ortasında
        # yinelenmesin diye GİB görüntüleyicisindeki gibi tek seferlik basılır.
        fix = "<style>thead, tfoot { display: table-row-group; } tr { break-inside: avoid; }</style>"
        return html.replace("</head>", fix + "</head>", 1) if "</head>" in html else fix + html


def merge_monthly(out_root: Path, docs: list[Doc], done: set[int]) -> list[Path]:
    """Her ay için belgeleri sırasıyla tek PDF'te birleştirir (iptal edilenler hariç)."""
    from pypdf import PdfWriter
    groups: dict[Path, list[Path]] = {}
    for i, d in enumerate(docs):
        if i in done and not d.cancelled:
            groups.setdefault(d.out_dir, []).append(out_root / d.out_dir / d.out_name)
    made = []
    for rel_dir, files in groups.items():
        d0 = next(d for d in docs if d.out_dir == rel_dir)
        target = out_root / rel_dir / f"{d0.year}-{d0.month} Tümü.pdf"
        w = PdfWriter()
        for f in files:
            w.append(str(f))
        with open(target, "wb") as fh:
            w.write(fh)
        made.append(target)
    return made


def zip_folder(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(folder.parent))
