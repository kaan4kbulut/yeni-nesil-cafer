# YENİ NESİL CAFER · bulut sunucusu

Bilgisayarın kapalıyken asistanına telefondan (Telegram) ya da tarayıcıdan ulaşmanı sağlar. Bulut asistan aynı
programın bir kopyasıdır: web'de araştırır, hafızanı bilir (bilgisayar açıkken eşitlenir). **Bilgisayarına
erişemez**: dosyaların gereken işleri kuyruğa bırakır; bilgisayar açılınca programda durum çubuğunda
**☁ N iş** görünür, "yap" dersen yerel asistan yapar ve sonucu Telegram'a / web'e geri gönderir.

Model sunucunun işlemcisinde çalışır (ekran kartı yok): `qwen3.5:4b` ile bir cevap yarım dakika ile birkaç dakika
sürebilir. Hızlı cevap için kısa sorular sor; ağır işleri kuyruğa bırakmasını iste.

## 1. Ücretsiz sunucu (Oracle Cloud Always Free)

1. <https://www.oracle.com/cloud/free/> → hesap aç (kimlik doğrulaması için kart istenebilir; ücret alınmaz).
2. Compute → Instances → **Create instance**: görüntü **Ubuntu 24.04**, şekil **Ampere A1 (VM.Standard.A1.Flex)**,
   4 OCPU, 24 GB bellek (ücretsiz sınırın içinde). SSH anahtarını indir.
3. Sunucunun genel IP adresini not al. Başka port açmana gerek yok: erişim Tailscale üzerinden olacak.

## 2. Paketi gönder ve kur

Bilgisayarında (proje klasöründe):

```bash
paketleme/bulut_paketi.sh                       # dist/yeni-nesil-cafer-bulut.tar.gz oluşur
scp -i anahtar.key dist/yeni-nesil-cafer-bulut.tar.gz ubuntu@SUNUCU_IP:
```

Sunucuda:

```bash
ssh -i anahtar.key ubuntu@SUNUCU_IP
tar xzf yeni-nesil-cafer-bulut.tar.gz && cd yeni-nesil-cafer-bulut
sudo ./sunucu/kur.sh
```

Kurulum Ollama'yı, modeli, Tailscale'i ve servisi kurar; Tailscale için bir giriş bağlantısı gösterir. En sonda
**adres** ve **erişim anahtarı** yazılır.

## 3. Tailscale (yalnızca senin cihazların erişsin)

Telefonuna ve bilgisayarına Tailscale'i kur (<https://tailscale.com/download>), aynı hesapla giriş yap. Web sayfası
ve programın bağlantısı bu özel ağ üzerinden çalışır; sunucu internete açılmaz.

## 4. Programa bağla

Programda **Ayarlar → Bulut asistan**: adres ve anahtarı yaz → **Bağlantıyı dene** → Kaydet. Hafıza dakikada bir
eşitlenir.

## 5. Telegram botu (isteğe bağlı)

1. Telegram'da **@BotFather** → `/newbot` → bir ad ver → verdiği **bot anahtarını** kopyala.
2. Sunucuda: `sudo ./sunucu/kur.sh --telegram BOT_ANAHTARI`
3. Yazdığı kodla bota yaz: `/baglan 123456`. Bot artık yalnızca senin sohbetine cevap verir; başkalarına hiç
   cevap vermez. `/isler` bekleyen işleri gösterir.

## Bakım

- Durum: `systemctl status yeni-nesil-cafer-bulut` · kayıt: `journalctl -u yeni-nesil-cafer-bulut -f`
- Güncelleme: yeni paketi gönder, `sudo ./sunucu/kur.sh` yeniden çalıştır (ayarlar ve hafıza korunur).
- Veriler: `/var/lib/yeni-nesil-cafer` (hafıza, sohbetler, iş kuyruğu, `bulut.json` ayarları).
