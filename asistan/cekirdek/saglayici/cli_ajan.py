"""CLI ajanları (`claude -p`, `codex exec`, Gemini CLI): kullanıcının kendi hesabıyla, alt süreç olarak.

Kurulum, giriş ve süreç yönetimi `asistan.cli_agents`'ta; bu sınıf onu sağlayıcı arayüzüne bağlar. CLI ajanı araçlarını
kendisi çalıştırır: sağlayıcı tek bir cevap metni verir (akış yok, adımlar `adim` geri çağrısıyla gelir).
Kural (CLAUDE.md): yalnızca kullanıcının sohbette gönderdiği istekte çalışır; kuyruğa ya da zamanlanmış işe bağlanmaz.
"""

from collections.abc import Callable, Iterator

from ... import cli_agents
from .temel import METIN, SON, Iptal, Parca, Saglayici, Saglik


def istem(mesajlar: list, gecmis_sayisi: int = 6, karakter: int = 1500) -> str:
    """Son isteğe önceki konuşmanın kısa özetini ekler (program her çağrıda yeni oturum açar)."""
    gecmis = [m for m in mesajlar[:-1] if isinstance(m.get("content"), str) and m["content"].strip()][-gecmis_sayisi:]
    son = mesajlar[-1]["content"]
    if not gecmis:
        return son
    baglam = "\n\n".join(f"{m['role']}: {m['content'][:karakter]}" for m in gecmis)
    return f"Earlier conversation:\n{baglam}\n\nCurrent request:\n{son}"


class CliAjanSaglayici(Saglayici):
    def __init__(self, ad: str, model: str = ""):
        if not cli_agents.is_cli(ad) or ad not in cli_agents.AGENTS:
            raise ValueError(f"bilinmeyen CLI ajanı: {ad}")
        self.ad, self.model = ad, model
        self.ajan = cli_agents.AGENTS[ad]

    def akis(self, mesajlar: list, sistem: str = "", araclar: list | None = None, *, klasor: str = ".",
             duzenleyebilir: bool = False, iptal: Callable[[], bool] | None = None,
             adim: Callable[[str, str, bool], None] | None = None, model: str = "", **_) -> Iterator[Parca]:
        """Tek parça METIN + SON. `araclar` yok sayılır (CLI ajanı kendi araçlarını kullanır).

        İptal edilirse `InterruptedError`; `duzenleyebilir=False` iken ajan dosya değiştiremez (onay bekleyen tur)."""
        try:
            metin = cli_agents.run(self.ad, istem(mesajlar), klasor, sistem, edits=duzenleyebilir, cancelled=iptal,
                                   on_step=adim, model=model or self.model)
        except InterruptedError:  # K12-E6: ■ zincirde aynı CLI'ı ve ücretli modeli denemesin
            raise Iptal() from None
        yield Parca(METIN, metin)
        yield Parca(SON, son={"model": self.ajan.title.lower()})

    def saglik(self) -> Saglik:
        if not cli_agents.installed(self.ad):
            return Saglik(False, f"{self.ajan.title} kurulu değil")
        if not cli_agents.logged_in(self.ad):
            return Saglik(False, f"{self.ajan.title} için giriş yapılmamış")
        return Saglik(True)
