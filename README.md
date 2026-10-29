# e-Defter PDF

e-Defter arşivini (.zip / .rar / .7z) bilgisayardan çıkmadan PDF'e çeviren masaüstü uygulaması.
İnternet bağlantısı kullanmaz.

## Kullanım
1. Masaüstündeki **e-Defter PDF** kısayolunu açın.
2. Arşivi pencereye sürükleyin (veya tıklayıp seçin).
3. Bitince **Klasörü aç**'a basın. Çıktı arşivin yanına `<arşiv adı> - PDF` klasörü (ve isteğe bağlı .zip) olarak yazılır.

Çıktı düzeni: `VKN/Yıl/Ay/2024-04 Yevmiye Defteri.pdf`, `… Kebir Defteri.pdf`, `… Yevmiye Beratı.pdf`,
`… Kebir Beratı.pdf`, `… GİB Yevmiye/Kebir Beratı.pdf`, `… Defter Raporu.pdf`.
- "iptal edilen / silinen" klasörlerindekiler ayın içinde `İptal edilenler/` altına konur.
- Arşivdeki diğer PDF'ler (muhasebe programı raporları) `Ek - …pdf` olarak ayın klasörüne kopyalanır.
- "Tümü.pdf" seçeneği her ayın belgelerini tek dosyada birleştirir.
- Excel seçeneği her mali yıl için `VKN/Yıl/<yıl> Defter (Yevmiye-Kebir-Mizan).xlsx` yazar:
  **Yevmiye** (tüm satırlar), **Kebir** (hesap/alt hesap sırasıyla, kümülatif toplam ve bakiye),
  **Mizan (Ana Hesap)** ve **Mizan (Alt Hesap)**. İptal edilenler Excel'e alınmaz.

## Nasıl çalışır
Her XML, arşivle gelen GİB XSLT şablonuyla (yoksa `xslt/` içindeki yedekle) Saxon kullanılarak HTML'e,
ardından Qt WebEngine ile A4 PDF'e çevrilir. İç içe zip'ler açılır, aynı içerikli kopyalar elenir.

## Geliştirme
```bash
python3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py                      # pencere
.venv/Scripts/python main.py arşiv.rar --out DIR  # otomatik çalıştır ve kapan
```
Exe: PowerShell'de `.\build.ps1` → `build/dist/eDefterPDF/` ve `build/eDefterPDF-windows.zip`.
Klasör başka bilgisayara olduğu gibi kopyalanabilir; Python gerekmez.

## İndirme
Hazır exe GitHub **Releases** sayfasında: `eDefterPDF-windows.zip` → açın → `eDefterPDF.exe`.
Exe imzasız olduğundan Windows SmartScreen / Akıllı Uygulama Denetimi uyarı verebilir.
