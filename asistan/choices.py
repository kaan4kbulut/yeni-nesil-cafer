"""Asistanın sorusundaki cevap seçeneklerini bulur: sohbette tıklanabilir baloncuk olarak sunulur, kullanıcı yazmak
zorunda kalmaz (gui/chat.py `AssistantBubble.offer_choices`).

Model, soruyu sorup seçenekleri altına madde olarak yazar (agent.py'deki talimat): "Hangi duy?\\n- E14\\n- E27".
Seçenek yazmadığı evet/hayır sorusunda (son satır "… ister misin?") Evet / Hayır sunulur."""

import re

MAX_OPTIONS = 6
MAX_LEN = 90
_ITEM = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)]|[a-fA-F][.)])\s+(.+?)\s*$")
_YES_NO = re.compile(r"\b(mi|mı|mu|mü)(yim|yım|yum|yüm|sin|sın|sun|sün|siniz|sınız|dir|dır)?\s*\?\s*$", re.I)


def _clean(option: str) -> str:
    option = re.sub(r"\*\*|__|`", "", option).strip()
    return option.rstrip(".;,").strip()


def _question_line(lines: list[str]) -> int | None:
    for i in range(len(lines) - 1, -1, -1):
        if re.sub(r"[*_`\s]+$", "", lines[i]).endswith("?"):
            return i
    return None


def parse(text: str) -> list[str]:
    """Son sorunun altındaki seçenekler; soru yoksa ya da seçenek anlaşılmıyorsa boş liste."""
    lines = (text or "").strip().splitlines()
    q = _question_line(lines)
    if q is None:
        return []
    options: list[str] = []
    for line in lines[q + 1:]:
        if not line.strip():
            if options:
                break
            continue
        m = _ITEM.match(line)
        if not m:
            if options:
                break  # listeden sonraki açıklama
            return []  # sorudan sonra düz metin: seçenek listesi değil
        options.append(_clean(m.group(1)))
    if not options:
        last = re.sub(r"[*_`]", "", lines[q]).strip()
        return ["Evet", "Hayır"] if q == len(lines) - 1 and _YES_NO.search(last) else []
    options = [o for o in options if o]
    if not 2 <= len(options) <= MAX_OPTIONS or any(len(o) > MAX_LEN for o in options):
        return []
    return options
