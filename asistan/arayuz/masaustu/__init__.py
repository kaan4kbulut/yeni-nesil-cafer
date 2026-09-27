"""Masaüstü yüzü (PySide6). Pencere kodu şimdilik `asistan/gui/`'de; bu paket onu çekirdeğin üstündeki yüz olarak sunar.

Fiziksel taşıma yapılmadı (K1): `testler/arayuz_denetimi.py` gui modüllerini tek tek yamalıyor, `main.py` simge yolunu
`asistan/gui/assets`'ten alıyor ve güncelleme geri dönüşü `main.py`'ye dokunmadan çalışmalı. İçe aktarmalar bilerek
hemen yapılır: `import asistan.arayuz.masaustu` masaüstünün açılabildiğinin duman testidir.
"""

from ...gui.theme import apply_theme  # noqa: F401
from ...gui.window import MainWindow  # noqa: F401
from ...gui.worker import AgentWorker  # noqa: F401
