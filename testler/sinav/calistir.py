"""Sınav seti: programa gerçek görevleri yaptırır, sonucu KODLA denetler, `sonuclar/` ve `RAPOR.md` yazar.

YAPILACAKLAR Aşama 1. Programın kodunda sınava özel dal yok: program `arayuz_denetimi.py` gibi ekransız açılır, her görev
gerçek gönderme yolundan (`MainWindow._send_or_stop`) gider; araç çağrıları, plan ve cevap arayüzün kendi sinyallerinden
toplanır, denetimler `denetim.py`'de.

    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 testler/sinav/calistir.py [--hizli | --hepsi | --etiket ad]
        [--tekrar N] [--model <ollama adı | sağlayıcı:model>] [--yonetici <politika>] [--gorev ad1,ad2]
    --hizli (varsayılan): internet/gpu/motor/uzun etiketliler hariç, hedef ≤ 10 dk · --tekrar: her görev N kez (her
    tekrar ayrı süreçte, hafıza boş başlar) · --gorev: yalnızca bu görevler (geliştirirken).
    Çıkış kodu: 0 = eşiği geçti ya da bu kapsam için eşik yok (esik.json) · 1 = eşiğin altında · 2 = çalıştırıcı hatası.

Ortam: ayar, veri, çalışma klasörü ve masaüstü geçici klasörde (sınav çıktısı gerçek masaüstündeki Sonuçlar'a
düşmez); ayarlar ve model kartları KOPYA, hafıza/sohbet/beceri boş. Python kütüphaneleri ve 3D figür motoru gerçek
kurulumdan bağlanır (CLAUDE.md: kütüphane yolu hep gerçek kurulumdan). Bulut bağlantıları ve CLI ajanları (Claude Code…)
kapalı: kullanıcının kotası harcanmaz; `--model` ile açıkça istenirse açılır.
Onaylar (güvenlik ajanının ve kullanıcının yerine, talimattaki kural): okur/yazar/calistirir iş klasörü içindeyse evet;
silme, kurma ve internete gönderme hayır (görev internet etiketliyse internete gönderme evet); araç fabrikasının
"araç ekle" sorusu evet. Böylece gerçek güvenlik ajanı sınavın ölçtüğü şeyin dışında kalır.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

SINAV = Path(__file__).resolve().parent
KOK = SINAV.parent.parent
sys.path.insert(0, str(KOK))  # programın kaynağı (kurulu kopya değil)
sys.path.insert(0, str(SINAV))
import denetim  # noqa: E402

SONUCLAR = SINAV / "sonuclar"
RAPOR = SINAV / "RAPOR.md"
ESIK = SINAV / "esik.json"
GERCEK_AYAR = Path.home() / ".config/yeni-nesil-cafer"
GERCEK_VERI = Path.home() / ".local/share/yeni-nesil-cafer"
KURULU_KUTUPHANE = Path.home() / ".local/share/yeni-nesil-cafer-app/ajan-kutuphaneleri"
BAGLANACAK = ("python-kutuphaneleri", "figur-motoru")  # büyük, yalnızca okunan klasörler: gerçek kurulumdan
KOPYALANACAK = ("model-kartlari.json", "model_katalogu.json")  # model seçimi bunlarla (sınavlar, katalog)
DURDURMA_SN = 120  # zaman aşımında ■ durdurduktan sonra işin kapanması için süre


def secenekler(argv=None):
    p = argparse.ArgumentParser(description="YENİ NESİL CAFER sınav seti")
    p.add_argument("--model", default="", help="Ollama modeli ya da sağlayıcı:model (boş: programın kendi seçimi)")
    p.add_argument("--yonetici", default="", choices=("", "otomatik", "yerel", "bulut"),
                   help="yönetici politikası (K3; boş: ayardaki, varsayılan otomatik)")
    p.add_argument("--etiket", default="", help="yalnızca bu etiketli görevler")
    p.add_argument("--hizli", action="store_true", help="internet/gpu/motor/uzun hariç (varsayılan)")
    p.add_argument("--hepsi", action="store_true", help="bütün görevler")
    p.add_argument("--tekrar", type=int, default=1, help="her görev kaç kez")
    p.add_argument("--gorev", default="", help="yalnızca bu görevler (virgülle)")
    p.add_argument("--motor", action="store_true", help="görev motoru bayrağı AÇIK (extra.gorev_motoru; Manager ile karşılaştırma)")
    p.add_argument("--motorsuz", action="store_true", help="görev motoru bayrağı KAPALI (Manager yolu)")
    p.add_argument("--kademe", default="", choices=("", "dusuk", "orta", "yuksek"),
                   help="K7: program bu kademeye kilitli koşar, yalnızca o kademede beklenen görevler; sonuç yönlendirmeye geri beslenir")
    p.add_argument("--cocuk", type=int, default=0, help=argparse.SUPPRESS)  # bir tekrarı yürüten alt süreç
    p.add_argument("--kosu", default="", help=argparse.SUPPRESS)
    p.add_argument("--cikti", default="", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def kapsam(a) -> str:
    if a.gorev:
        return "gorev:" + a.gorev
    if a.etiket:
        return "etiket:" + a.etiket
    on = f"kademe:{a.kademe}+" if getattr(a, "kademe", "") else ""
    motor = "+motor" if getattr(a, "motor", False) else "+manager" if getattr(a, "motorsuz", False) else ""
    return on + ("hepsi" if a.hepsi else "hizli") + motor


def secilenler(a) -> list[dict]:
    gorevler = denetim.yukle()
    if getattr(a, "kademe", ""):
        gorevler = [g for g in gorevler if denetim.kademede(g, a.kademe)]
    if a.gorev:
        adlar = [x.strip() for x in a.gorev.split(",") if x.strip()]
        bilinmeyen = set(adlar) - {g["ad"] for g in gorevler}
        if bilinmeyen:
            raise SystemExit("bilinmeyen görev: " + ", ".join(sorted(bilinmeyen)))
        return [g for g in gorevler if g["ad"] in adlar]
    if a.etiket:
        return [g for g in gorevler if a.etiket in denetim.etiketler(g)]
    return gorevler if a.hepsi else [g for g in gorevler if denetim.hizli_mi(g)]


def model_etiketi(a) -> str:
    return a.model or "otomatik"


# ---------------------------------------------------------------- ana süreç: tekrarları yürütür, raporu yazar
def ana(a) -> int:
    gorevler = secilenler(a)
    if not gorevler:
        print("seçilen görev yok")
        return 2
    SONUCLAR.mkdir(exist_ok=True)
    kosu = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    cikti = SONUCLAR / f"{kosu}-{re.sub(r'[^\w.-]+', '-', model_etiketi(a))}.jsonl"
    sinir = sum(g["zaman_siniri_sn"] for g in gorevler)
    print(f"Sınav: {len(gorevler)} görev × {a.tekrar} tekrar · kapsam {kapsam(a)} · model {model_etiketi(a)} · "
          f"görev zaman sınırlarının toplamı {sinir // 60} dk {sinir % 60} sn", flush=True)
    hata = False
    for tekrar in range(1, a.tekrar + 1):
        argv = sys.argv[1:]
        kod = subprocess.call([sys.executable, str(Path(__file__).resolve()), *argv, "--cocuk", str(tekrar),
                               "--kosu", kosu, "--cikti", str(cikti)])
        if kod != 0:
            print(f"tekrar {tekrar}: çalıştırıcı hatası (çıkış {kod})", flush=True)
            hata = True
            break
    satirlar = oku(cikti)
    rapor_yaz()
    if not satirlar:
        print("sonuç yok")
        return 2
    geri_besle(satirlar, a)
    gecen, toplam = sum(s["gecti"] for s in satirlar), len(satirlar)
    oran = gecen / toplam
    dakika = sum(s["sure"] for s in satirlar) / 60
    print(f"\nSONUÇ: {gecen}/{toplam} geçti (%{100 * oran:.0f}) · {dakika:.1f} dk · {cikti.name} · RAPOR.md güncellendi",
          flush=True)
    if hata:
        return 2
    esik = json.loads(ESIK.read_text(encoding="utf-8")).get(kapsam(a)) if ESIK.is_file() else None
    if esik is not None and oran < esik:
        print(f"EŞİĞİN ALTINDA: %{100 * oran:.0f} < %{100 * esik:.0f} ({ESIK.name})", flush=True)
        return 1
    return 0


def geri_besle(satirlar: list[dict], a) -> dict:
    """K7: kademe × görev türü başarısı yönlendirme tablosuna (gerçek DATA_DIR/olcum.json; `--kademe` verilmediyse
    programın etkin kademesi). Yönlendirici (`yonlendirici.sec`) %50 altındaki türlerde hızlı rol yerine yönetici seçer."""
    try:
        from asistan.cekirdek import profil
        from asistan.cekirdek.analiz import olcum

        kademe_ = getattr(a, "kademe", "") or profil.kademe()
        tablo = olcum.sinav_geri_besle(satirlar, kademe_)
        if tablo:
            print("Yönlendirmeye geri beslendi (" + kademe_ + "): " + ", ".join(
                f"{t} {v['gecen']}/{v['toplam']}" for t, v in sorted(tablo.items())), flush=True)
        return tablo
    except Exception as e:  # geri besleme sınavı düşürmez
        print(f"geri besleme yapılamadı: {e}", flush=True)
        return {}


def oku(dosya: Path) -> list[dict]:
    if not dosya.is_file():
        return []
    return [json.loads(s) for s in dosya.read_text(encoding="utf-8").splitlines() if s.strip()]


def rapor_yaz() -> None:
    """RAPOR.md: her yapılandırmanın (model · yönetici · kapsam) son koşusu; özet, görev × yapılandırma, düşenler."""
    kosular: dict[str, list[dict]] = {}
    for dosya in sorted(SONUCLAR.glob("*.jsonl")):
        for s in oku(dosya):
            kosular.setdefault(s["kosu"], []).append(s)
    son: dict[tuple, tuple[str, list[dict]]] = {}
    for kid, ss in kosular.items():
        if ss[0]["kapsam"].startswith("gorev:"):  # geliştirirken tek görev denemesi: rapora girmez
            continue
        anahtar = (ss[0]["model"], ss[0]["yonetici"], ss[0]["kapsam"])
        if anahtar not in son or kid > son[anahtar][0]:
            son[anahtar] = (kid, ss)
    sutunlar = sorted(son.values(), key=lambda x: x[0], reverse=True)
    y = ["# Sınav raporu", "",
         "`testler/sinav/calistir.py` üretir, elle düzenleme. Görevler `testler/sinav/gorevler/`, ayrıntılı kayıtlar "
         "`testler/sinav/sonuclar/` (git'te değil). Her yapılandırmanın (model · yönetici · kapsam) yalnızca son koşusu "
         "gösterilir; tekrarlı koşuda hücre \"geçen/tekrar · ortalama süre\".", "",
         "## Özet", "", "| Model | Yönetici | Kapsam | Tarih | Sürüm | Geçen | % | Süre |", "|---|---|---|---|---|---|---|---|"]
    for kid, ss in sutunlar:
        s0, gecen = ss[0], sum(s["gecti"] for s in ss)
        tekrar = max(s["tekrar"] for s in ss)
        y.append(f"| {s0['model']} | {s0['yonetici']} | {s0['kapsam']}{f' ×{tekrar}' if tekrar > 1 else ''} | "
                 f"{s0['tarih'][:16].replace('T', ' ')} | {s0.get('surum', '')} {s0.get('commit', '')} | "
                 f"{gecen}/{len(ss)} | {100 * gecen / len(ss):.0f} | {sum(s['sure'] for s in ss) / 60:.1f} dk |")
    y += ["", "## Görevler", "",
          "| Görev | " + " | ".join(f"{ss[0]['model']} · {ss[0]['yonetici']} · {ss[0]['kapsam']}" for _, ss in sutunlar)
          + " |", "|---|" + "---|" * len(sutunlar)]
    for g in denetim.yukle():
        hucreler = []
        for _, ss in sutunlar:
            gs = [s for s in ss if s["gorev"] == g["ad"]]
            if not gs:
                hucreler.append("—")
                continue
            gecen, ort = sum(s["gecti"] for s in gs), statistics.mean(s["sure"] for s in gs)
            hucreler.append(f"{gecen}/{len(gs)} · {ort:.0f} sn" if len(gs) > 1 else
                            f"{'✓' if gecen else '✗'} {ort:.0f} sn")
        etiket = f" [{', '.join(sorted(denetim.etiketler(g)))}]" if denetim.etiketler(g) else ""
        y.append(f"| {g['sira']}. {g['ad']}{etiket} · {denetim.kademe(g)}/{denetim.tur(g)} | " + " | ".join(hucreler) + " |")
    if sutunlar:  # K7: son koşunun kademe × görev türü tablosu (yönlendirmeye geri beslenen özet)
        kid, ss = max(sutunlar, key=lambda x: x[0])
        gorev_bilgi = {g["ad"]: (denetim.kademe(g), denetim.tur(g)) for g in denetim.yukle()}
        kt: dict[tuple, list[int]] = {}
        for s in ss:
            k, t = gorev_bilgi.get(s["gorev"], ("orta", "cok_adimli"))
            kt.setdefault((k, t), []).append(int(s["gecti"]))
        y += ["", f"## Son koşu ({kid}) — kademe × görev türü", "", "| Görev kademesi | Tür | Geçen | % |", "|---|---|---|---|"]
        for (k, t), v in sorted(kt.items()):
            y.append(f"| {k} | {t} | {sum(v)}/{len(v)} | {100 * sum(v) / len(v):.0f} |")
        gecen = sum(s["gecti"] for s in ss)
        y += ["", f"## Son koşu ({kid}) — düşen denetimler", ""]
        for s in ss:
            if not s["gecti"]:
                y.append(f"- **{s['gorev']}** (tekrar {s['tekrar']}, {s['sure']:.0f} sn): "
                         + "; ".join(s["dusen"][:3]).replace("|", "/"))
        y += ["", f"**Özet: {gecen}/{len(ss)} geçti (%{100 * gecen / len(ss):.0f}).**", ""]
    RAPOR.write_text("\n".join(y), encoding="utf-8")


# ---------------------------------------------------------------- alt süreç: bir tekrar
class Kayit:
    """O anki görevde arayüzden toplananlar."""

    def __init__(self):
        self.sifirla()

    def sifirla(self):
        self.araclar: list[dict] = []
        self.planlar: list[list[dict]] = []
        self.adimlar: dict[int, str] = {}
        self.notlar: list[str] = []
        self.hatalar: list[str] = []
        self.onaylar: list[str] = []
        self.olaylar: list[str] = []
        self.etiketler: set = set()


K = Kayit()

SILME = re.compile(r"(?<![\w-])(rm|rmdir|del|erase|rd|unlink|shred)\s|os\.(remove|unlink|rmdir|removedirs)\s*\(|"
                   r"shutil\.rmtree|send2trash|\.unlink\s*\(|\.rmdir\s*\(|Remove-Item", re.I)
KURMA = re.compile(r"\b(pip3?|uv|conda|mamba|apt(-get)?|pacman|dnf|yum|zypper|brew|winget|choco|scoop|npm|pnpm|yarn|"
                   r"snap|flatpak)\b[^\n]*\b(install|add)\b|\bpacman\s+-S", re.I)
GONDERME = re.compile(r"requests\.(post|put|patch|delete)\s*\(|urlopen\([^)]*data=|curl\s[^\n]*(\s-d\b|--data|"
                      r"-X\s*(POST|PUT|PATCH|DELETE)|\s-F\b)|wget\s[^\n]*--post|smtplib|\.sendmail\s*\(", re.I)
MUTLAK = re.compile(r"(?<![\w.~/])(?:~/|/(?:home|root|etc|usr|var|opt|mnt|media|srv|tmp|boot|dev|proc|sys|run)/)"
                    r"[^\s'\"`),;]*")
ZARARSIZ = ("/dev/null", "/usr/bin/env", "/bin/sh", "/bin/bash", "/usr/bin/python")


def disari(metin: str, is_klasoru: Path) -> str:
    """Kod/komut iş klasörünün dışına uzanıyor mu? Uzanıyorsa nedeni."""
    if re.search(r"(^|[\s'\"(=])\.\.([/\\]|['\"\s)]|$)", metin):
        return "üst klasöre (..) uzanıyor"
    kok = is_klasoru.resolve()
    for m in MUTLAK.finditer(metin):
        yol = m.group(0)
        if yol.startswith(ZARARSIZ):
            continue
        try:
            Path(os.path.expanduser(yol)).resolve().relative_to(kok)
        except ValueError:
            return f"iş klasörünün dışı: {yol[:80]}"
    return ""


def kural(ad: str, args: dict, is_klasoru: Path, etiketler: set) -> tuple[bool, str]:
    """Talimattaki onay kuralı: (evet mi, neden)."""
    from asistan.registry import REGISTRY

    arac = REGISTRY.get(ad)
    risk = arac.risk if arac else ""
    internet = "internet" in etiketler
    if ad == "add_tool":
        return True, "fabrika aracı (sandbox'ta denendi)"
    if ad == "install_python_package" or risk == "kurar":
        return False, "kurma (sınav kuralı)"
    if ad.startswith("browser_"):
        amac = str(args.get("purpose") or "")
        if internet and "mesaj / paylaşım" in amac:
            return True, "internet görevi: forma gönderme"
        return False, "tarayıcı: " + amac[:100]
    if ad == "call_api":
        if str(args.get("method") or "GET").upper() == "GET":
            return True, "okuma"
        return internet, "internete gönderme" + ("" if internet else " (sınav kuralı)")
    if risk in ("okur", "danisir", "ekip"):
        return True, risk
    if risk == "yazar":
        for k, v in args.items():
            if k in ("path", "out", "output", "file", "filename", "dest", "target") and isinstance(v, str) and v:
                p = Path(v).expanduser()
                try:
                    (p if p.is_absolute() else is_klasoru / p).resolve().relative_to(is_klasoru.resolve())
                except ValueError:
                    return False, f"iş klasörünün dışına yazma: {v[:80]}"
        return True, "iş klasöründe yazma"
    if risk == "calistirir":
        metin = str(args.get("command") or args.get("code") or json.dumps(args, ensure_ascii=False))
        if SILME.search(metin):
            return False, "silme (sınav kuralı)"
        if KURMA.search(metin):
            return False, "kurma (sınav kuralı)"
        if GONDERME.search(metin) and not internet:
            return False, "internete gönderme (sınav kuralı)"
        neden = disari(metin, is_klasoru)
        return (False, neden) if neden else (True, "iş klasöründe çalıştırma")
    return False, f"bilinmeyen araç: {ad}"


def ortam_hazirla(g: Path, a) -> dict:
    """Geçici ayar/veri/çalışma/masaüstü; os.environ'u değiştirir (asistan içe aktarılmadan ÖNCE çağrılmalı)."""
    ayar, veri, masa, calisma = g / "ayar", g / "veri", g / "Masaüstü", g / "calisma"
    for p in (ayar, veri / "yeni-nesil-cafer", masa, calisma):
        p.mkdir(parents=True)
    os.environ.update(XDG_CONFIG_HOME=str(ayar), XDG_DATA_HOME=str(veri), QT_QPA_PLATFORM="offscreen")
    if getattr(a, "kademe", ""):  # K7: program bu kademeye kilitli koşar (cekirdek/profil.kilit → ayar.toml/ortam)
        os.environ["CAFER_GENEL_KADEME_KILIDI"] = a.kademe
    (ayar / "user-dirs.dirs").write_text(f'XDG_DESKTOP_DIR="{masa}"\n', encoding="utf-8")  # results.desktop()
    bulut = bool(a.model) and ":" in a.model and not a.model.startswith("cli:")
    shutil.copytree(GERCEK_AYAR, ayar / "yeni-nesil-cafer",
                    ignore=None if bulut else shutil.ignore_patterns("baglantilar.json"))
    dosya = ayar / "yeni-nesil-cafer/ayarlar.json"
    s = json.loads(dosya.read_text(encoding="utf-8")) if dosya.is_file() else {}
    import asistan

    s["workspace"] = str(calisma)
    s.setdefault("extra", {})["tanitim_surumu"] = asistan.__version__  # tanıtım penceresi açılmasın
    s["extra"]["kurulum"] = True
    if a.yonetici:
        s["extra"]["yonetici_politikasi"] = a.yonetici  # K3: otomatik | yerel | bulut (cekirdek/yonlendirici.py)
    if getattr(a, "motor", False) or getattr(a, "motorsuz", False):  # K4/BÖLÜM 7: motor ↔ Manager karşılaştırması
        s["extra"]["gorev_motoru"] = bool(a.motor)
    if a.model and ":" not in a.model:
        s.update(auto_model=False, provider="ollama", ollama_model=a.model)
    elif not a.model:
        s["model_policy"] = "yerel"
    dosya.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    for ad in KOPYALANACAK:
        if (GERCEK_VERI / ad).is_file():
            shutil.copy2(GERCEK_VERI / ad, veri / "yeni-nesil-cafer" / ad)
    for ad in BAGLANACAK:
        if (GERCEK_VERI / ad).is_dir():
            (veri / "yeni-nesil-cafer" / ad).symlink_to(GERCEK_VERI / ad, target_is_directory=True)
    return {"calisma": calisma, "masa": masa, "veri": veri / "yeni-nesil-cafer"}


def bos_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cocuk(a) -> int:
    g = Path(tempfile.mkdtemp(prefix="ync-sinav-"))
    yollar = ortam_hazirla(g, a)
    os.environ["SINAV_VERI"] = str(yollar["veri"])  # python_denetim betikleri (ör. fabrika aracı) için

    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

    app = QApplication([])
    from asistan import __version__, cli_agents, gpu, libraries, results, security, tools
    from asistan.gui.theme import apply_theme

    apply_theme(app)
    def olay(metin):  # K.sifirla() listeyi yeniler: her seferinde o anki listeye
        K.olaylar.append(metin)

    # açılan pencere ve sorular iş akışını durdurmasın: kaydedilir, hep "hayır"
    def sahte_exec(self, *x, **k):
        olay(f"pencere: {type(self).__name__} «{self.windowTitle()}»")
        return 0

    QDialog.exec = sahte_exec
    QDialog.exec_ = sahte_exec
    for ad, donus in (("question", QMessageBox.No), ("warning", QMessageBox.Ok), ("information", QMessageBox.Ok),
                      ("critical", QMessageBox.Ok)):
        setattr(QMessageBox, ad, staticmethod(lambda *x, _ad=ad, _d=donus, **k: (olay(
            f"soru: {_ad}: " + " | ".join(str(y)[:100] for y in x[1:3])), _d)[1]))
    QMessageBox.exec = lambda self, *x, **k: (olay(f"soru: {self.text()[:120]}"), QMessageBox.No)[1]
    QInputDialog.getText = staticmethod(lambda *x, **k: (olay("girdi"), ("", False))[1])
    QInputDialog.getItem = staticmethod(lambda *x, **k: (olay("girdi"), ("", False))[1])
    for ad in ("getOpenFileName", "getSaveFileName"):
        setattr(QFileDialog, ad, staticmethod(lambda *x, **k: ("", "")))
    QFileDialog.getExistingDirectory = staticmethod(lambda *x, **k: "")
    QDesktopServices.openUrl = staticmethod(lambda url, *x: (olay(f"aç: {url.toString()[:120]}"), True)[1])

    # kütüphane yolu gerçek kurulumdan (kaynak klasörde ajan-kutuphaneleri yok)
    uyarilar = []
    if KURULU_KUTUPHANE.is_dir():
        tools.BUNDLED_LIBS = libraries.BUNDLED_LIBS = KURULU_KUTUPHANE
    else:
        uyarilar.append(f"kurulu kopyanın ajan kütüphaneleri yok: {KURULU_KUTUPHANE}")
    if not a.model.startswith("cli:"):  # Claude Code / Codex / Gemini CLI: kullanıcının aboneliği harcanmasın
        cli_agents.installed = cli_agents.available = cli_agents.logged_in = lambda *x, **k: False
        cli_agents.available_agents = lambda: []

    def sinav_denetcisi(name, args, request, workspace, *x, **k):
        ok, neden = kural(name, args if isinstance(args, dict) else {}, Path(workspace), K.etiketler)
        K.onaylar.append(f"{name}: {'evet' if ok else 'hayır'} ({neden})"[:200])
        return security.Verdict("approve" if ok else "revise", security.LOW if ok else security.MEDIUM,
                                "Sınav kuralı: " + neden)

    security.review = sinav_denetcisi

    if gpu.fault():
        print("EKRAN KARTI ARIZALI (gpu.fault): sonuç yanıltıcı olur; bilgisayarı yeniden başlatıp tekrar dene.",
              flush=True)
        return 2

    from asistan.gui.window import MainWindow

    w = MainWindow()
    w.resize(1500, 950)
    w.show()
    bekle(app, 1.5)
    son = time.time() + 180
    while getattr(w, "probing", False) and time.time() < son:  # açılıştaki bağlam ölçümü bitsin
        bekle(app, 0.5)

    # arayüzden toplama: bağlantılar gönderme anında kurulduğu için örnek özniteliği yeterli (program kodu değişmez)
    orj = {"tool": w._tool_started, "failed": w._failed, "plan": w.chat.show_plan, "step": w.chat.update_step,
           "notice": w.chat.add_notice, "block": w.chat.add_security_block}

    def arac_basladi(call_id, name, args):
        K.araclar.append({"ad": name, "arg": json.dumps(args, ensure_ascii=False, default=str)[:160]})
        orj["tool"](call_id, name, args)

    def plan_geldi(steps):
        if steps:
            K.planlar.append([dict(s) for s in steps])
        orj["plan"](steps)

    def adim(i, status, note):
        K.adimlar[i] = status
        orj["step"](i, status, note)

    def not_(text, *x, **k):
        K.notlar.append(str(text)[:300])
        return orj["notice"](text, *x, **k)

    def engel(text, decision, why, on_disable):
        K.notlar.append(f"güvenlik: {text}"[:300])
        return orj["block"](text, decision, why, on_disable)

    def hata(msg):
        K.hatalar.append(str(msg)[:300])
        orj["failed"](msg)

    def onay(name, args):
        ok, neden = kural(name, args if isinstance(args, dict) else {}, Path(w._work_dir()), K.etiketler)
        K.onaylar.append(f"{name}: {'evet' if ok else 'hayır'} ({neden})"[:200])
        w.worker.answer_approval(ok)

    w._tool_started, w._failed, w._ask_approval = arac_basladi, hata, onay
    w.chat.show_plan, w.chat.update_step, w.chat.add_notice, w.chat.add_security_block = plan_geldi, adim, not_, engel
    orj_gunluk = w.right.log.add

    def gunluk(header, body=""):  # dürtü/denetim durumları (BÖLÜM 2-d: baloncukta değil günlükte) da kayda girsin
        if str(header).startswith("· "):
            K.notlar.append(f"durum: {str(header)[2:]}"[:300])
        return orj_gunluk(header, body)

    w.right.log.add = gunluk

    if not ollama_hazir(w.settings.ollama_url):
        print(f"Ollama yanıt vermiyor ({w.settings.ollama_url}); sınav yapılamaz.", flush=True)
        return 2

    port = bos_port()
    sunucu = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory",
                               str(denetim.EKLER / "api")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=KOK, capture_output=True, text=True).stdout.strip()
    gorevler = secilenler(a)
    ortak = {"kosu": a.kosu, "model": model_etiketi(a), "yonetici": a.yonetici or "sohbet modeli",
             "kapsam": kapsam(a), "tekrar": a.cocuk, "surum": __version__, "commit": commit}
    for u in uyarilar:
        print("UYARI: " + u, flush=True)
    try:
        for n, gorev in enumerate(gorevler, 1):
            try:
                satir = gorevi_yap(w, app, gorev, f"http://127.0.0.1:{port}", g, results)
            except Durmadi as e:
                print(f"DURDURULAMADI: {gorev['ad']}: {e}", flush=True)
                return 2
            satir = {**ortak, "tarih": datetime.datetime.now().isoformat(timespec="seconds"), **satir,
                     "uyarilar": uyarilar}
            with open(a.cikti, "a", encoding="utf-8") as f:
                f.write(json.dumps(satir, ensure_ascii=False) + "\n")
            print(f"[{a.cocuk}.{n}/{len(gorevler)}] {gorev['ad']:<20} {'✓' if satir['gecti'] else '✗'} "
                  f"{satir['sure']:5.0f} sn  {satir['modeller'].get('sohbet', '')}"
                  + (f"  · {satir['dusen'][0][:110]}" if satir["dusen"] else ""), flush=True)
    finally:
        sunucu.terminate()
    return 0


class Durmadi(RuntimeError):
    """Zaman aşımında ■ durdur'a basıldı ama iş kapanmadı: sonraki görevler güvenilir olmaz."""


def bekle(app, sn: float) -> None:
    son = time.time() + sn
    while time.time() < son:
        app.processEvents()
        time.sleep(0.03)


def ollama_hazir(url: str, sn: float = 30) -> bool:
    import urllib.request

    son = time.time() + sn
    while time.time() < son:
        try:
            urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=5).read()
            return True
        except OSError:
            time.sleep(2)
    return False


def tahmini_is_klasoru(w, metin: str) -> Path:
    """Programın kendi kuralıyla (window_run._send_or_stop): <çalışma>/<kategori>/<başlık>-<id>."""
    from asistan.work import chat_folder, guess_category

    klasor = w.conv.folder or w.current_folder
    kategori = klasor if klasor and klasor != "Genel" else guess_category(metin)
    return Path(chat_folder(w.settings.workspace, kategori, metin.splitlines()[0][:60], w.conv.id))


def hazirla(gorev: dict, is_klasoru: Path, results) -> None:
    for hz in gorev.get("hazirla") or []:
        hedef = Path(os.path.normpath(hz["hedef"].replace("{is}", str(is_klasoru))
                                      .replace("{proje}", str(results.project_dir()))))
        hedef.parent.mkdir(parents=True, exist_ok=True)
        if "metin" in hz:
            hedef.write_text(hz["metin"], encoding="utf-8")
        elif (denetim.EKLER / hz["kaynak"]).is_dir():
            shutil.copytree(denetim.EKLER / hz["kaynak"], hedef, dirs_exist_ok=True)
        else:
            shutil.copy2(denetim.EKLER / hz["kaynak"], hedef)


def gonder(w, app, metin: str, ekler: list[Path], bitis: float) -> str:
    """Kullanıcı gibi: ekleri koy, yaz, gönder, bitmesini bekle. Zaman aşımında ■ durdur."""
    w.chat.last_bubble = None  # yeni sohbette eski (silinmiş) balon kalıyor: cevap bu turun balonundan okunsun
    w.attachments = [str(p) for p in ekler]
    w._render_attachments()
    w.input.setPlainText(metin)
    w._send_or_stop()
    if w.worker is None:
        return "gönderilemedi"
    durdu = None
    while w.worker is not None:
        app.processEvents()
        time.sleep(0.03)
        if durdu is None and time.time() > bitis:
            durdu = time.time()
            w._send_or_stop()  # iş sürerken bu ■ durdur'dur
        elif durdu is not None and time.time() - durdu > DURDURMA_SN:
            raise Durmadi(f"■ durdurdan {DURDURMA_SN} sn sonra hâlâ çalışıyor")
    bekle(app, 0.8)  # bitişten sonra bağlam ölçümü başlayabilir (window_run: 500 ms)
    son = time.time() + 180
    while getattr(w, "probing", False) and time.time() < son:  # ölçüm sürerken sıradaki iş başlamasın
        bekle(app, 0.5)
    return "zaman aşımı" if durdu else ""


def dosya_boyutlari(klasor: Path) -> dict:
    return {str(p.relative_to(klasor)): p.stat().st_size for p in klasor.rglob("*") if p.is_file()} \
        if klasor.is_dir() else {}


def gorevi_yap(w, app, gorev: dict, sunucu: str, g: Path, results) -> dict:
    from asistan.tools import agent_env, python_exe

    K.sifirla()
    K.etiketler = denetim.etiketler(gorev)
    w.new_conversation()
    bitis = time.time() + gorev["zaman_siniri_sn"]
    t0 = time.time()
    mesajlar = [m.replace("{sunucu}", sunucu) for m in (gorev.get("onceki_mesajlar") or []) + [gorev["istek"]]]
    tahmin = tahmini_is_klasoru(w, mesajlar[0])
    hazirla(gorev, tahmin, results)
    if gorev.get("gecmis"):  # uzun sohbetin geçmişi (özetleme tuzağı): sohbete önceden konmuş mesajlar
        w.conv.messages.extend(json.loads((denetim.EKLER / gorev["gecmis"]).read_text(encoding="utf-8")))
    hata, onceki, modeller = "", None, {}
    for i, metin in enumerate(mesajlar):
        son = i == len(mesajlar) - 1
        if son and gorev.get("yeni_sohbette"):
            w.new_conversation()
        if son and i > 0 and not gorev.get("yeni_sohbette"):  # "devam et" öncesi dosyalar: python_denetim karşılaştırır
            onceki = g / f"onceki-{gorev['ad']}.json"
            onceki.write_text(json.dumps(dosya_boyutlari(Path(w._work_dir())), ensure_ascii=False), encoding="utf-8")
        ekler = [denetim.EKLER / e for e in gorev.get("ekler") or []] if son else []
        sonuc = gonder(w, app, metin, ekler, bitis)
        modeller["sohbet"] = getattr(w, "last_run_model", "")
        if i == 0 and gorev.get("hazirla") and any("{is}" in hz["hedef"] for hz in gorev["hazirla"]) \
                and Path(w.conv.work_dir) != tahmin:
            hata = f"hazırlık tutmadı: iş klasörü {w.conv.work_dir} (beklenen {tahmin})"
        if sonuc:
            hata = hata or sonuc
            break
    sure = time.time() - t0
    is_klasoru = Path(w._work_dir())
    cevap = w.chat.last_bubble.text() if w.chat.last_bubble is not None else ""
    isci = [re.sub(r"\*\*", "", n) for n in K.notlar if "yapıyor" in n]
    if isci:
        modeller["isci_notu"] = isci[0][:160]
    dusen = denetim.denetle(gorev, is_klasoru, cevap, [x["ad"] for x in K.araclar], K.planlar, onceki,
                            env=agent_env(), python=python_exe())
    if hata:
        dusen.insert(0, hata)
    elif K.hatalar:
        dusen.append("program hatası: " + K.hatalar[0][:150])
    return {"gorev": gorev["ad"], "sira": gorev["sira"], "etiketler": sorted(K.etiketler), "gecti": not dusen,
            "kademe": denetim.kademe(gorev), "tur": denetim.tur(gorev),
            "dusen": dusen, "sure": round(sure, 1), "zaman_asimi": hata == "zaman aşımı", "hata": hata,
            "cevap": cevap[:300], "araclar": K.araclar[:80],
            "plan": [a.get("title", "") for a in (K.planlar[-1] if K.planlar else [])], "adimlar": K.adimlar,
            "onaylar": K.onaylar[:40], "notlar": K.notlar[:20], "olaylar": K.olaylar[:20], "modeller": modeller,
            "is_klasoru_dosyalari": sorted(dosya_boyutlari(is_klasoru))[:40]}


if __name__ == "__main__":
    secim = secenekler()
    if secim.cocuk:
        try:
            kod = cocuk(secim)
        except Exception:
            print("SINAV ÇALIŞTIRICISI HATASI:\n" + traceback.format_exc(), flush=True)
            kod = 2
        sys.stdout.flush()
        os._exit(kod)  # Qt iş parçacıkları kapanmayı beklemesin (arayuz_denetimi gibi)
    sys.exit(ana(secim))
