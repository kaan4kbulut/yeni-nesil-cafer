#!/usr/bin/env python3
"""
YENİ NESİL CAFER — K serisi OTOMATİK SÜRÜCÜ
============================================

Tek komutla: paketi kurar, K0'dan K10'a kadar her aşamayı Claude Code'a yaptırır,
testleri koşar, kırmızıysa düzelttirir, commit atar, sonrakine geçer.

Kullanım (repo kökünde, cafer-plan.zip'in yanında):

    python otomatik.py                 # kurulum + K0 → K10, durmadan
    python otomatik.py --dur           # her aşamadan sonra Enter bekle
    python otomatik.py --asama K3      # sadece K3
    python otomatik.py --baslangic K4  # K4'ten itibaren
    python otomatik.py --sadece-kur    # sadece paketi kur, aşama koşma
    python otomatik.py --deneme 3      # başarısız aşamayı en fazla 3 kez tekrar dene (varsayılan 2)
    python otomatik.py --tam-yetki     # Claude Code'u izin sormadan çalıştır (uyarıyı oku)
    python otomatik.py --python ~/.local/share/yeni-nesil-cafer-app/python/bin/python3   # testler bu Python'la
    python otomatik.py --bekle         # kullanım limitinde sıfırlanma saatine kadar uyu, aynı aşamayı yeniden başlat
    python otomatik.py --model opus    # bütün oturumlar bu modelle (varsayılan sonnet; adında "mimari" geçen aşama opus)

Kesilirse (Ctrl+C, elektrik, hata) tekrar `python otomatik.py` → kaldığı aşamadan sürer.

Nasıl çalışır:
  - Her aşama için TAZE `claude -p` oturumları: YAPILACAKLAR'daki her alt başlık (`###`) ayrı oturum (20 dk;
    zaman aşımında SIGINT, 30 sn bekleme). Varsayılan model sonnet; denetçi turu ayrı bir haiku oturumu (ana
    oturuma yalnızca denetçinin SONUÇ satırı ve rapor yolu geçer). İsteme SORULAR/KONTROL_LISTEN'in son 10 maddesi eklenir.
  - "hit your … limit" / "usage limit" görülürse aşama bitmiş SAYILMAZ, commit ATILMAZ; yarım değişiklikler stash'e,
    sıfırlanma saati loglanır ve sürücü durur (`--bekle` ile o saate kadar uyuyup aynı aşamayı yeniden başlatır).
  - Aşama bitince sürücü kendisi kontrol eder: pytest (yoksa unittest) + import dumanı + açık kutucuklar
    + Claude'un son mesajındaki SONUÇ/TEST satırı (KALDI → düzeltme turu; sürücünün kendi yazdığı
    KONTROL_LISTEN/log dosyaları "değişiklik" sayılmaz).
  - Kırmızıysa aynı aşamayı "önce kırmızıları düzelt" talimatıyla tekrar koşar.
  - Yeşilse commit + `k<n>-bitti` etiketi. Senin elle bakacağın şeyler NOTLAR/KONTROL_LISTEN.md'de birikir.
  - Terminalde canlı çubuk: aşama x/11, Claude'un görev listesi (.cafer/ilerleme.json), geçen/kalan süre.
  - Aşama bitince ve sürücü durunca masaüstü bildirimi (.claude/ilerleme/bildir.py).

İzinler: .claude/settings.json'daki permissions.allow listesi (paketle gelir) test/git/pip gibi
komutları önceden onaylar. Listede olmayan bir şeyi Claude yapamaz ve raporlar. `--tam-yetki`
bu sınırı kaldırır (Claude Code'un --dangerously-skip-permissions'ı): sadece kendi
bilgisayarında, yedeği olan bir repoda kullan.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

KOK = Path.cwd()
CAFER = KOK / ".cafer"
DURUM = CAFER / "otomatik.json"
ILERLEME = CAFER / "ilerleme.json"
LOGLAR = KOK / "NOTLAR" / "otomatik"
KONTROL_LISTEN = KOK / "NOTLAR" / "KONTROL_LISTEN.md"
SORULAR = KOK / "NOTLAR" / "SORULAR.md"
PY = sys.executable

ONSOZ = """OTOMATİK MOD — dikkatle oku:
- Bu oturumda kimse onay veremez, soru cevaplayamaz. "Onayımı bekle" diyen her yerde beklemek YERİNE en makul varsayımı seç, varsayımı NOTLAR/ altındaki aşama notuna yaz ve devam et.
- Kullanıcıya sorman gereken bir şey varsa NOTLAR/SORULAR.md'nin SONUNA "K<n> | soru | verdiğin geçici karar" satırı ekle, geçici kararla devam et. SORULAR.md ve KONTROL_LISTEN.md'nin tamamını okuma; son maddeleri aşağıda.
- Commit ATMA; sürücü atar. git push, git reset --hard, rm -rf kullanma.
- Görev listesini (TaskCreate/TaskUpdate) mutlaka kullan: her madde bir görev, ilk görevin başlığı aşama koduyla başlasın, başladığını in_progress, bitirdiğini completed yap.
- Bitirince son mesajın şu biçimde olsun:
  SONUÇ: TAMAM | KISMEN | KALDI
  DEĞİŞEN: <dosya sayısı>
  TEST: <geçti/kaldı>
  NOT: <tek satır>
"""


# ----------------------------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------------------------
def yaz(*a, **k):
    print(*a, **k, flush=True)


def calistir(cmd, cwd=KOK, girdi=None, sessiz=False, zaman_asimi=None):
    """Komutu çalıştır; (kod, çıktı) döner. Hiç exception fırlatmaz."""
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd), input=girdi, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=zaman_asimi,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        cikti = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        if not sessiz and p.returncode != 0:
            yaz(f"   ⚠ komut {p.returncode} döndü: {' '.join(map(str, cmd))[:80]}")
        return p.returncode, cikti
    except FileNotFoundError:
        return 127, f"bulunamadı: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "zaman aşımı"
    except Exception as e:  # pragma: no cover
        return 1, str(e)


NAZIK_BEKLEME = 30  # SIGINT'ten sonra Claude'un toparlanıp çıkması için saniye; sonra SIGTERM/kill


def calistir_nazik(cmd, girdi=None, zaman_asimi=None, cwd=KOK, bekleme: float = NAZIK_BEKLEME):
    """Claude koşusu için: zaman aşımında süreç ÖLDÜRÜLMEZ; önce SIGINT (Ctrl+C gibi), `bekleme` sn sonra
    SIGTERM, yine bitmezse kill. (kod, o ana kadarki çıktı) döner; zaman aşımı kodu 124."""
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except FileNotFoundError:
        return 127, f"bulunamadı: {cmd[0]}"
    try:
        cikti, _ = p.communicate(girdi, timeout=zaman_asimi)
        return p.returncode, cikti or ""
    except subprocess.TimeoutExpired:
        pass
    import signal

    for sinyal, sure in ((signal.SIGINT, bekleme), (signal.SIGTERM, 10)):
        try:
            p.send_signal(sinyal)
            cikti, _ = p.communicate(timeout=sure)
            return 124, (cikti or "") + "\n[zaman aşımı: sinyalle durduruldu]"
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            break
    p.kill()
    cikti, _ = p.communicate()
    return 124, (cikti or "") + "\n[zaman aşımı: öldürüldü]"


def git(*args, sessiz=True):
    return calistir(["git", *args], sessiz=sessiz)


def json_oku(yol: Path, varsayilan=None):
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return {} if varsayilan is None else varsayilan


def json_yaz(yol: Path, veri):
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")


def sure_metni(sn: float) -> str:
    sn = int(max(0, sn))
    if sn < 60:
        return f"{sn}sn"
    dk = sn // 60
    return f"{dk}dk" if dk < 60 else f"{dk // 60}sa{dk % 60:02d}dk"


def cubuk(oran: float, genislik=14) -> str:
    dolu = int(round(max(0.0, min(1.0, oran)) * genislik))
    return "█" * dolu + "░" * (genislik - dolu)


def bildir(baslik: str, metin: str):
    betik = KOK / ".claude" / "ilerleme" / "bildir.py"
    if betik.exists():
        calistir([PY, str(betik)], girdi=json.dumps({
            "hook_event_name": "Stop", "cwd": str(KOK),
            "last_assistant_message": f"{baslik}: {metin}",
        }), sessiz=True)
    yaz("\a", end="")


def ek_not(yol: Path, metin: str):
    yol.parent.mkdir(parents=True, exist_ok=True)
    with open(yol, "a", encoding="utf-8") as f:
        f.write(metin.rstrip() + "\n")


# ----------------------------------------------------------------------------------------------
# Aşama tanımları
# ----------------------------------------------------------------------------------------------
def komut_metni(ad: str, argumanlar: str) -> str:
    """.claude/commands/<ad>.md içeriğini frontmatter'sız, $ARGUMENTS yerleştirilmiş döner."""
    for yol in (KOK / ".claude" / "commands" / f"{ad}.md", KOK / ".claude" / "skills" / ad / "SKILL.md"):
        if yol.exists():
            t = yol.read_text(encoding="utf-8")
            t = re.sub(r"^---\n.*?\n---\n", "", t, count=1, flags=re.S)
            return t.replace("$ARGUMENTS", argumanlar)
    return f"/{ad} {argumanlar}"


def ajan_metni(ad: str) -> str:
    """.claude/agents/<ad>.md gövdesi (frontmatter'sız); yoksa .claude/skills/<ad>/SKILL.md; o da yoksa kısa yedek."""
    for yol in (KOK / ".claude" / "agents" / f"{ad}.md", KOK / ".claude" / "skills" / ad / "SKILL.md"):
        if yol.exists():
            return re.sub(r"^---\n.*?\n---\n", "", yol.read_text(encoding="utf-8"), count=1, flags=re.S)
    return ("Değişikliği (git diff) bağımsız gözle denetle: testleri koş, mimari kuralları (çekirdekte Qt yok, model adı "
            "kodda yok, yeni modülün testi var) uygula. Rapor: '## Sonuç: GEÇTİ | ŞARTLI | KALDI', sonra Engelleyici / Uyarı.")


def p_asama(kod: str, ek: str = ""):
    """Aşama koşusu; `asama_kos` YAPILACAKLAR'daki alt başlıklara göre ayrı oturumlara böler (3c)."""
    return ("asama", kod, ek)


def p_denetci(kod: str, odak: str = ""):
    """Denetçi turu: ayrı bir haiku oturumu; ana oturuma yalnızca SONUÇ satırı + rapor yolu geçer (3d)."""
    return ("denetci", kod, odak)


def p_denetci_metni(kod: str, odak: str = "") -> str:
    return (
        "DENETÇİ TURU — kod DEĞİŞTİRME, yalnızca bul ve raporla. Kimse soru cevaplayamaz; eksik bilgiyi varsayım olarak yaz.\n\n"
        + ajan_metni("denetci")
        + f"\n\nDenetlenecek değişiklik: `git diff {kod.lower()}-basi` (aşama başı etiketi; çalışma ağacı dahil). {odak}\n"
        "Raporun İLK satırı mutlaka `## Sonuç: GEÇTİ | ŞARTLI | KALDI` olsun; sonra Engelleyici / Uyarı / Testler."
    )


def model_sec(baslik: str, istenen: str = "") -> str:
    """3a: --model verildiyse o; aşama adında "mimari" geçiyorsa opus; yoksa sonnet."""
    if istenen:
        return istenen
    return "opus" if "mimari" in baslik.lower() else "sonnet"


def son_maddeler(yol: Path, n: int = 10, genislik: int = 240) -> list[str]:
    """Dosyadaki `- ` ile başlayan SON n madde (3e: SORULAR/KONTROL_LISTEN tam değil, son maddeler isteme girer)."""
    if not yol.exists():
        return []
    maddeler = [s.rstrip() for s in yol.read_text(encoding="utf-8").splitlines() if re.match(r"^\s*-\s", s)]
    return [(m if len(m) <= genislik else m[:genislik - 1] + "…") for m in maddeler[-n:]]


def baglam_ozeti(n: int = 10) -> str:
    parca = []
    for ad, yol in (("SORULAR.md", SORULAR), ("KONTROL_LISTEN.md", KONTROL_LISTEN)):
        m = son_maddeler(yol, n)
        if m:
            parca.append(f"NOTLAR/{ad} — son {len(m)} madde (dosyanın tamamını OKUMA; yeni madde sona eklenir):\n" + "\n".join(m))
    return "\n\n".join(parca)


def onsoz() -> str:
    """ONSOZ + not dosyalarının son maddeleri (her oturumun başına)."""
    b = baglam_ozeti()
    return ONSOZ + ("\n" + b + "\n" if b else "")


def alt_basliklar(kod: str) -> list[tuple[str, int]]:
    """3c: YAPILACAKLAR'da aşamanın alt başlıkları → [(başlık, açık madde sayısı)]; ilk öğe `###` öncesi "ana maddeler".
    Aşamada hiç `###` yoksa boş liste (aşama tek oturumda koşar)."""
    y = KOK / "YAPILACAKLAR.md"
    if not y.exists():
        return []
    m = re.search(rf"^##\s+Aşama\s+{kod}\b.*?(?=^##\s+|\Z)", y.read_text(encoding="utf-8"), re.S | re.M)
    if not m:
        return []
    parcalar = re.split(r"^###\s+(.+?)\s*$", m.group(0), flags=re.M)  # [ana, başlık1, gövde1, başlık2, gövde2, …]
    if len(parcalar) < 3:
        return []

    def acik(t: str) -> int:
        return len(re.findall(r"^\s*-\s*\[ \]", t, re.M))

    sonuc = [("ana maddeler", acik(parcalar[0]))]
    for i in range(1, len(parcalar), 2):
        sonuc.append((parcalar[i].strip(), acik(parcalar[i + 1])))
    return sonuc


ASAMALAR = [
    # kod, başlık, koşular (prompt üreticileri), elle kontrol listesi
    ("K0", "Mevcut durum haritası", [lambda: p_asama("K0")], [
        "NOTLAR/MEVCUT_DURUM.md'yi oku: projeni doğru anlamış mı? Mimari ihlal listesi mantıklı mı?",
    ]),
    ("K1", "Çekirdek / arayüz ayrımı", [
        lambda: p_asama("K1", "Geri dönüş noktası: git tag v-k0-baslangic. Önce mimar ajanıyla plan çıkar, sonra uygula; her taşıma adımından sonra masaüstü import dumanı yeşil kalsın."),
        lambda: p_denetci("K1"),
    ], [
        "Masaüstü uygulamasını aç: sohbet, dosya aracı, komut çalıştırma eskisi gibi mi?",
    ]),
    ("K2", "Donanım profili ve kademe", [
        lambda: p_asama("K2"),
        lambda: komut_metni("profil", "benchmark"),
        lambda: (
            "ayar/modeller.json'daki örnek model adlarını gerçek adlarla değiştir. Web'de araştır: Ollama'da yaygın "
            "kullanılan, iyi puanlanan açık modellerden 3B, 7–8B, 14B, 32B sınıfında birer aday; Claude ve "
            "OpenAI-uyumlu bulut sağlayıcılardan 'ucuz-hızlı' ve 'güçlü' roller için birer aday. Kademe × rol "
            "tablosunu NOTLAR/MODELLER_ONERI.md'ye yaz (her satırda neden). modeller.json'a en makul seçimi yaz ve "
            "dosyaya \"gecici\": true alanı ekle; kullanıcı sonra değiştirecek."
        ),
    ], [
        "Durum çubuğundaki kademe laptop'unla uyuşuyor mu? (NOTLAR/<tarih>-K2.md ve .cafer/profil.json)",
        "NOTLAR/MODELLER_ONERI.md'ye bak, ayar/modeller.json'daki geçici seçimleri beğenmediysen değiştir, \"gecici\" alanını sil.",
    ]),
    ("K3", "Model yönlendirici", [lambda: p_asama("K3")], [
        "Programı aç: cevapların yanında 'sağlayıcı/model — neden' görünüyor mu?",
        "Ollama'yı kapat, sohbet et → bulut anahtarı varsa buluta düşmeli, yoksa 'çevrimdışı' demeli.",
        "Gizlilik modunu 'yerel' yap → bulut kullanılmamalı. Sonra 'karma'ya al.",
    ]),
    ("K4", "Görev motoru", [
        lambda: p_asama("K4", "Önce mimar ajanıyla plan çıkar (şema kısıtlı araç seçimi kodunun planlayıcıya taşınması, SQLite deposunun mevcut veri dosyalarıyla çakışması, devam ettirme), sonra uygula."),
        lambda: p_denetci("K4"),
    ], [
        "Programa yaz: 'Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle.' Plan görünüyor mu?",
        "Adım 1 bitince programı kapat/aç, 'devam et' de → kaldığı yerden sürüyor mu?",
    ]),
    ("K5", "Yetenek kayıt defteri", [
        lambda: p_asama("K5"),
        lambda: komut_metni("yetenek-ekle", 'saat_dilimi "Verilen şehir adı için şu anki saati ve UTC farkını döner. Girdi: sehir (string). Çıktı: saat (string), utc_fark (string). İzin: ag."'),
    ], [
        "Yetenekler sekmesinde saat_dilimi aktif mi? 'İstanbul'da saat kaç?' deyince planlayıcı onu seçiyor mu?",
        "K4'teki .txt görevini tekrar ver → adımlarda yetenek adları görünüyor mu?",
    ]),
    ("K6", "Hata analizi ve kendini genişletme", [
        lambda: p_asama("K6", "Bu koşuda SADECE: analiz/hata.py sınıflandırıcı, guvenlik.py + ayar/guvenlik.toml, yetenek/yukleyici.py, yürütücü↔hata analizi bağlantısı, onay kuyruğu, NOTLAR/HATALAR.md. uretici.py maddesini YAPMA, [ ] bırak."),
        lambda: p_asama("K6", "Kalan madde: yetenek/uretici.py ve testleri. Kod ajanı olarak ayar.toml [cli_ajan] tercihindeki ilk bulunanı kullan; hiçbiri yoksa bulut 'kod' rolü. Sandbox testi geçmeden hiçbir üretilen yetenek kayıt defterine girmesin; giren yetenek kaynak=uretildi, guvenilir=false."),
        lambda: p_denetci("K6", "Özellikle: onaysız kurulum yolu var mı, sandbox izin dışı erişimi gerçekten engelliyor mu, API anahtarları alt sürece sızıyor mu."),
    ], [
        "Bir yeteneğin pip paketini kaldır, o yeteneği kullan → 'eksik bağımlılık, kurayım mı?' sormalı; onaylayınca kurup devam etmeli.",
        "Yeteneği olmayan bir iş iste ('şu PDF'in tablolarını Excel'e çıkar') → eksik yeteneği söyleyip üretme onayı istiyor mu? Üretip görevi bitiriyor mu?",
    ]),
    ("K7", "Ölçüm ve sınav", [lambda: p_asama("K7")], [
        "Modeller sekmesinde tok/sn ve başarı oranları var mı? 'Listeyi yenile' modeller.json'u güncelliyor mu?",
    ]),
    ("K8", "Sunucu modu", [
        lambda: p_asama("K8"),
        lambda: komut_metni("sunucu", "docker (docker kurulu değilse docker kısmını atla, nedenini yaz)"),
        lambda: (
            "docs/SUNUCU_KURULUM.md'yi, taze bir Ubuntu VPS'te kopyala-yapıştır ile çalışan tek betiğe dönüştür: sunucu/kur.sh. "
            "Docker + compose kurar, repoyu klonlar, .env'i sorarak doldurur (CAFER_TOKEN'ı kendi üretir), docker compose up -d, "
            "Caddy ile alan adına HTTPS. İdempotent olsun. VPS'te çalıştırılacak tek satır komutu docs/SUNUCU_KURULUM.md'nin başına yaz."
        ),
    ], [
        "Telefonu aynı Wi-Fi'ye bağla, NOTLAR/<tarih>-K8.md'deki adresi aç, token'ı gir, görev başlat.",
        "VPS'e SSH ile gir, docs/SUNUCU_KURULUM.md başındaki tek satırı çalıştır.",
    ]),
    ("K9", "Uzak mod ve senkron", [lambda: p_asama("K9")], [
        "Masaüstünde 'uzak sunucu' ayarına VPS adresi + token gir. Bilgisayar kapalıyken telefondan görev ver → açınca masaüstünde görünüyor mu?",
    ]),
    ("K10", "Kurulum ve sadeleştirme", [
        lambda: p_asama("K10"),
    ], [
        "ayar.toml'da kademe_kilidi = \"dusuk\" yap, programı aç → sade arayüz, hızlı açılış, bulut anahtarıyla görev bitiyor mu? Sonra kilidi boşalt.",
    ]),
    ("K11", "Dağıtım (Windows · macOS · Linux)", [
        lambda: p_asama("K11", "Yerleşik sağlayıcı (llama-cpp-python) için CI'da indirilen küçük bir test GGUF'u kullan; büyük model dosyasını repoya KOYMA. paketle.py'yi bu makinede --dry-run ile koş; gerçek paketi üretmeye çalışma (uzun sürer), sadece betiklerin ve workflow'un hazır olduğunu göster."),
        lambda: p_denetci("K11", "Özellikle: model dosyası ya da 50 MB üstü bir şey git'e girmiş mi (git ls-files ile boyut kontrolü), boyut kapısı gerçekten çalışıyor mu, güncelleyici modeli silmiyor mu."),
        lambda: (
            "Kapanış: docs/MIMARI.md'yi gerçekle karşılaştır, yapılmayan/değişen kararları dokümana işle ('değişti: …'). "
            "/kontrol'ün yaptığı kontrolleri koş, tamamen yeşil olana kadar düzelt. NOTLAR/ altına K serisi kapanış notu yaz "
            "(ne yapıldı, ne ertelendi, sonraki 5 öneri). CHANGELOG.md'ye sürüm notu ekle. NOTLAR/SORULAR.md varsa "
            "kullanıcının cevaplaması gereken soruları en üste toparla."
        ),
    ], [
        "Kendi makinende: `python dagitim/paketle.py --tam` ile Tam paketi üret (uzun sürer); temiz bir kullanıcı hesabında ya da sanal makinede internet KAPALIYKEN kur, sohbet et.",
        "Sihirbazda sistem analizi, 'yerleşik modelle başla' ve eklenti önerileri ekranları geliyor mu?",
        "NOTLAR/SORULAR.md'deki soruları cevapla; geçici kararları beğenmediysen /hata-analiz ya da /asama ile düzelttir.",
        "git checkout main && git merge k-serisi && git tag v3.0.0 && git push --tags  → Actions üç platformda derleyip Release'e 6 dosya yüklemeli.",
    ]),
]
KODLAR = [a[0] for a in ASAMALAR]


# ----------------------------------------------------------------------------------------------
# Kurulum
# ----------------------------------------------------------------------------------------------
def settings_birlestir(hedef: Path, ornek: Path):
    mevcut = json_oku(hedef) if hedef.exists() else {}
    yeni = json_oku(ornek)
    yeni.pop("_aciklama", None)

    def komut_duzelt(k: str) -> str:
        k = k.replace("${CLAUDE_PROJECT_DIR}", KOK.as_posix())
        return re.sub(r'^python3?\s', f'"{PY}" ', k)

    if "statusLine" not in mevcut and "statusLine" in yeni:
        sl = dict(yeni["statusLine"])
        sl["command"] = komut_duzelt(sl["command"])
        mevcut["statusLine"] = sl
    hooks = mevcut.setdefault("hooks", {})
    for olay, girisler in (yeni.get("hooks") or {}).items():
        liste = hooks.setdefault(olay, [])
        for g in girisler:
            g = json.loads(json.dumps(g))
            for h in g.get("hooks", []):
                h["command"] = komut_duzelt(h["command"])
            imza = json.dumps(g, sort_keys=True)
            if not any(json.dumps(x, sort_keys=True) == imza for x in liste):
                liste.append(g)
    izin = mevcut.setdefault("permissions", {})
    for anahtar in ("allow", "deny"):
        birlesik = list(izin.get(anahtar, []))
        for x in (yeni.get("permissions") or {}).get(anahtar, []):
            if x not in birlesik:
                birlesik.append(x)
        if birlesik:
            izin[anahtar] = birlesik
    json_yaz(hedef, mevcut)


def paket_kur(zip_yolu: Path) -> list[str]:
    """Zip'i repoya birleştirir; raporu (satır listesi) döner."""
    rapor = []
    gecici = CAFER / "_paket"
    if gecici.exists():
        shutil.rmtree(gecici)
    with zipfile.ZipFile(zip_yolu) as z:
        z.extractall(gecici)
    kaynak = gecici / "cafer-plan" if (gecici / "cafer-plan").exists() else gecici
    for yol in sorted(kaynak.rglob("*")):
        if yol.is_dir():
            continue
        goreli = yol.relative_to(kaynak)
        if goreli.name in ("BENIOKU.md", "settings.ornek.json") or goreli.name == Path(__file__).name:
            continue
        hedef = KOK / goreli
        hedef.parent.mkdir(parents=True, exist_ok=True)
        if hedef.exists():
            if hedef.read_bytes() == yol.read_bytes():
                continue
            if goreli.parts[0] == ".claude" or goreli.name in ("ADIMLAR.md",):
                eski = hedef.with_name(hedef.stem + "-eski" + hedef.suffix)
                shutil.move(str(hedef), str(eski))
                rapor.append(f"mevcut {goreli} → {eski.name} olarak korundu")
            elif goreli.parts[0] == "docs":
                eski = hedef.with_name(hedef.stem + "-eski" + hedef.suffix)
                shutil.move(str(hedef), str(eski))
                rapor.append(f"mevcut {goreli} → {eski.name} olarak korundu")
        shutil.copy2(yol, hedef)
    ornek = kaynak / ".claude" / "settings.ornek.json"
    if ornek.exists():
        settings_birlestir(KOK / ".claude" / "settings.json", ornek)
        rapor.append(".claude/settings.json birleştirildi (durum çubuğu, hook'lar, izinler)")
    shutil.rmtree(gecici, ignore_errors=True)
    zip_yolu.unlink(missing_ok=True)
    gi = KOK / ".gitignore"
    icerik = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if ".cafer/" not in icerik:
        gi.write_text(icerik.rstrip("\n") + ("\n" if icerik else "") + ".cafer/\n", encoding="utf-8")
        rapor.append(".gitignore ← .cafer/")
    return rapor


def betikleri_test_et() -> list[str]:
    sorun = []
    durum = KOK / ".claude" / "ilerleme" / "durum.py"
    kod, cikti = calistir([PY, str(durum)], girdi='{"model":{"display_name":"test"},"context_window":{"used_percentage":12}}', sessiz=True)
    if kod != 0 or not cikti.strip():
        sorun.append(f"durum.py çalışmadı: {cikti[:120]}")
    return sorun


def claude_yolu() -> str | None:
    for ad in ("claude", "claude.cmd", "claude.exe"):
        y = shutil.which(ad)
        if y:
            return y
    return None


def kurulum(args) -> None:
    yaz("━" * 70)
    yaz(" KURULUM")
    yaz("━" * 70)
    if not (KOK / ".git").exists():
        yaz("✖ Burası bir git deposu değil. Repo kökünde çalıştır (CLAUDE.md'nin olduğu klasör).")
        sys.exit(1)
    if not claude_yolu():
        yaz("✖ `claude` komutu bulunamadı. Claude Code kurulu ve PATH'te olmalı: https://claude.com/claude-code")
        sys.exit(1)
    if not (KOK / "CLAUDE.md").exists():
        yaz("⚠ CLAUDE.md yok; Claude Code eklentiyi yeni bir CLAUDE.md olarak yazacak.")

    # dal
    _, dal = git("rev-parse", "--abbrev-ref", "HEAD")
    dal = dal.strip()
    if dal != "k-serisi":
        kod, _ = git("rev-parse", "--verify", "k-serisi")
        git("checkout", "k-serisi") if kod == 0 else git("checkout", "-b", "k-serisi")
        yaz("• dal: k-serisi")
    _, kirli = git("status", "--porcelain")
    if kirli.strip():
        git("add", "-A")
        git("commit", "-m", "otomatik: başlangıçtaki kaydedilmemiş değişiklikler")
        yaz("• kaydedilmemiş değişiklikler ayrı commit'e alındı")

    zip_yolu = KOK / "cafer-plan.zip"
    if zip_yolu.exists():
        for satir in paket_kur(zip_yolu):
            yaz(f"• {satir}")
        yaz("• paket açıldı ve birleştirildi")
    elif not (KOK / ".claude" / "commands" / "asama.md").exists() and not (KOK / ".claude" / "skills" / "asama").exists():
        yaz("✖ cafer-plan.zip yok ve paket kurulu değil. Zip'i repo köküne koy.")
        sys.exit(1)
    else:
        yaz("• paket zaten kurulu")

    for s in betikleri_test_et():
        yaz(f"⚠ {s}")

    # pytest
    kod, _ = calistir([PY, "-m", "pytest", "--version"], sessiz=True)
    if kod != 0:
        yaz("• pytest kuruluyor…")
        kod, _ = calistir([PY, "-m", "pip", "install", "-q", "pytest"], sessiz=True)
        if kod != 0:
            kod, _ = calistir([PY, "-m", "pip", "install", "-q", "--break-system-packages", "pytest"], sessiz=True)
        if kod != 0:
            yaz("⚠ pytest kurulamadı; sürücü testleri unittest ile koşacak.")
    pytest_var = kod == 0

    # temel çizgi: import şu an çalışıyor mu?
    kod, _ = calistir([PY, "-c", "import asistan"], sessiz=True)
    d = json_oku(DURUM)
    d.setdefault("temel_import_ok", kod == 0)
    d["pytest_var"] = pytest_var
    d.setdefault("tamamlanan", [])
    d.setdefault("sureler", {})
    d.setdefault("baslangic", time.time())
    json_yaz(DURUM, d)

    git("add", "-A")
    git("commit", "-m", "K serisi: mimari doküman, komutlar, aşama planı, ilerleme çubuğu, otomatik sürücü")
    kod, _ = git("rev-parse", "v-k0-baslangic")
    if kod != 0:
        git("tag", "v-k0-baslangic")
        yaz("• etiket: v-k0-baslangic")

    # Claude'un yargı gerektiren kurulum işleri
    if (KOK / "CLAUDE_EKLENTI.md").exists() or (KOK / "YAPILACAKLAR_EK.md").exists():
        yaz("• CLAUDE.md ve YAPILACAKLAR.md birleştirmesi Claude Code'a veriliyor…")
        prompt = ONSOZ + """
Kurulum görevi:
1. CLAUDE_EKLENTI.md içeriğini CLAUDE.md'nin sonuna işle (CLAUDE.md parçalara bölünmüşse uygun parçaya; CLAUDE.md yoksa oluştur). Sonra CLAUDE_EKLENTI.md'yi sil.
2. YAPILACAKLAR_EK.md'deki K0–K10 aşamalarını YAPILACAKLAR.md'nin sonuna taşı (dosya yoksa oluştur). Mevcut planımdaki sınav seti, güçlü yönetici model, şema kısıtlı araç seçimi, bulut sunucu, UI sadeleştirme gibi maddeler K serisiyle çakışıyorsa ilgili K aşamasının içine "mevcut plandan taşındı" notuyla birleştir; çift madde bırakma. Sonra YAPILACAKLAR_EK.md'yi sil.
3. .claude/settings.json'daki hook ve statusLine komutlarını bu makinede bir kez çalıştırıp test et (bildir.py'ye {"hook_event_name":"Stop","last_assistant_message":"kurulum tamam"} ver; bildirim çıkmazsa bu işletim sisteminde çalışan yöntemle düzelt).
4. Hiçbir Python dosyasına (asistan/ altı) dokunma.
"""
        kodu, cikti = claude_kos("KUR", prompt, args, ad="kurulum")
        if limit_mi(kodu, cikti):
            yaz("✖ Claude Code çalışamadı (limit ya da oturum sorunu). Limit dolunca tekrar `python otomatik.py`.")
            sys.exit(2)
        git("add", "-A")
        git("commit", "-m", "K serisi kurulum: CLAUDE.md ve YAPILACAKLAR.md birleştirildi")
    yaz("✔ kurulum tamam\n")


# ----------------------------------------------------------------------------------------------
# Claude Code koşusu + canlı çubuk
# ----------------------------------------------------------------------------------------------
class Cubuk:
    def __init__(self, kod: str, sira: int, toplam: int, genel_baslangic: float, sureler: dict):
        self.kod, self.sira, self.toplam = kod, sira, toplam
        self.genel_baslangic, self.sureler = genel_baslangic, sureler
        self.asama_baslangic = time.time()
        self.dur = threading.Event()

    def satir(self) -> str:
        il = json_oku(ILERLEME)
        parca = [f"[{self.sira}/{self.toplam}] {self.kod} {cubuk((self.sira - 1) / self.toplam)}"]
        if il.get("toplam"):
            b, t = int(il.get("biten", 0)), int(il["toplam"])
            parca.append(f"görev {cubuk(b / t, 10)} {b}/{t} %{int(b / t * 100)}")
            if il.get("su_an") and b < t:
                parca.append("▶ " + re.sub(r"^\s*K\d+\s*[:\-–]\s*", "", il["su_an"])[:36])
        else:
            parca.append("Claude çalışıyor…")
        gecen = time.time() - self.asama_baslangic
        parca.append(sure_metni(gecen))
        biten = [v for v in self.sureler.values() if v]
        if biten:
            kalan = sum(biten) / len(biten) * (self.toplam - self.sira + 1) - gecen
            parca.append(f"~{sure_metni(max(0, kalan))} kaldı")
        return " │ ".join(parca)

    def calis(self):
        if not sys.stdout.isatty():
            self.dur.wait()
            return
        genislik = shutil.get_terminal_size((100, 20)).columns - 1
        while not self.dur.is_set():
            s = self.satir()[:genislik]
            sys.stdout.write("\r" + s.ljust(genislik))
            sys.stdout.flush()
            self.dur.wait(2)
        sys.stdout.write("\r" + " " * genislik + "\r")
        sys.stdout.flush()


SON_LOG: Path | None = None  # son claude oturumunun log dosyası (denetçi raporunu ana oturuma yol olarak vermek için)


def claude_kos(kod: str, prompt: str, args, ad: str = "", cubuk_obj: Cubuk | None = None, model: str = "sonnet",
               zaman_asimi_dk: int | None = None) -> tuple[int, str]:
    """Taze bir claude -p oturumu. (çıkış kodu, çıktı) döner ve NOTLAR/otomatik/ altına loglar.
    `model`: sonnet/opus/haiku (3a); `zaman_asimi_dk`: bu oturuma özel süre (None → --zaman-asimi)."""
    global SON_LOG
    LOGLAR.mkdir(parents=True, exist_ok=True)
    zaman = time.strftime("%Y-%m-%d_%H-%M-%S")
    log = LOGLAR / f"{zaman}_{kod}_{ad or 'kosu'}.log"
    cmd = [claude_yolu(), "-p", "--output-format", "text", "--model", model]
    if args.tam_yetki:
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd += ["--permission-mode", "acceptEdits"]
    t = None
    if cubuk_obj:
        t = threading.Thread(target=cubuk_obj.calis, daemon=True)
        t.start()
    dk = args.zaman_asimi if zaman_asimi_dk is None else zaman_asimi_dk
    try:
        kodu, cikti = calistir_nazik(cmd, girdi=prompt, zaman_asimi=(dk * 60) if dk else None)
    finally:
        if cubuk_obj:
            cubuk_obj.dur.set()
            t.join(timeout=3)
    log.write_text(f"### MODEL {model} · zaman aşımı {dk or 'yok'} dk\n### PROMPT\n{prompt}\n\n### ÇIKTI (kod {kodu})\n{cikti}",
                   encoding="utf-8")
    SON_LOG = log
    son = cikti.strip().splitlines()
    ozet = "\n".join(son[-6:]) if son else "(çıktı yok)"
    yaz("   ┌ Claude:")
    for s in ozet.splitlines():
        yaz("   │ " + s[:110])
    yaz(f"   └ log: {log.relative_to(KOK)}")
    if kodu != 0:
        yaz(f"   ⚠ claude {kodu} ile çıktı")
    return kodu, cikti


# ----------------------------------------------------------------------------------------------
# Kontrol ve döngü
# ----------------------------------------------------------------------------------------------
def python_sec(istenen: str = "") -> str:
    """Kontrol Python'u: --python verildiyse o; yoksa proje `.venv`'i; o da yoksa sürücünün yorumlayıcısı."""
    if istenen:
        return istenen
    for aday in (KOK / ".venv" / "bin" / "python", KOK / ".venv" / "Scripts" / "python.exe"):
        if aday.is_file():
            return str(aday)
    return sys.executable


def acik_kutular(kod: str) -> int | None:
    """YAPILACAKLAR.md'de aşamanın açık [ ] madde sayısı; bölüm (ya da dosya) yoksa None — aşama geçmiş SAYILMAZ."""
    y = KOK / "YAPILACAKLAR.md"
    if not y.exists():
        return None
    t = y.read_text(encoding="utf-8")
    m = re.search(rf"^##\s+Aşama\s+{kod}\b.*?(?=^##\s+|\Z)", t, re.S | re.M)
    return len(re.findall(r"^\s*-\s*\[ \]", m.group(0), re.M)) if m else None


def kontrol(kod: str) -> list[str]:
    sorun = []
    d = json_oku(DURUM)
    if (KOK / "testler").exists():
        if d.get("pytest_var", True):
            k, c = calistir([PY, "-m", "pytest", "testler", "-q", "-x", "--no-header", "-p", "no:cacheprovider"], sessiz=True, zaman_asimi=1800)
            etiket = "pytest"
        else:  # pytest yoksa unittest ile koş; test kontrolü asla atlanmaz
            k, c = calistir([PY, "-m", "unittest", "discover", "-s", "testler", "-q"], sessiz=True, zaman_asimi=1800)
            etiket = "unittest"
        if k not in (0, 5):  # 5 = test bulunamadı
            satirlar = [s for s in c.strip().splitlines() if s.strip()]
            sorun.append(f"{etiket} kırmızı: " + (satirlar[-1][:100] if satirlar else "") + "\n" + "\n".join(satirlar[-15:]))
    if d.get("temel_import_ok", True):
        k, c = calistir([PY, "-c", "import asistan"], sessiz=True, zaman_asimi=120)
        if k != 0:
            satirlar = [s for s in c.strip().splitlines() if s.strip()]
            sorun.append("`import asistan` kırıldı: " + (satirlar[-1][:100] if satirlar else "") + "\n" + "\n".join(satirlar[-8:]))
    if kod not in ("K0", "K1"):
        k, c = calistir([PY, "-c", "import asistan.cekirdek"], sessiz=True, zaman_asimi=120)
        if k != 0:
            satirlar = [s for s in c.strip().splitlines() if s.strip()]
            sorun.append("`import asistan.cekirdek` kırıldı: " + (satirlar[-1][:100] if satirlar else "") + "\n" + "\n".join(satirlar[-8:]))
    return sorun


LIMIT_DESENI = re.compile(
    r"(usage limit|rate limit|limit reached|hit your limit|out of (usage|credits|quota)|quota|resets? at|"
    r"kullan[ıi]m limit|limit doldu|overloaded|too many requests|not logged in|please (log|sign) in|"
    r"authentication|invalid api key|credit balance)", re.I,
)
# 3b: bu ifadeler çıktının NERESİNDE ve çıktı ne kadar uzun olursa olsun limittir ("hit your session limit",
# "hit your weekly limit", "usage limit"); aşama bitmiş sayılmaz, commit atılmaz.
LIMIT_KESIN = re.compile(r"hit your (?:[\w-]+ ){0,3}limit|usage limit", re.I)


def limit_mi(kodu: int, cikti: str) -> tuple[str | None, str]:
    """Claude koşusu neden bitti: (sınıf, neden). Sınıflar: "limit" (kullanım/oturum), "zaman_asimi" (sürücü
    durdurdu: değişiklikler stash'e, aşama KISMEN), "bos" (çıktı yok), "hata" (kısa hata çıktısı); (None, "") normal."""
    kisa = cikti.strip()
    if kodu == 124:
        return "zaman_asimi", "zaman aşımı (--zaman-asimi): Claude SIGINT ile durduruldu, yarım değişiklikler stash'te"
    if not kisa:
        return "bos", "claude boş çıktı verdi"
    m = LIMIT_KESIN.search(kisa)
    if m:
        satir = kisa[kisa.rfind("\n", 0, m.start()) + 1:].splitlines()[0]
        return "limit", satir.strip()[:160]
    # Limit metni başta ya da sonda olabilir; kısa çıktı (< 2500) + desen = limit.
    if len(kisa) < 2500 and (LIMIT_DESENI.search(kisa[:1500]) or LIMIT_DESENI.search(kisa[-1500:])):
        return "limit", kisa.splitlines()[0][:160]
    if kodu != 0 and len(kisa) < 400:
        return "hata", f"claude {kodu} ile çıktı: {kisa[:160]}"
    return None, ""


def sifirlanma_zamani(cikti: str, simdi: float | None = None) -> float | None:
    """Limit mesajındaki sıfırlanma saati (epoch): "resets at 5pm", "resets 3:30pm (Europe/Istanbul)", "reset in 2 hours",
    "resets Oct 3 at 9am". Bulunamazsa None. Saat geçmişteyse yarın sayılır."""
    simdi = time.time() if simdi is None else simdi
    m = re.search(r"reset\w*\s+in\s+(\d+)\s*(h|hour|m|min)", cikti, re.I)
    if m:
        return simdi + int(m.group(1)) * (3600 if m.group(2).lower().startswith("h") else 60)
    m = re.search(r"reset\w*\s*(?:at\s*)?(?:[A-Za-z]{3,9}\.?\s+\d{1,2},?\s*(?:at\s*)?)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
                  cikti, re.I)
    if not m:
        return None
    saat, dakika, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and saat < 12:
        saat += 12
    if ap == "am" and saat == 12:
        saat = 0
    if not (0 <= saat < 24 and 0 <= dakika < 60):
        return None
    t = time.localtime(simdi)
    hedef = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, saat, dakika, 0, 0, 0, -1))
    if hedef <= simdi:
        hedef += 86400
    return hedef


def sonuc_oku(cikti: str) -> dict:
    """Claude'un son mesajındaki SONUÇ/TEST/DEĞİŞEN/NOT satırlarını ayrıştırır (ONSOZ biçimi)."""
    r = {}
    for m in re.finditer(r"^\s*\**\s*(SONUÇ|SONUC|TEST|DEĞİŞEN|DEGISEN|NOT)\s*\**\s*:\s*\**\s*(.+?)\s*\**\s*$", cikti, re.M | re.I):
        anahtar = m.group(1).upper().replace("Ç", "C").replace("Ğ", "G").replace("İ", "I").replace("Ş", "S")
        r[anahtar] = m.group(2).strip()  # son geçen kazanır
    s = (r.get("SONUC") or "").upper()
    r["sonuc"] = "TAMAM" if "TAMAM" in s else "KISMEN" if "KISMEN" in s else "KALDI" if "KALDI" in s else None
    t = (r.get("TEST") or "").lower().strip()
    # İlk kelime karar verir: "kaldı (… 59/59 geçti …)" yine kaldıdır.
    r["test_kaldi"] = bool(re.match(r"\W*(kald[ıi]|k[ıi]rm[ıi]z[ıi]|fail|hata|ko[şs]ulmad[ıi])", t))
    return r


# Sürücünün kendi yazdığı dosyalar "Claude bir şey değiştirdi" sayılmaz.
SURUCU_DOSYALARI = (":!NOTLAR/KONTROL_LISTEN.md", ":!NOTLAR/otomatik", ":!.cafer", ":!otomatik.py")


def degisiklik_var(surucu_haric: bool = True) -> bool:
    if surucu_haric:
        _, c = git("status", "--porcelain", "--", ".", *SURUCU_DOSYALARI)
    else:
        _, c = git("status", "--porcelain")
    return bool(c.strip())


def son_commit_asamanin(kod: str) -> bool:
    """Son commit bu aşamaya ait mi ve sürücü dosyaları dışında bir şey içeriyor mu?"""
    _, mesaj = git("log", "-1", "--format=%s")
    if not re.match(rf"^{kod}\b", mesaj.strip()):
        return False
    _, dosyalar = git("show", "--stat", "--format=", "--name-only", "HEAD", "--", ".", *SURUCU_DOSYALARI)
    return bool(dosyalar.strip())


def deneme_kaydet(kod: str, ad: str, sure: float, sinif: str | None) -> None:
    """Her Claude koşusunun süresi (ilk deneme dahil) `otomatik.json → denemeler[kod]`'a; ETA ve rapor için."""
    d = json_oku(DURUM)
    d.setdefault("denemeler", {}).setdefault(kod, []).append(
        {"ad": ad, "sure": round(sure, 1), "sinif": sinif, "zaman": time.strftime("%Y-%m-%d %H:%M")})
    json_yaz(DURUM, d)


def asama_durdur(kod: str, neden: str, sinif: str, sure: float, cikti: str = "") -> bool:
    """Aşama durdu. `zaman_asimi`: yarım değişiklikler COMMIT edilmez, stash'e alınır, aşama KISMEN (yeniden koşunca
    `git stash pop`). `limit` (3b): commit YOK, yarım değişiklikler stash'e (aşama yeniden başlayınca kendiliğinden geri
    alınır), sıfırlanma saati loglanır. Diğer sınıflar (boş/hata): eskisi gibi yarım commit."""
    yaz(f"   ✖ {kod} DURDU ({sinif}): {neden}")
    hedef = None
    if sinif == "zaman_asimi":
        if degisiklik_var(surucu_haric=False):
            git("stash", "push", "-u", "-m", f"{kod}: zaman aşımı (otomatik) — KISMEN")
            yaz("   ⏸ yarım değişiklikler stash'e alındı: git stash list · git stash pop")
        ek_not(KONTROL_LISTEN, f"- [ ] **{kod} KISMEN (zaman aşımı):** {neden}. Değişiklikler `git stash list`'te; "
                               f"`git stash pop` sonra `python otomatik.py --asama {kod}` ya da süreyi artır.")
    elif sinif == "limit":
        if degisiklik_var(surucu_haric=False):
            git("stash", "push", "-u", "-m", f"{kod}: limit (otomatik)")
            yaz("   ⏸ yarım değişiklikler stash'e alındı; aşama yeniden başlayınca geri alınır")
        hedef = sifirlanma_zamani(cikti)
        saat = time.strftime("%Y-%m-%d %H:%M", time.localtime(hedef)) if hedef else "bilinmiyor"
        yaz(f"   ⏳ kullanım limiti; sıfırlanma: {saat}")
        ek_not(KONTROL_LISTEN, f"- [ ] **{kod} DURDU (limit):** {neden}. Sıfırlanma: {saat}. "
                               f"`python otomatik.py --bekle` o saati bekleyip aynı aşamayı yeniden başlatır.")
        ek_not(LOGLAR / "limit.log", f"{time.strftime('%Y-%m-%d %H:%M')} | {kod} | sıfırlanma {saat} | {neden}")
    else:
        if degisiklik_var(surucu_haric=False):
            git("add", "-A")
            git("commit", "-m", f"{kod}: yarım — {neden[:60]} (otomatik)")
        ek_not(KONTROL_LISTEN, f"- [ ] **{kod} DURDU ({sinif}):** {neden}. `python otomatik.py` kaldığı yerden sürer.")
    d2 = json_oku(DURUM)
    d2["basarisiz"] = kod
    d2["durma_nedeni"] = neden
    d2["durma_sinifi"] = sinif
    d2["durum"] = "KISMEN" if sinif in ("zaman_asimi", "limit") else "KALDI"
    d2["limit_sifirlanma"] = hedef
    d2.setdefault("sureler", {})  # ilk denemenin süresi kaybolmasın (tamamlanmayan aşama da ölçülür)
    d2.setdefault("yarim_sureler", {})[kod] = round(sure, 1)
    json_yaz(DURUM, d2)
    bildir(f"{kod} durdu", neden[:80])
    return False


def limit_stash_geri_al(kod: str) -> bool:
    """Limitte stash'e alınan yarım değişiklikleri aşama yeniden başlarken geri koyar."""
    _, liste = git("stash", "list")
    for satir in liste.splitlines():
        if f"{kod}: limit (otomatik)" in satir:
            k, _ = git("stash", "pop", satir.split(":", 1)[0])
            yaz("   ▶ limit öncesi yarım değişiklikler geri alındı" if k == 0 else "   ⚠ stash geri alınamadı; elle: git stash pop")
            return k == 0
    return False


def denetci_sonuc(cikti: str) -> tuple[str | None, str]:
    """Denetçi raporundaki `## Sonuç: GEÇTİ | ŞARTLI | KALDI` satırı → ("GECTI"|"SARTLI"|"KALDI"|None, satır)."""
    m = None
    for m in re.finditer(r"Sonu[çc]\s*:\s*\**\s*(GEÇTİ|GEÇTI|GECTI|ŞARTLI|SARTLI|KALDI)", cikti, re.I):
        pass
    if not m:
        return None, ""
    s = m.group(1).upper().replace("Ç", "C").replace("İ", "I").replace("Ş", "S")
    return s, m.group(0).strip()


ALT_OTURUM_DK = 20  # 3c: her alt başlık ayrı oturum, en çok bu kadar dakika (SIGINT → 30 sn → SIGTERM)
DENETCI_TUR = 3  # 3d: denetçi (haiku) + düzeltme (ana model) en çok bu kadar tur


def oturum(kod: str, prompt: str, args, ad: str, cb: "Cubuk | None", model: str, zaman_asimi_dk: int | None = None):
    """Bir Claude oturumu: koş, sınıflandır, süresini kaydet → (sınıf, neden, çıktı, SONUÇ sözlüğü)."""
    t0 = time.time()
    kodu, cikti = claude_kos(kod, prompt, args, ad=ad, cubuk_obj=cb, model=model, zaman_asimi_dk=zaman_asimi_dk)
    sinif, neden = limit_mi(kodu, cikti)
    deneme_kaydet(kod, ad, time.time() - t0, sinif)
    return sinif, neden, cikti, sonuc_oku(cikti)


def asama_kos(idx: int, args) -> bool:
    kod, baslik, kosular, elle = ASAMALAR[idx]
    d = json_oku(DURUM)
    yaz("━" * 70)
    yaz(f" AŞAMA {kod} — {baslik}   ({idx + 1}/{len(ASAMALAR)})")
    yaz("━" * 70)
    baslangic = time.time()
    model = model_sec(baslik, args.model)
    alt_dk = args.zaman_asimi or ALT_OTURUM_DK
    git("tag", "-f", f"{kod.lower()}-basi")  # denetçi diff'i bu noktadan
    limit_stash_geri_al(kod)
    yaz(f"   model: {model} · alt oturum en çok {alt_dk} dk")

    def durdur(neden: str, sinif: str = "limit", cikti: str = "") -> bool:
        return asama_durdur(kod, neden, sinif, time.time() - baslangic, cikti)

    def cb() -> Cubuk:
        return Cubuk(kod, idx + 1, len(ASAMALAR), d.get("baslangic", baslangic), d.get("sureler", {}))

    sonuc_sorunu: list[str] = []

    def beyan(so: dict, ad: str) -> None:
        """Claude'un kendi beyanı: KALDI ya da TEST kaldı → aşama bitmiş sayılmaz; SONUÇ satırı zorunlu."""
        if so["sonuc"] == "KALDI":
            sonuc_sorunu.append(f"Claude {ad} sonunda 'SONUÇ: KALDI' dedi. NOT: {so.get('NOT', '')[:200]}")
        elif so["test_kaldi"]:
            sonuc_sorunu.append(f"Claude {ad} sonunda 'TEST: {so.get('TEST', '')[:120]}' dedi.")
        elif so["sonuc"] == "KISMEN":
            ek_not(KONTROL_LISTEN, f"- [ ] {kod} {ad}: Claude 'KISMEN' dedi — NOT: {so.get('NOT', '')[:200]}")
        elif so["sonuc"] is None:
            sonuc_sorunu.append(f"{ad}: son mesajda SONUÇ satırı yok (ONSOZ biçimi zorunlu: SONUÇ/DEĞİŞEN/TEST/NOT).")
            yaz(f"   ⚠ {ad}: SONUÇ satırı yok (düzeltme turunda istenecek)")

    n = 0
    for uret in kosular:
        k = uret()
        k = ("metin", k) if isinstance(k, str) else k
        if k[0] == "asama":
            ek = k[2]
            bolumler = [(b, a) for b, a in alt_basliklar(kod) if a > 0]
            if not bolumler:  # alt başlık yok (ya da hepsi kapalı): aşama tek oturumda
                n += 1
                yaz(f"▸ koşu {n}: {kod} (tek oturum)")
                sinif, neden, cikti, so = oturum(kod, onsoz() + "\n" + komut_metni("asama", f"{kod} onaysız {ek}".strip()),
                                                 args, f"kosu{n}", cb(), model)
                if sinif:
                    return durdur(neden, sinif, cikti)
                beyan(so, f"koşu {n}")
                continue
            for b, acik in bolumler:  # 3c: her alt başlık ayrı oturum
                n += 1
                yaz(f"▸ koşu {n}: «{b}» ({acik} açık madde, en çok {alt_dk} dk)")
                ek2 = (f"Bu oturumda YALNIZCA «{b}» bölümü ({acik} açık madde); diğer bölümlere dokunma, bitirdiğin "
                       f"maddeleri [x] yap. {ek}").strip()
                sinif, neden, cikti, so = oturum(kod, onsoz() + "\n" + komut_metni("asama", f"{kod} onaysız {ek2}"),
                                                 args, f"kosu{n}", cb(), model, alt_dk)
                if sinif == "zaman_asimi":  # alt oturum: durma, not düş, sıradaki bölüme geç
                    yaz(f"   ⏱ «{b}» {alt_dk} dk'da durduruldu (SIGINT); kalanı düzeltme turuna")
                    ek_not(KONTROL_LISTEN, f"- [ ] {kod} «{b}»: {alt_dk} dk zaman aşımı (SIGINT ile durduruldu); "
                                           "kalan maddeler düzeltme turunda.")
                    continue
                if sinif:
                    return durdur(neden, sinif, cikti)
                beyan(so, f"koşu {n} «{b}»")
        elif k[0] == "denetci":  # 3d: haiku denetçi, ana oturuma yalnızca SONUÇ satırı + rapor yolu
            odak = k[2]
            satir = ""
            for tur in range(1, DENETCI_TUR + 1):
                n += 1
                yaz(f"▸ koşu {n}: denetçi turu {tur}/{DENETCI_TUR} (haiku)")
                sinif, neden, cikti, _ = oturum(kod, p_denetci_metni(kod, odak), args, f"denetci{tur}", cb(), "haiku", alt_dk)
                if sinif:
                    return durdur(neden, sinif, cikti)
                karar, satir = denetci_sonuc(cikti)
                if karar == "GECTI":
                    yaz("   ✔ denetçi: GEÇTİ")
                    break
                satir = satir or "Sonuç satırı yok (denetçi raporu biçimsiz)"
                yaz(f"   ✖ denetçi: {satir}")
                rapor = SON_LOG.relative_to(KOK) if SON_LOG else "NOTLAR/otomatik/"
                n += 1
                duzelt = (onsoz() + f"\n{kod} denetçi turu {tur}/{DENETCI_TUR} — denetçinin SONUÇ satırı: «{satir}». "
                          f"Tam rapor: {rapor} (yalnızca 'Engelleyici' bölümünü oku). Engelleyicileri düzelt (kök neden, semptom "
                          "değil), her düzeltmeye test ekle, testleri koş; uyarıları yalnızca ucuzsa düzelt.")
                sinif, neden, cikti, so = oturum(kod, duzelt, args, f"denetci{tur}-duzeltme", cb(), model, alt_dk)
                if sinif:
                    return durdur(neden, sinif, cikti)
                beyan(so, f"denetçi düzeltmesi {tur}")
            else:
                sonuc_sorunu.append(f"Denetçi {DENETCI_TUR} turda GEÇTİ demedi: {satir}")
        else:  # düz metin istem (profil, model araştırması, sunucu…)
            n += 1
            yaz(f"▸ koşu {n}")
            sinif, neden, cikti, so = oturum(kod, onsoz() + "\n" + k[1], args, f"kosu{n}", cb(), model)
            if sinif:
                return durdur(neden, sinif, cikti)
            beyan(so, f"koşu {n}")

    for deneme in range(1, args.deneme + 1):
        sorun = kontrol(kod) + sonuc_sorunu
        sonuc_sorunu = []  # yalnızca ilk kontrol turunda geçerli; düzeltme koşusu kendi SONUÇ'unu verir
        acik = acik_kutular(kod)
        if acik is None:  # YAPILACAKLAR'da bölüm yok: "0 açık madde" diye geçilmez
            sorun.append(f"YAPILACAKLAR.md'de `## Aşama {kod}` bölümü yok; önce planı yaz (maddeler + Bitti sayılır).")
            acik = 0
        if not sorun and acik == 0:
            break
        if not sorun and deneme == args.deneme:
            if not degisiklik_var() and not (KOK / "NOTLAR").exists():
                return durdur(f"{acik} madde açık ve hiçbir dosya değişmedi")
            yaz(f"   ⚠ {kod}: {acik} madde açık kaldı — NOTLAR/'daki aşama notuna bak.")
            ek_not(KONTROL_LISTEN, f"- [ ] {kod}: {acik} madde açık kaldı; NOTLAR/ altındaki {kod} notunu oku, gerekirse `/asama {kod}` ile bitirt.")
            break
        yaz(f"   ✖ kontrol ({deneme}/{args.deneme}): " + ("; ".join(s.splitlines()[0] for s in sorun) or f"{acik} açık madde"))
        if deneme == args.deneme:
            git("add", "-A")
            git("commit", "-m", f"{kod}: KALDI — kontrol kırmızı (otomatik)")
            ek_not(KONTROL_LISTEN, f"- [ ] **{kod} KALDI.** Sorun: {(sorun or ['açık maddeler'])[0].splitlines()[0]}. `/asama {kod}` ile devam et ya da `/hata-analiz son`.")
            d["basarisiz"] = kod
            json_yaz(DURUM, d)
            bildir(f"{kod} KALDI", "sürücü durdu — terminale bak")
            return False
        duzelt = onsoz() + f"\n{kod} aşaması bitti sayılmıyor. Sürücü kontrolü şunları buldu:\n\n" + "\n\n".join(sorun or []) \
            + (f"\n\nYAPILACAKLAR.md'de {kod} altında {acik} madde hâlâ [ ]." if acik else "") \
            + "\n\nÖnce bunları düzelt (kök neden, semptom değil), sonra aşamanın kalan maddelerini bitir, /kontrol'ün yaptığı kontrolleri koş, NOTLAR'ı güncelle."
        sinif, neden, cikti, so = oturum(kod, duzelt, args, f"duzeltme{deneme}", cb(), model)
        if sinif:
            return durdur(neden, sinif, cikti)
        if so["sonuc"] == "KALDI" or so["test_kaldi"]:
            sonuc_sorunu.append(f"Düzeltme {deneme} sonunda Claude '{so.get('SONUC', '')} / TEST: {so.get('TEST', '')}' dedi.")
        elif so["sonuc"] is None:
            sonuc_sorunu.append(f"Düzeltme {deneme}: son mesajda SONUÇ satırı yok (zorunlu).")

    # Sürücünün kendi yazdıkları (KONTROL_LISTEN, loglar) sayılmaz: Claude gerçekten kod/not değiştirmiş olmalı.
    if not degisiklik_var() and not son_commit_asamanin(kod):
        return durdur("Claude hiçbir dosyayı değiştirmedi (limit ya da oturum sorunu olabilir; NOTLAR/otomatik/ logunu oku)")

    git("add", "-A")
    git("commit", "-m", f"{kod}: {baslik} (otomatik)")
    git("tag", "-f", f"{kod.lower()}-bitti")
    sure = time.time() - baslangic
    d = json_oku(DURUM)
    d.setdefault("tamamlanan", [])
    if kod not in d["tamamlanan"]:
        d["tamamlanan"].append(kod)
    d.setdefault("sureler", {})[kod] = sure
    for anahtar in ("basarisiz", "durma_nedeni", "durma_sinifi", "limit_sifirlanma"):
        d.pop(anahtar, None)
    json_yaz(DURUM, d)
    if elle:
        ek_not(KONTROL_LISTEN, f"\n## {kod} — {baslik} ({time.strftime('%Y-%m-%d %H:%M')})")
        for e in elle:
            ek_not(KONTROL_LISTEN, f"- [ ] {e}")
    yaz(f"✔ {kod} bitti ({sure_metni(sure)}) — commit + etiket {kod.lower()}-bitti\n")
    bildir(f"{kod} bitti", f"{baslik} · {sure_metni(sure)}")
    return True


def limit_bekle(hedef: float | None, varsayilan_dk: int = 60, pay_sn: int = 120) -> None:
    """3b `--bekle`: sıfırlanma saatine (+pay) kadar uyu; saat bilinmiyorsa `varsayilan_dk` bekle."""
    simdi = time.time()
    hedef = (hedef + pay_sn) if hedef and hedef > simdi else simdi + varsayilan_dk * 60
    yaz(f"⏳ kullanım limiti: {time.strftime('%H:%M', time.localtime(hedef))}'e kadar bekleniyor (Ctrl+C ile çık)")
    while (kalan := hedef - time.time()) > 0:
        if sys.stdout.isatty():
            sys.stdout.write(f"\r   kalan {sure_metni(kalan)}   ")
            sys.stdout.flush()
        time.sleep(min(60, kalan))
    yaz("\n▶ süre doldu; aynı aşama yeniden başlıyor")


def ozet_yaz():
    d = json_oku(DURUM)
    yaz("━" * 70)
    yaz(" ÖZET")
    yaz("━" * 70)
    for kod, baslik, _, _ in ASAMALAR:
        if kod in d.get("tamamlanan", []):
            isaret = "✔"
        elif d.get("basarisiz") == kod:
            isaret = "✖"
        else:
            isaret = "·"
        s = d.get("sureler", {}).get(kod)
        yaz(f" {isaret} {kod:<4} {baslik:<38} {sure_metni(s) if s else ''}")
    if KONTROL_LISTEN.exists():
        yaz(f"\n Elle bakacakların: {KONTROL_LISTEN.relative_to(KOK)}")
    if SORULAR.exists():
        yaz(f" Claude'un sana soruları: {SORULAR.relative_to(KOK)}")
    yaz(f" Loglar: {LOGLAR.relative_to(KOK)}/")


def main():
    ap = argparse.ArgumentParser(description="YENİ NESİL CAFER — K serisi otomatik sürücü")
    ap.add_argument("--asama", help="sadece bu aşamayı koş (örn. K3)")
    ap.add_argument("--baslangic", help="bu aşamadan itibaren koş (örn. K4)")
    ap.add_argument("--dur", action="store_true", help="her aşamadan sonra Enter bekle")
    ap.add_argument("--sadece-kur", action="store_true", help="sadece paketi kur")
    ap.add_argument("--deneme", type=int, default=2, help="başarısız aşamayı kaç kez tekrar dene (varsayılan 2)")
    ap.add_argument("--zaman-asimi", type=int, default=0, help="tek Claude koşusu için dakika (0 = sınırsız)")
    ap.add_argument("--tam-yetki", action="store_true", help="Claude Code'u izin sormadan çalıştır (--dangerously-skip-permissions)")
    ap.add_argument("--python", default="", help="testler ve import dumanı için Python (varsayılan: .venv/bin/python varsa o, yoksa bu yorumlayıcı)")
    ap.add_argument("--bekle", action="store_true", help="kullanım limitinde sıfırlanma saatine kadar uyu ve aynı aşamayı yeniden başlat")
    ap.add_argument("--model", default="", help="Claude modeli (varsayılan sonnet; adında 'mimari' geçen aşama opus; denetçi hep haiku)")
    args = ap.parse_args()
    global PY
    PY = python_sec(args.python)
    yaz(f"Testler için Python: {PY}")

    if args.tam_yetki:
        yaz("⚠ --tam-yetki: Claude Code hiçbir komut için izin sormayacak. Sadece kendi bilgisayarında, yedeği olan repoda kullan.")
        time.sleep(2)

    kurulum(args)
    if args.sadece_kur:
        return

    d = json_oku(DURUM)
    if args.asama:
        secilen = [KODLAR.index(args.asama.upper())]
    else:
        bas = KODLAR.index(args.baslangic.upper()) if args.baslangic else 0
        if args.baslangic:
            # bu aşamadan itibaren "tamamlandı" işaretlerini kaldır (yanlışlıkla bitti sayılanlar için)
            d["tamamlanan"] = [k for k in d.get("tamamlanan", []) if KODLAR.index(k) < bas]
            # süreleri de temizle; yoksa 6 saniyelik sahte koşular ETA ortalamasını bozuyor
            d["sureler"] = {k: v for k, v in d.get("sureler", {}).items() if k in KODLAR and KODLAR.index(k) < bas}
            d.pop("basarisiz", None)
            json_yaz(DURUM, d)
        secilen = [i for i in range(bas, len(KODLAR)) if KODLAR[i] not in d.get("tamamlanan", [])]
        if not secilen:
            yaz("Tüm aşamalar tamamlanmış görünüyor. Belirli birini tekrar için: --asama K<n>")
            ozet_yaz()
            return

    yaz(f"Sıra: {', '.join(KODLAR[i] for i in secilen)}\n")
    try:
        for i in secilen:
            while True:
                if asama_kos(i, args):
                    break
                d = json_oku(DURUM)
                if args.bekle and d.get("durma_sinifi") == "limit":  # 3b: bekle, aynı aşamayı yeniden başlat
                    limit_bekle(d.get("limit_sifirlanma"))
                    continue
                raise StopIteration
            if args.dur and i != secilen[-1]:
                cevap = input("Devam için Enter, çıkmak için q: ").strip().lower()
                if cevap == "q":
                    break
    except StopIteration:
        pass
    except KeyboardInterrupt:
        yaz("\n⏸ durduruldu; tekrar `python otomatik.py` ile kaldığın aşamadan sürer.")
    ozet_yaz()
    bildir("Sürücü durdu", "özet terminalde")


if __name__ == "__main__":
    main()
