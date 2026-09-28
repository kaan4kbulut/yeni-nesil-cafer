"""Görev deposu (SQLite): `DATA_DIR/gorevler.db` (docs/MIMARI.md §5; `.cafer/` = programın veri klasörü, SORULAR K2/K4).

Her görev SEMALAR §2 biçiminde tek JSON olarak saklanır; liste ve arama için durum/istek/zaman ayrı sütunda. Programın
öteki veri dosyalarıyla (`hafiza.db`, `bulut.db`, sohbet JSON'ları) dosya ya da tablo paylaşmaz. Her işlem kendi
bağlantısını açar: arayüz iş parçacığı ile görev iş parçacığı aynı anda okuyup yazabilir.

"Yarım görev": durumu bitmemiş (planlandı, çalışıyor, onay/kullanıcı bekliyor) görev. Program kapanırken "calisiyor"da
kalan görev de yarımdır; `devam_noktasi` kaldığı adımı verir (`checkpoint.son_adim + 1`).
"""

import json
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

SURUM = 1  # PRAGMA user_version: tablo biçimi değişirse artar

BITMIS = ("tamamlandi", "basarisiz", "iptal")
YARIM = ("planlandi", "calisiyor", "bekliyor_onay", "bekliyor_kullanici")
KLASOR_ALANI = "_klasor"  # görevin iş klasörü (program alanı, SEMALAR §2 dışı): sürdürülünce aynı klasörde çalışır


def varsayilan_yol() -> Path:
    from ..ayar import DATA_DIR

    return Path(DATA_DIR) / "gorevler.db"


def simdi() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def yeni_id() -> str:
    """"2026-09-27T20-41-03_a1b2" biçimi (SEMALAR §2)."""
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S") + "_" + secrets.token_hex(2)


class Depo:
    def __init__(self, yol: str | Path | None = None):
        self.yol = Path(yol) if yol else varsayilan_yol()
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._baglan()) as b, b:
            b.execute("""CREATE TABLE IF NOT EXISTS gorevler (
                gorev_id TEXT PRIMARY KEY, durum TEXT NOT NULL, istek TEXT NOT NULL, olusturma TEXT NOT NULL,
                guncelleme REAL NOT NULL, sohbet_id TEXT NOT NULL DEFAULT '', veri TEXT NOT NULL)""")
            b.execute("CREATE INDEX IF NOT EXISTS gorevler_durum ON gorevler (durum, guncelleme)")
            b.execute(f"PRAGMA user_version = {SURUM}")

    def _baglan(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.yol), timeout=10)

    def kaydet(self, gorev: dict, sohbet_id: str | None = None) -> None:
        """Görevi yazar (varsa üstüne). `sohbet_id` verilmezse eski değer korunur."""
        with closing(self._baglan()) as b, b:
            eski = b.execute("SELECT sohbet_id FROM gorevler WHERE gorev_id = ?", (gorev["gorev_id"],)).fetchone()
            sid = sohbet_id if sohbet_id is not None else (eski[0] if eski else gorev.get("_sohbet_id", ""))
            b.execute("INSERT OR REPLACE INTO gorevler VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (gorev["gorev_id"], gorev.get("durum", "planlandi"), gorev.get("istek", ""),
                       gorev.get("olusturma", ""), time.time(), sid or "",
                       json.dumps(gorev, ensure_ascii=False)))

    def getir(self, gorev_id: str) -> dict | None:
        with closing(self._baglan()) as b:
            satir = b.execute("SELECT veri FROM gorevler WHERE gorev_id = ?", (gorev_id,)).fetchone()
        return json.loads(satir[0]) if satir else None

    def listele(self, durumlar: tuple[str, ...] | None = None, sinir: int = 100) -> list[dict]:
        """En son güncellenen önce."""
        sorgu, arg = "SELECT veri FROM gorevler", []
        if durumlar:
            sorgu += f" WHERE durum IN ({','.join('?' * len(durumlar))})"
            arg += list(durumlar)
        sorgu += " ORDER BY guncelleme DESC LIMIT ?"
        with closing(self._baglan()) as b:
            return [json.loads(s[0]) for s in b.execute(sorgu, (*arg, sinir))]

    def yarim(self) -> list[dict]:
        """Bitmemiş görevler ("yarım görevler" listesi)."""
        return self.listele(YARIM)

    def sohbetin(self, sohbet_id: str) -> list[dict]:
        """Bir sohbetten başlatılan görevler (en yeni önce)."""
        with closing(self._baglan()) as b:
            return [json.loads(s[0]) for s in b.execute(
                "SELECT veri FROM gorevler WHERE sohbet_id = ? ORDER BY guncelleme DESC", (sohbet_id,))]

    def sohbet_yarim(self) -> list[dict]:
        """Sohbetten başlatılmış yarım görevler (en yeni önce); komut satırı ve Görevler penceresinin görevleri hariç."""
        with closing(self._baglan()) as b:
            return [json.loads(s[0]) for s in b.execute(
                f"SELECT veri FROM gorevler WHERE sohbet_id != '' AND durum IN ({','.join('?' * len(YARIM))}) "
                "ORDER BY guncelleme DESC", YARIM)]

    def iptal_et(self, gorev_id: str) -> bool:
        """Görevi silmez, `iptal` durumuna alır (listeden düşer, kayıt kalır)."""
        gorev = self.getir(gorev_id)
        if gorev is None or gorev.get("durum") in BITMIS:
            return False
        gorev["durum"] = "iptal"
        self.kaydet(gorev)
        return True


def devam_noktasi(gorev: dict) -> int:
    """Sıradaki adımın dizini (0'dan): checkpoint'ten sonraki ilk bitmemiş adım; hepsi bittiyse adım sayısı."""
    adimlar = gorev.get("adimlar") or []
    son = int((gorev.get("checkpoint") or {}).get("son_adim") or 0)
    for i, adim in enumerate(adimlar):
        if adim.get("id", i + 1) > son and adim.get("durum") != "tamamlandi":
            return i
    for i, adim in enumerate(adimlar):  # checkpoint'ten önce yarım kalan (ör. elle sıfırlanmış) adım
        if adim.get("durum") != "tamamlandi":
            return i
    return len(adimlar)


_DEPO: Depo | None = None


def depo() -> Depo:
    """Programın görev deposu (tek örnek; yol `DATA_DIR`'den)."""
    global _DEPO
    if _DEPO is None or _DEPO.yol != varsayilan_yol():
        _DEPO = Depo()
    return _DEPO
