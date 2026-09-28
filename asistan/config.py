"""Uygulama ayarları ve sohbet kayıtlarının diskteki yeri.

K1'den beri asıl kod `asistan.cekirdek.ayar`'da (tek ayar kaynağı: ayarlar.json + ayar.toml + CAFER_*); bu modül aynı
nesneleri eski adlarıyla dışa aktarır. Yeni kod `from asistan.cekirdek.ayar import …` kullanır.
"""

from .cekirdek.ayar import (  # noqa: F401  (eski yol: aynı nesneler)
    _CONFIG_BASE,
    _DATA_BASE,
    APP_ID,
    CHATS_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    DATA_DIR,
    OLD_ID,
    Settings,
    migrate_dir,
)

from .cekirdek import modeller as _modeller

CLAUDE_MODELS = _modeller.deger("claude.modeller")  # önerilen başta (ayar/modeller.json)
