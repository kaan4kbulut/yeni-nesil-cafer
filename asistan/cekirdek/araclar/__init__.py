"""Temel araçların uygulaması: dosya (`dosya`), komut ve Python (`komut`), web (`web`).

Araç tanımları, risk sınıfları ve tek çalıştırma yolu değişmedi: `tools.py` (`REGISTRY.add`, `Toolbox._tool_<ad>`) →
`agent._execute_tool` → `permissions.decide`. `Toolbox` bu modüllere devreder; K5'te her biri `yetenekler/` altında
manifestli bir yeteneğe dönüşür.
"""

from .temel import AracHatasi  # noqa: F401
