"""Sohbetlerin JSON dosyaları olarak kaydedilmesi."""

import json
import time
import uuid
from dataclasses import asdict, dataclass, field

from .config import CHATS_DIR


@dataclass
class Conversation:
    provider: str  # "ollama", "claude" ya da "api:<bağlantı id>"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Yeni sohbet"
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    folder: str = "Genel"  # kenar çubuğundaki klasör
    agent_id: str = ""  # yardımcı ajanla açılan sohbetlerde ajan profili
    work_dir: str = ""  # sohbetin iş klasörü (boşsa eski sohbet: çalışma klasörünün kendisi)
    messages: list = field(default_factory=list)  # sağlayıcının kendi mesaj biçiminde

    @property
    def path(self):
        return CHATS_DIR / f"{self.id}.json"

    def save(self) -> None:
        if not self.messages:
            return
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        self.updated = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


def load_all() -> list[Conversation]:
    convs = []
    for path in CHATS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            convs.append(Conversation(**data))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(convs, key=lambda c: c.updated, reverse=True)
