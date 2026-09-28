"""Araçların ortak parçaları: hata sınıfı, gizli dosyalar, pencere bayrağı."""

import subprocess
import sys

GIZLI_DOSYALAR = {"anahtarlar.json", "ayarlar.json"}  # anahtarlar ve ayarlar: asistan bunları okuyamaz
PENCERESIZ = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # Windows: konsol penceresi açılmasın


class AracHatasi(Exception):
    """Aracın modele bildirilecek hatası (eski adı `tools.ToolError`, aynı sınıf)."""
