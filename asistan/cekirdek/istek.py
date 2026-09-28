"""Bir isteği çalıştırmak: ajanı kurmak (iş klasörü, onay kipi, sansürsüz not, beceriler) ve yönetici döngüsüyle
çalıştırmak. Masaüstü (`gui/window_run.py` + `gui/worker.py`) ve bulut sunucu aynı yolu kullanır; web ve komut satırı
da buradan çağıracak. Arayüz yalnızca olayları gösterir (`agent.Callbacks`), karar burada verilir.
"""

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from .saglayici import Iptal, hata_metni

_gunluk = logging.getLogger(__name__)

# bu sohbetin iş klasörü: diğer işler salt okunur (CLAUDE.md: her sohbet kendi iş klasöründe)
IS_KLASORU_NOTU = (
    "\n\n## This conversation's folder\nThe workspace `{work}` belongs only to this conversation; everything you "
    "create goes there. Other tasks live in sibling folders under `{root}`: never list, read or change them unless "
    "the user explicitly asks about them. Words like \"files\", \"steps\" or \"models\" in a request refer to "
    "the user's request itself (for example the app's own UI), not to whatever files happen to exist.")

# sansürsüz mod: kullanıcı filtresiz yerel modeli kendisi seçti; bilgisayardaki işlemlerin kuralları değişmez
SANSURSUZ_NOTU = (
    "\n\n## Unfiltered mode\nThe user switched on unfiltered mode and chose an uncensored local model. Answer "
    "directly, frankly and completely: no moralizing, lectures, unnecessary disclaimers or refusals of ordinary "
    "requests. The app's rules for actions on the computer (approval of commands, file changes, installs) stay "
    "exactly the same.")

ONERI_NOTU = (
    "\n\n## The user only asked for suggestions\nGive the suggestions; do NOT run commands, code or change "
    "anything now. Read-only checks (reading files, searching, read-only commands) are fine. If they want "
    "one applied, they will ask.")

UYGULA = "▶ "  # "uygula" düğmesinin mesajın başına koyduğu işaret


@dataclass
class IstekBaglami:
    """Ajanı kurmak için gereken her şey (arayüzden bağımsız)."""

    metin: str  # kullanıcının mesajı
    ayarlar: object  # kullanıcının ayarları (`cekirdek.ayar.Settings`): ana çalışma klasörü, onay kipi
    ajan_ayarlari: object = None  # ajanın çalışacağı ayarlar (sansürsüzde yerel model); None: `ayarlar`
    is_klasoru: str = ""  # bu sohbetin iş klasörü; boş: ana çalışma klasörü
    profil: object = None  # `profiles.AgentProfile` (yardımcı ajan) ya da None (ana asistan)
    baglantilar: list = field(default_factory=list)
    ekip: list = field(default_factory=list)  # grup çalışmasına verilebilecek ajanlar
    sansursuz: bool = False
    her_zaman_izinli: bool = False  # "bu oturumda hep izin ver"
    devam_projesi: dict | None = None  # "… devam et": kayıtlı proje (learning)
    cli_modeli: str = ""  # Claude Code / Codex modeli (opus, sonnet…)
    sohbet_id: str = ""  # masaüstü sohbetinin kimliği: görev motoru görevi sohbete bağlar (boş: motor yok)


def ajan_hazirla(b: IstekBaglami, geri_cagri=None):
    """İstek için ajanı kurar. (ajan, kullanılan beceriler) döner; beceriler arayüzde bildirilir ve öğrenmeye gider."""
    from .. import learning
    from ..agent import Agent, is_advice_request

    ayar = b.ajan_ayarlari or b.ayarlar
    ana = b.ayarlar.workspace
    if b.is_klasoru and b.is_klasoru != ana:
        ayar = replace(ayar, workspace=b.is_klasoru)
    ajan = Agent(ayar, geri_cagri, b.profil, b.baglantilar, team_tool=b.profil is None, team=b.ekip)
    if b.is_klasoru and b.is_klasoru != ana:
        # diğer işler salt okunur kalır: kullanıcı açıkça isterse eski bir işe bakılabilir
        kok = Path(ana).expanduser().resolve()
        ajan.toolbox.read_roots.append(kok)
        ajan.extra_system = (ajan.extra_system or "") + IS_KLASORU_NOTU.format(work=ajan.toolbox.root, root=kok)
        if b.devam_projesi:
            ajan.extra_system += learning.project_note(b.devam_projesi)
    if b.sansursuz:
        ajan.extra_system = (ajan.extra_system or "") + SANSURSUZ_NOTU
    ajan.always_allowed = b.her_zaman_izinli
    uygula = b.metin.startswith(UYGULA)
    if b.ayarlar.approval_mode == "guvenlik":
        # güvenlik ajanı kipi: onay sorulmaz; asistan işe hemen başlar, her adımı güvenlik ajanı denetler
        ajan.gate_actions = False
    elif b.sansursuz:
        # sansürsüz modda güvenlik ajanı çalışamıyor, ama "önce plan, sonra ▶" de yok: model plan yazıp
        # duruyordu. İşe hemen başlar; komut ve kurulum gibi riskli adımlar yine tek tek kullanıcıya sorulur.
        ajan.gate_actions = False
        ajan.must_act = uygula
    else:
        # varsayılan: hiçbir işlem kendiliğinden yapılmaz; değişiklikler bekler, yanıtın kenarına ✓ gelir
        ajan.gate_actions = not uygula
        ajan.must_act = uygula  # "uygula" düğmesi: yazıp geçmesin, gerçekten yapsın
    if b.ayarlar.approval_mode == "guvenlik" and is_advice_request(b.metin):
        ajan.extra_system = (ajan.extra_system or "") + ONERI_NOTU  # yalnızca öneri istendi: hiçbir şey yapılmasın
    ajan.cli_model = b.cli_modeli
    ajan.gorev_baglami = {"sohbet_id": b.sohbet_id, "ana_klasor": ana}  # görev motoru (`gorev/sohbet.py`)
    # beceri kütüphanesi: benzer bir iş daha önce başarıyla yapıldıysa yöntemini asistana ver
    beceriler = learning.find_skills(learning.original_request(b.metin)) if not b.metin.startswith("📈") else []
    if beceriler:
        ajan.extra_system = (ajan.extra_system or "") + learning.skills_prompt(beceriler)
    return ajan, beceriler


def calistir(ajan, saglayici: str, mesajlar: list, metin: str) -> None:
    """İsteği yönetici döngüsüyle çalıştırır (plan → adımlar → denetim). Hatalar ve `Iptal` yukarı çıkar.

    Masaüstü sohbetinde (`sohbet_id` dolu): bu sohbetin yarım görevi "devam et" ile sürer; görev motoru bayrağı
    açıksa (`gorev/sohbet.py`) Manager'ın plan çıkaracağı iş motora gider. İkisi de yoksa Manager yolu aynen."""
    from ..manager import Manager

    sohbet_id = (getattr(ajan, "gorev_baglami", None) or {}).get("sohbet_id", "")
    if sohbet_id and ajan.profile is None:
        from .gorev import sohbet

        try:
            yarim = sohbet.yarim_gorev(sohbet_id, mesajlar, metin)
        except Exception as e:  # gorevler.db bozuk/kilitli: sohbet bozulmasın, Manager yolu sürer
            _gunluk.warning("yarım görev okunamadı: %s", e)
            yarim = None
        if yarim is not None:
            from . import yonlendirici

            # Manager.run'daki gibi: görev başına bulut sayacı sıfırlanır; tavan aşılınca soru motorun model
            # çağrısında (`gorev/model.py`, `permissions.bulut_tavani`)
            yonlendirici.gorev_basla()
            sohbet.calistir(ajan, mesajlar, metin, sohbet_id, yarim)
            return
    yonetici = Manager(ajan)
    if sohbet_id and ajan.profile is None:
        from .gorev import sohbet

        if sohbet.acik_mi(ajan.settings):
            yonetici.motor = lambda m, t: sohbet.calistir(ajan, m, t, sohbet_id)
            yonetici.motor_karari = sohbet.gorev_mu
    yonetici.run(saglayici, mesajlar, metin)


@dataclass
class Sonuc:
    durum: str  # "tamam" | "durduruldu" | "hata"
    hata: str = ""  # kullanıcıya gösterilecek Türkçe metin
    istisna: Exception | None = None


def istegi_calistir(ajan, saglayici: str, mesajlar: list, metin: str) -> Sonuc:
    """`calistir` + sonucu arayüzün göstereceği biçime çevirir (durdurma ve hata yakalanır)."""
    try:
        calistir(ajan, saglayici, mesajlar, metin)
    except Iptal:
        return Sonuc("durduruldu")
    except Exception as e:
        _sagligi_bildir(saglayici, e)
        return Sonuc("hata", hata_metni(e), e)
    return Sonuc("tamam")


def _sagligi_bildir(saglayici: str, hata: Exception) -> None:
    """Bağlantı kurulamadı ya da anahtar reddedildi: yönlendirici bu sağlayıcıyı bir süre sağlıksız sayar,
    sonraki istek yedeğe gider (docs/MIMARI.md §4 madde 6)."""
    import httpx

    from . import yonlendirici

    ulasilamadi = isinstance(hata, (httpx.ConnectError, httpx.ConnectTimeout)) or type(hata).__name__ in (
        "AuthenticationError", "APIConnectionError") or "(401)" in str(hata)
    if ulasilamadi:
        yonlendirici.SAGLIK.bildir(saglayici, False, hata_metni(hata)[:200])
