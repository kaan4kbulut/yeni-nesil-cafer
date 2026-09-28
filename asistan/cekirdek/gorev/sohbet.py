"""Görev motorunu masaüstü sohbetine bağlar (bayrak `ayarlar.extra["gorev_motoru"]`, varsayılan kapalı).

Hangi istek motora gider: bayrak açıksa Manager plan çıkaracağı yerde işi motora verir (`Manager.motor`); ölçüt
`gorev_mu` (Manager'ın `needs_plan`'ı + salt okuyan çok adımlı analiz). Manager'ın öteki kararları aynen geçerli: CLI
sağlayıcısı, araçsız model, yardımcı ajan, tarayıcı işi motora gitmez. ✓ bekletme turunda da motor çalışır, çünkü ✓
beklemez: her değişiklik kendi adımında onay penceresiyle sorulur (aşağıda). Bayrak kapalıyken Manager yolu birebir
aynıdır. Bulut ve öteki yollar `sohbet_id` vermez: motor yalnızca masaüstü sohbetinde çalışır.

Sohbette görünen: plan kartı (Manager'ın adım biçimi: `title`, `status`, `note`, `secim`) ve adım durumları mevcut
geri çağrılarla (`on_plan`, `on_step`, `on_text`, araç kartları); yeni arayüz sinyali yok. Kullanıcı mesajında
`_plan` (kartın kaydı) ve `_gorev_id` (görevin kimliği) saklanır; asıl kayıt `gorevler.db`.

Onay: planda `onay_gerekli` olan ya da çalışırken izin hattının sorduğu adımda görev `bekliyor_onay` olur; burada
sohbetin onay penceresi (`ask_approval`) açılır, cevap `Yurutucu.onayla`'ya gider. Onay kuralı yine `permissions.py`'de.

Devam: bu sohbetin yarım görevi varsa "devam et" (ya da motorun sorusuna verilen cevap) görevi kaldığı yerden sürdürür;
yeni boş sohbette yalnızca "devam et" yazılırsa sohbetten başlatılmış son yarım görev sürer (kendi iş klasöründe).
"""

import re
from types import SimpleNamespace

from ..saglayici import Iptal
from . import durum as durum_mod
from .yurutucu import coz, temiz_sonuc

BAYRAK = "gorev_motoru"
SONUC_SINIRI = 4000  # sohbete yazılan son adım sonucu (karakter)

# motor durumu → plan kartının durumu (`manager.STEP_ICONS`)
KART_DURUMU = {"planlandi": "pending", "calisiyor": "running", "bekliyor_onay": "pending",
               "bekliyor_kullanici": "pending", "tamamlandi": "done", "basarisiz": "failed", "iptal": "skipped"}

# yarım görevi sürdüren mesaj: YALNIZCA "devam et" (başka iş yok). "hikâyenin devamını yaz" ya da "sürdürülebilirlik
# raporu" yeni istektir: eski görevi sürdürürse kullanıcının isteği sessizce kaybolurdu (denetçi, K4)
_YALNIZ_DEVAM = re.compile(
    r"^\s*(lütfen\s+)?((kaldığın|kaldığımız|kaldığı)\s+yerden\s+)?((görev(e|ine)|iş(e|ine))\s+)?(devam|sürdür)"
    r"(\s*(et|edelim|eder\s+misin|le|))?(\s+lütfen)?\s*[.!…]*\s*$", re.I)
# yarım görevi bırakmak (iptal: kayıt kalır). Ekler tek tek sayılır: "iptal etme", "vazgeçme", "bırakma" olumsuzdur,
# görevi bırakmak onların tam tersi olurdu (denetçi, K4)
_VAZGEC = re.compile(
    r"^\s*(lütfen\s+)?((bu\s+)?(görevi|işi)\s+)?(iptal(\s+(et|edelim|edin))?|vazgeç(tim|elim|tik)?|bırak(alım|ın)?)"
    r"(\s+lütfen)?\s*[.!…]*\s*$", re.I)


def acik_mi(ayarlar) -> bool:
    return bool((getattr(ayarlar, "extra", None) or {}).get(BAYRAK))


def gorev_mu(metin: str) -> bool:
    """Motora gidecek çok adımlı iş mi? Manager'ın plan kararı (`needs_plan`: yazan/kuran işler) ya da iki ayrı iş
    adımı olan salt okuyan analiz ("… dosyalarını say, en büyüğünü özetle"). Soru ve öneri isteği sohbet cevabıdır."""
    from ... import learning
    from ...agent import is_advice_request
    from ...manager import _LIST_ITEM, _STEP_VERBS, _TASK, needs_plan

    if needs_plan(metin):
        return True
    if (metin or "").startswith(("📈", "↻ ")):
        return False
    istek = learning.original_request(metin)
    if not istek or "?" in istek or is_advice_request(istek):
        return False
    adim = sum(1 for rx in (_TASK, _STEP_VERBS) for _ in rx.finditer(istek))
    return adim >= 2 or len(_LIST_ITEM.findall(istek)) >= 2


def yarim_gorev(sohbet_id: str, mesajlar: list, metin: str, depo: durum_mod.Depo | None = None) -> dict | None:
    """Bu mesaj yarım bir görevi mi sürdürüyor? Sürdürülecek görev ya da None (mesaj normal yoldan gider)."""
    if not sohbet_id or (depo is None and not durum_mod.varsayilan_yol().exists()):
        return None  # hiç görev yok (bayrak hiç açılmadı): veritabanı boşuna oluşturulmaz
    depo = depo or durum_mod.depo()
    bagli = [g for g in depo.sohbetin(sohbet_id) if g.get("durum") in durum_mod.YARIM]
    if bagli:
        gorev = bagli[0]
        # motorun sorusuna her mesaj cevaptır; "vazgeç" görevi bırakır
        if gorev["durum"] == "bekliyor_kullanici" or _YALNIZ_DEVAM.match(metin or "") or _VAZGEC.match(metin or ""):
            return gorev
        return None
    if not mesajlar and _YALNIZ_DEVAM.match(metin or ""):
        # başka sohbetin sorusu "devam et" ile cevaplanmaz: soru bekleyen görev kendi sohbetinde sürer
        return next((g for g in depo.sohbet_yarim() if g.get("durum") != "bekliyor_kullanici"), None)
    return None


def kart(gorev: dict) -> list[dict]:
    """Görevin adımları plan kartı biçiminde (Manager'ın adımlarıyla aynı alanlar)."""
    return [{"title": a["amac"][:80], "do": a["amac"], "done_when": a.get("basari_olcutu", ""),
             "status": KART_DURUMU.get(a.get("durum"), "pending"),
             "note": (a.get("sonuc_ozeti") or a.get("not") or "")[:300], "secim": a.get("secim") or {}}
            for a in gorev.get("adimlar") or []]


def sonuc_metni(gorev: dict) -> str:
    """Tur bitince sohbete yazılan metin: sonuç ya da dürüstçe "yapılamadı"."""
    durum, rapor = gorev.get("durum"), gorev.get("rapor") or ""
    if durum == "bekliyor_kullanici":
        return rapor
    if durum == "tamamlandi":
        son = next((a for a in reversed(gorev.get("adimlar") or []) if a.get("durum") == "tamamlandi"), None)
        sonuc = temiz_sonuc((son or {}).get("sonuc", "")).strip()
        adim = len(gorev.get("adimlar") or [])
        return (sonuc[:SONUC_SINIRI] if sonuc else rapor) + f"\n\n*Görev tamamlandı ({adim}/{adim} adım).*"
    if durum == "iptal":
        return rapor or "Görev durduruldu."
    if durum == "basarisiz":
        return ("**Yapılamadı.** " + rapor.replace("\n", "\n\n", 1)
                + "\n\nYarım kalan adımlar planda işaretli; isteği değiştirip yeniden deneyebilirsin.")
    return rapor


class SohbetGorevi:
    """Tek sohbet turu: motoru kurar, olayları sohbetin geri çağrılarına çevirir, onayları sorar."""

    def __init__(self, ajan, sohbet_id: str, motor_kur=None):
        self.ajan, self.cb, self.sohbet_id = ajan, ajan.cb, sohbet_id
        self.kart: list[dict] = []  # kullanıcı mesajında `_plan` olarak kalır (yerinde güncellenir)
        self._motor_kur = motor_kur
        self._depo = None  # testler sahte depo verir; None: programın deposu
        # sohbet ajanının izin bağlamı. ✓ bekletme turunda (varsayılan kip, ▶ basılmadı) motor ▶ turu gibi
        # davranır: her değişiklik tek tek sorulur (`permissions.decide`: `must_act and action`), sessizce yapılmaz
        # ✓ turunda "komutları onayla" kutusu kapalı olsa da: ▶'a basılmadan hiçbir değişiklik sorulmadan yapılmaz
        self.izin = SimpleNamespace(must_act=bool(ajan.must_act or ajan.gate_actions),
                                    confirm_commands=bool(ajan.gate_actions),
                                    always_allowed=ajan.always_allowed, auto_approve=ajan.auto_approve)

    def _kur(self, gorev_id: str, istek: str):
        from .komut import motor_kur

        baglam = getattr(self.ajan, "gorev_baglami", None) or {}
        kur = self._motor_kur or motor_kur
        return kur(self.ajan.settings, self.ajan.connections, istek=istek, gorev_id=gorev_id, olay=self._olay,
                   iptal=self._iptal, kaynak="sohbet", klasor=str(self.ajan.toolbox.root),
                   okunur=baglam.get("ana_klasor", ""), ust_cb=self.cb, izin_kaynagi=self.izin,
                   sohbet_id=self.sohbet_id)

    def _iptal(self) -> bool:
        fn = getattr(self.cb, "is_cancelled", None)
        return bool(fn and fn())

    def _emit(self, ad: str, *a):
        fn = getattr(self.cb, ad, None)
        if fn:
            fn(*a)

    # ---- motorun olayları → sohbet
    def _kart_yenile(self, gorev: dict) -> None:
        self.kart[:] = kart(gorev)

    def _olay(self, tur: str, veri: dict) -> None:
        gorev = veri.get("gorev") or {}
        if tur == "plan":
            self._kart_yenile(gorev)
            self._emit("on_plan", self.kart)
        elif tur in ("adim", "tekrar", "onay") and veri.get("adim"):
            adim = veri["adim"]
            i = int(adim["id"]) - 1
            if not 0 <= i < len(self.kart):
                return
            durum = {"tekrar": "fixing", "onay": "pending"}.get(tur, KART_DURUMU.get(adim.get("durum"), "pending"))
            not_ = {"tekrar": veri.get("neden", ""), "onay": "onay bekliyor"}.get(
                tur, adim.get("sonuc_ozeti") or adim.get("not") or "")
            self.kart[i].update(status=durum, note=str(not_)[:300])
            self._emit("on_step", i, durum, self.kart[i]["note"])

    def _onay_iste(self, gorev: dict) -> bool:
        """Onay bekleyen adımı sohbetin onay penceresine sorar."""
        adim = next((a for a in gorev["adimlar"] if a.get("durum") == "bekliyor_onay"), None)
        ask = getattr(self.cb, "ask_approval", None)
        if adim is None or ask is None:
            return False
        return bool(ask(adim["yetenek"], coz(adim.get("girdi") or {}, gorev)))

    # ---- tur
    def calistir(self, mesajlar: list, metin: str, gorev: dict | None = None) -> dict:
        """Yeni görev (`gorev` None) ya da yarım görevi sürdürme. Görevin son hâlini döndürür."""
        kullanici = {"role": "user", "content": metin, "_plan": self.kart}
        mesajlar.append(kullanici)
        self.ajan.user_text = metin
        if gorev is not None and _VAZGEC.match(metin or ""):
            (self._depo or durum_mod.depo()).iptal_et(gorev["gorev_id"])
            kullanici["_gorev_id"] = gorev["gorev_id"]
            self._emit("on_plan", [])
            metin_ = f"Görev bırakıldı: «{gorev.get('istek', '')[:80]}». Kaydı Görevler penceresinde kalır."
            self._emit("on_text", metin_)
            mesajlar.append({"role": "assistant", "content": metin_})
            return dict(gorev, durum="iptal")
        try:
            if gorev is None:
                gorev_id = durum_mod.yeni_id()
                kullanici["_gorev_id"] = gorev_id
                self._emit("on_plan", None)  # "plan çıkarılıyor…"
                motor = self._kur(gorev_id, metin)
                self._emit("on_route", "🧭 Görev motoru: plan kaydedilir; program kapansa da «devam et» ile sürer")
                gorev = motor.baslat(metin, gorev_id=gorev_id)
            else:
                gorev_id = gorev["gorev_id"]
                kullanici["_gorev_id"] = gorev_id
                self._kart_yenile(gorev)
                self._emit("on_plan", self.kart)
                motor = self._kur(gorev_id, gorev.get("istek", ""))
                if gorev["durum"] == "bekliyor_kullanici":
                    gorev = motor.yanitla(gorev_id, metin)
                elif gorev["durum"] != "bekliyor_onay":
                    self._emit("on_route", f"⏯ Yarım görev sürüyor: «{gorev.get('istek', '')[:80]}»")
                    gorev = motor.devam(gorev_id)
            while gorev.get("durum") == "bekliyor_onay":
                evet = self._onay_iste(gorev)
                if self._iptal():  # ■ onay penceresini "hayır"la kapatır: görev iptal olmasın, yarım kalsın
                    raise Iptal()
                gorev = motor.onayla(gorev_id, evet)
        except Iptal:
            mesajlar.append({"role": "assistant", "content": "[Kullanıcı tarafından durduruldu: görev yarım kaldı, "
                                                             "«devam et» yazınca kaldığı yerden sürer]"})
            raise
        if not gorev.get("adimlar"):
            self._emit("on_plan", [])  # plan yok (soru ya da plan çıkarılamadı): kart gizlenir
        else:
            self._kart_yenile(gorev)
        metin_ = sonuc_metni(gorev)
        self._emit("on_text", metin_)
        mesajlar.append({"role": "assistant", "content": metin_})
        return gorev


def calistir(ajan, mesajlar: list, metin: str, sohbet_id: str, gorev: dict | None = None, motor_kur=None,
              depo: durum_mod.Depo | None = None) -> dict:
    """Sohbet turunu görev motoruyla çalıştırır (yeni görev, `gorev`i sürdürme ya da "vazgeç" ile bırakma)."""
    tur = SohbetGorevi(ajan, sohbet_id, motor_kur)
    tur._depo = depo
    # motorun adımları kendi izin hattından geçer; bu tur ✓ bekleyen bir plan değildir (arayüz ▶ önermesin)
    ajan.gate_actions = False
    return tur.calistir(mesajlar, metin, gorev)
