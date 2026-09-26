"""Araç kaydı: programdaki bütün araçlar tek yerde, tek biçimde.

Her araç için ad, açıklama, JSON şeması (MCP'deki `inputSchema` ile aynı), risk sınıfı, arayüzdeki Türkçe adı ve
kaynağı (yerleşik ya da bir MCP sunucusu) burada durur. Onay kuralları, güvenlik ajanının ilk sınıflandırması,
girdi doğrulama ve sohbetteki araç kartları bu kayıttan beslenir; bir araç eklemek için tek bir kayıt yeter.

Risk sınıfları (onay kuralı buradan çıkar):
- okur: yalnızca bilgi okur (dosya okuma, web araması) — onaysız
- danisir: başka bir modele sorar, hafızaya yazar, uygulama açar — onaysız, sistemi değiştirmez
- yazar: çalışma klasörüne yazar (dosya, resim) — değişiklik sayılır, onayı kipe göre
- ekip: işi ekibe devreder — değişiklik sayılır
- calistirir: komut / kod / dış araç çalıştırır — her zaman onay (güvenlik ajanı ya da kullanıcı)
- kurar: paket kurar — her zaman onay
"""

import re
from dataclasses import dataclass, field
from typing import Callable

RISKS = ("okur", "danisir", "yazar", "ekip", "calistirir", "kurar")
ACTION_RISKS = {"yazar", "ekip", "calistirir", "kurar"}  # sistemde / dosyalarda bir şey değiştirir
APPROVAL_RISKS = {"calistirir", "kurar"}  # her seferinde onay ister


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    risk: str
    label: tuple[str, str] = ("", "")  # (kısa ad, bittiğinde yazan) — sohbetteki araç kartı
    source: str = "yerlesik"  # "yerlesik" ya da "mcp:<sunucu>"
    group: str = "herkes"  # "temel": ajan profilleri seçer · "herkes": her ajanda · "ozel": koşula bağlı eklenir
    runner: Callable[[dict], str] | None = None  # dış araçlar (MCP): args -> sonuç metni
    trusted: bool = False  # kullanıcı bu dış aracı onaysız çalıştırmaya izin verdi
    hints: dict = field(default_factory=dict)  # MCP işaretleri: readOnlyHint, destructiveHint, openWorldHint…

    @property
    def spec(self) -> dict:
        """Modele giden tanım (Anthropic biçimi; OpenAI/Ollama biçimine agent.py çevirir)."""
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


@dataclass
class Registry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, spec: dict, risk: str, label: tuple[str, str] = ("", ""), group: str = "herkes", **kw) -> dict:
        """Yerleşik aracı kaydeder; tanımı (spec) aynen geri verir ki tools.py'de sabit olarak kalsın."""
        if risk not in RISKS:
            raise ValueError(f"Bilinmeyen risk sınıfı: {risk}")
        self.tools[spec["name"]] = Tool(spec["name"], spec["description"], spec["input_schema"], risk,
                                        label, group=group, **kw)
        return spec

    def put(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def remove_source(self, source: str) -> None:
        """Bir kaynağın (ör. kapatılan MCP sunucusu) bütün araçlarını kayıttan çıkarır."""
        for name in [n for n, t in self.tools.items() if t.source == source]:
            del self.tools[name]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def specs(self, group: str | None = None, source: str | None = None) -> list[dict]:
        return [t.spec for t in self.tools.values()
                if (group is None or t.group == group) and (source is None or t.source.startswith(source))]

    def external(self) -> list[Tool]:
        """Dışarıdan takılan araçlar (MCP sunucuları)."""
        return [t for t in self.tools.values() if t.source != "yerlesik"]

    def label(self, name: str) -> tuple[str, str]:
        tool = self.tools.get(name)
        if tool is None:
            return name, ""
        return tool.label if tool.label[0] else (name, "")


REGISTRY = Registry()


def safe_name(text: str) -> str:
    """Model API'lerinin kabul ettiği araç adı: harf, rakam, _ ve -; en çok 64 karakter."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:64] or "arac"
