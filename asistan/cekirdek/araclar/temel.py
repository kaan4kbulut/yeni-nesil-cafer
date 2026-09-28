"""Araçların ortak parçaları: hata sınıfı, gizli dosyalar, pencere bayrağı."""

import subprocess
import sys

GIZLI_DOSYALAR = {"anahtarlar.json", "ayarlar.json", "bulut.json"}  # anahtarlar, ayarlar, sunucu/Telegram anahtarı
# veri klasöründe (DATA_DIR) asistanın okuyamayacağı alt klasörler (K12-B5): tarayıcı oturum çerezleri, MCP günlükleri
GIZLI_KLASORLER = ("tarayici-profili", "mcp-kayitlari")


def gizli_yollar(veri_klasoru) -> list:
    """DATA_DIR altındaki gizli klasörlerin tam yolları (dosya araçları ve sandbox kancası için)."""
    from pathlib import Path

    return [Path(veri_klasoru) / ad for ad in GIZLI_KLASORLER]


PENCERESIZ = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # Windows: konsol penceresi açılmasın


class AracHatasi(Exception):
    """Aracın modele bildirilecek hatası (eski adı `tools.ToolError`, aynı sınıf)."""
