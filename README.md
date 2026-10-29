# e-Defter PDF

e-Defter arşivini (.zip / .rar / .7z) veya klasörünü **bilgisayardan çıkmadan** PDF'e ve Excel'e çeviren
Windows masaüstü uygulaması. Belgeler hiçbir sunucuya gönderilmez; internet yalnızca güncelleme denetimi
için kullanılır (kapatılabilir).

## Kurulum
1. [Releases](https://github.com/AcarPlus/edefter-pdf/releases/latest) sayfasından `eDefterPDF-windows.zip` indirin.
2. **Açmadan önce** zip'e sağ tıklayın → *Özellikler* → altta **Engellemeyi kaldır** kutusunu işaretleyin → *Tamam*.
   (Bu adım atlanırsa Windows zip'ten çıkan her dosyayı "internetten geldi" diye işaretler ve uyarı verir.)
3. Zip'i örneğin `%LOCALAPPDATA%\Programs\` altına açın, `eDefterPDF\eDefterPDF.exe`'yi çalıştırın.
   Program Files altına koymayın; orada otomatik güncelleme yazma izni bulamaz.

### "Windows bilgisayarınızı korudu" uyarısı
Exe henüz kod imzalı değil, bu yüzden Windows SmartScreen ilk açılışta uyarabilir:
**Ek bilgi** → **Yine de çalıştır**. Bu yalnızca bir kez sorulur.

PowerShell ile aynı işlem (2. adımın karşılığı):
```powershell
Unblock-File "$env:USERPROFILE\Downloads\eDefterPDF-windows.zip"
```

**Akıllı Uygulama Denetimi (Smart App Control)** açıksa imzasız uygulamalar "Yine de çalıştır" seçeneği
olmadan engellenir. Bunun tek kalıcı çözümü kod imzalamadır (yol haritasında). O zamana kadar
*Windows Güvenliği → Uygulama ve tarayıcı denetimi → Akıllı Uygulama Denetimi* ayarını kullanıcı
kendi kararıyla değiştirebilir.

## Kullanım
1. Arşivi ya da açılmış klasörü pencereye sürükleyin (veya **Arşiv seç… / Klasör seç…**).
   Klasör girdisinde kaynak klasöre hiçbir şey yazılmaz.
2. İlerleme aşamalarla gösterilir (Okunuyor → PDF → Excel → Paketleme); **İptal** ile durdurulabilir.
3. Bitince **Klasörü aç** / **Excel'i aç**. Çıktı varsayılan olarak kaynağın yanına
   `<ad> - PDF` klasörü olarak yazılır; *Kayıt yeri → Değiştir…* ile başka bir yer seçilebilir.
   Seçenekler bir sonraki açılışta hatırlanır.

Çıktı düzeni: `VKN/Yıl/Ay/2024-04 Yevmiye Defteri.pdf`, `… Kebir Defteri.pdf`, `… Yevmiye Beratı.pdf`,
`… Kebir Beratı.pdf`, `… GİB Yevmiye/Kebir Beratı.pdf`, `… Defter Raporu.pdf`.
- "iptal edilen / silinen" klasörlerindekiler ayın içinde `İptal edilenler/` altına konur.
- Arşivdeki diğer PDF'ler (muhasebe programı raporları) `Ek - …pdf` olarak ayın klasörüne kopyalanır.
- "Tümü.pdf" seçeneği her ayın belgelerini tek dosyada birleştirir.
- Excel seçeneği her mali yıl için `VKN/Yıl/<yıl> Defter (Yevmiye-Kebir-Mizan).xlsx` yazar:
  **Yevmiye** (tüm satırlar), **Kebir** (hesap/alt hesap sırasıyla, kümülatif toplam ve bakiye),
  **Mizan (Ana Hesap)** ve **Mizan (Alt Hesap)**. İptal edilenler Excel'e alınmaz.

## Otomatik güncelleme
Uygulama açılışta GitHub'daki son sürümü denetler. Yeni sürüm varsa arka planda indirir, **SHA-256** ile
doğrular ve üstte bir bant gösterir. Güncelleme, uygulama kapatılınca (veya **Şimdi yeniden başlat** ile)
kurulur. Sorun olursa eski dosyalara geri dönülür. Kayıt: `%LOCALAPPDATA%\eDefterPDF\update.log`.
Alt köşedeki **Güncellemeleri otomatik denetle** kutusuyla kapatılabilir.
v1.2.0'dan eski sürümlerde güncelleyici yoktur; v1.2.0 bir kez elle kurulmalıdır.

## Nasıl çalışır
Her XML, arşivle gelen GİB XSLT şablonuyla (yoksa `xslt/` içindeki yedekle) Saxon kullanılarak HTML'e,
ardından Qt WebEngine ile A4 PDF'e çevrilir. İç içe zip'ler açılır, aynı içerikli kopyalar elenir.
PDF basılan sayfalar internete erişemez (yerel içerik uzak adreslere kapalı).

## Geliştirme
```bash
python3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python main.py                      # pencere
.venv/Scripts/python main.py arşiv.rar --out DIR  # otomatik çalıştır ve kapan
```
Sürüm çıkarmak: `version.py`'deki numarayı artırın, sonra
`.venv/Scripts/python build.py --release` → exe derlenir, `eDefterPDF-windows.zip` + `.sha256`
oluşturulur ve `v<sürüm>` GitHub release'i yayınlanır. Kurulu uygulamalar bunu kendiliğinden alır.
