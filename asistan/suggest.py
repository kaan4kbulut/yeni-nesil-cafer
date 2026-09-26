"""Karşılama ekranındaki "birini dene" önerileri.

Her açılışta geniş bir havuzdan rastgele seçilir; ayrıca kullanıcının son sohbetlerinden yerel modelle
kişisel öneriler üretilir (sohbet bittikten sonra arka planda) ve genel karşılamaya karıştırılır.
"""

import hashlib
import json
import random
import re
import time

import httpx

from . import power
from .config import DATA_DIR, Settings

CACHE = DATA_DIR / "oneriler.json"
MIN_INTERVAL = 300  # kişisel önerileri en fazla 5 dakikada bir yeniden üret

POOL = {
    "": [
        ("{folder} klasöründeki dosyaları listele ve kısaca özetle", "dosyalar"),
        ("1'den 100'e kadar asal sayıları Python ile bul", "python"),
        ("Web'de araştır: 12 GB VRAM'e sığan yerel modeller", "web"),
        ("Bu haftanın teknoloji haberlerini kaynaklarıyla özetle", "web"),
        ("Bana günlük bir çalışma planı hazırla ve dosyaya kaydet", "yazı"),
        ("Bilgisayarımın disk kullanımını çıkar, en çok yer kaplayanları göster", "komut"),
        ("İstanbul'da bu hafta sonu hava nasıl olacak?", "web"),
        ("Bir CSV dosyasından grafik çizen Python betiği yaz", "python"),
        ("Linux'ta sistemi hızlandırmak için 5 somut öneri ver", "web"),
        ("Aylık bütçe tablosu için bir şablon oluştur", "dosyalar"),
        ("Ekibe ver: yerel yapay zekâ modellerini karşılaştıran bir rapor hazırlasın", "ekip"),
        ("İngilizce bir metni doğal bir Türkçeye çevir", "yazı"),
        ("Yeni öğrenmek istediğim bir konu için 30 günlük öğrenme planı çıkar", "yazı"),
        ("Klasördeki resimleri incele ve ne olduklarını listele", "görsel"),
        ("Python'da basit bir yapılacaklar listesi uygulaması yaz", "kod"),
    ],
    "kod": [
        ("Çalışma klasöründeki Python dosyalarını incele ve hataları bul", "kod"),
        ("Klasördeki CSV dosyasını okuyup özet istatistik çıkaran bir betik yaz", "python"),
        ("Bir klasörü her gün yedekleyen bir betik yaz", "kod"),
        ("Basit bir web sayfası (HTML + CSS) oluştur", "kod"),
        ("Verilen bir Python kodunu daha okunur hale getir", "kod"),
        ("Komut satırından hava durumu gösteren küçük bir araç yaz", "python"),
        ("Bir projeye birim testleri ekle", "kod"),
    ],
    "arastirmaci": [
        ("12 GB VRAM'e sığan en iyi yerel dil modellerini araştır", "web"),
        ("Linux'ta pil ömrünü uzatmanın yollarını kaynaklarıyla özetle", "web"),
        ("30-40 bin TL arası en iyi dizüstü bilgisayarları karşılaştır", "web"),
        ("Bir konunun artılarını ve eksilerini kaynaklarıyla çıkar", "web"),
        ("Son çıkan açık kaynak yapay zekâ araçlarını listele", "web"),
        ("Bir ürün hakkındaki kullanıcı yorumlarını araştırıp özetle", "web"),
    ],
    "dosya": [
        ("Çalışma klasörünü türlerine göre alt klasörlere düzenle", "dosyalar"),
        ("Klasördeki en büyük 10 dosyayı listele", "dosyalar"),
        ("Aynı içeriğe sahip kopya dosyaları bul", "dosyalar"),
        ("Dosya adlarını tarihe göre yeniden adlandır", "dosyalar"),
        ("Boş klasörleri bul ve listele", "dosyalar"),
    ],
    "gorsel": [
        ("Klasördeki ekran görüntülerini incele ve içlerindeki yazıları çıkar", "görsel"),
        ("Bir fotoğraftaki nesneleri listele", "görsel"),
        ("Taranmış bir belgeyi metne çevir", "görsel"),
        ("Bir grafiğin resmindeki verileri tabloya aktar", "görsel"),
    ],
    "ozet": [
        ("Çalışma klasöründeki metin dosyalarını tek tek özetle", "dosyalar"),
        ("Bir web sayfasının adresini ver, özetleyeyim", "web"),
        ("Uzun bir belgeyi madde madde kısalt", "yazı"),
        ("Bir toplantı notunu yapılacaklar listesine çevir", "yazı"),
    ],
}


def _load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pick(agent_id: str = "", n: int = 3, folder: str = "") -> list[tuple[str, str]]:
    """Karşılamada gösterilecek öneriler: genel sohbette en fazla 2 kişisel + havuzdan rastgele."""
    personal = []
    if not agent_id:
        items = [(s["text"], s.get("tag", "senin için")) for s in _load().get("items", []) if s.get("text")]
        personal = random.sample(items, min(2, len(items)))
    pool = [(t.replace("{folder}", folder or "çalışma"), tag) for t, tag in POOL.get(agent_id) or POOL[""]]
    random.shuffle(pool)
    seen = {t for t, _ in personal}
    return (personal + [p for p in pool if p[0] not in seen])[:n]


def _recent_requests(conversations) -> list[str]:
    """Son sohbetlerdeki kullanıcı istekleri (en yeni önce, ekler ve tekrar istekleri hariç)."""
    out = []
    for conv in sorted(conversations, key=lambda c: c.updated, reverse=True)[:8]:
        for m in reversed(conv.messages):
            content = m.get("content")
            if m.get("role") == "user" and isinstance(content, str) and not content.startswith("↻ "):
                text = content.split("\n\n[Ek")[0].strip()[:200]
                # "merhaba" gibi içeriksiz ve tekrar eden istekler öneriye konu olmasın
                if len(text.split()) >= 4 and text not in out:
                    out.append(text)
            if len(out) >= 12:
                return out
    return out


def stale(conversations) -> bool:
    """Son isteklerden bu yana kişisel öneriler yenilenmeli mi?"""
    requests = _recent_requests(conversations)
    if not requests:
        return False
    data = _load()
    basis = hashlib.sha1("\n".join(requests).encode()).hexdigest()
    return data.get("basis") != basis and time.time() - data.get("time", 0) > MIN_INTERVAL


def _ok(text: str) -> bool:
    """Kısa, Türkçe (Latin alfabesi) bir öneri mi? Yerel modeller bazen başka dile kayar."""
    text = text.strip()
    return 8 <= len(text) <= 110 and not re.search(r"[\u0370-\u03ff\u0400-\u04ff\u0600-\u06ff\u3000-\u9fff\uac00-\ud7af]", text)


def generate(settings: Settings, conversations) -> list[dict]:
    """Yerel modelle kişisel öneriler üretip saklar. Model o an yüklü olanla aynı ayarlarla çağrılır
    (aynı bağlam boyutu), böylece Ollama modeli yeniden yüklemez."""
    requests = _recent_requests(conversations)
    if not requests:
        return []
    prompt = (
        "Kullanıcının kişisel yapay zekâ asistanına son istekleri (en yenisi başta):\n"
        + "\n".join(f"- {r}" for r in requests)
        + "\n\nKullanıcının sırada muhtemelen yapmak isteyeceği 6 YENİ iş öner: bu isteklerin devamı, ilgili "
        "işler ya da doğal sonraki adımlar. Her biri doğrudan gönderilebilecek kısa bir istek olsun (en fazla "
        "90 karakter), konusunu açıkça ansın (ör. 'Claude Code token tasarrufu planını tabloya dök'; "
        "'Tabloya dök' gibi belirsiz olmasın) ve geçmiş bir isteği tekrar etmesin. Farklı türde işler karıştır. "
        "Her birine şu etiketlerden birini ver: web, python, kod, dosyalar, yazı, görsel, ekip. "
        'Yalnızca JSON döndür: {"suggestions": [{"text": "...", "tag": "..."}]}'
    )
    resp = httpx.post(settings.ollama_url.rstrip("/") + "/api/chat", json={
        # düşünmesiz: düşünen modeller (gemma4, qwen3…) bu kısa iş için 600 token düşünüp ekran kartını ~12 sn meşgul ediyordu
        "model": settings.ollama_model, "stream": False, "think": False, "format": "json", "keep_alive": "30m",
        "messages": [{"role": "system", "content": "Yalnızca Türkçe yaz. Başka dil ya da alfabe kullanma."},
                     {"role": "user", "content": prompt}],
        "options": {"num_ctx": power.num_ctx(settings), "num_predict": 400, "temperature": 0.6},
    }, timeout=httpx.Timeout(180, connect=5))
    resp.raise_for_status()
    try:
        raw = json.loads(resp.json().get("message", {}).get("content", "")).get("suggestions", [])
    except (ValueError, AttributeError):
        raw = []
    items = [{"text": str(s["text"]).strip(), "tag": str(s.get("tag") or "senin için").strip()[:12]}
             for s in raw if isinstance(s, dict) and _ok(str(s.get("text", "")))][:6]
    if items:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({
            "time": time.time(), "items": items,
            "basis": hashlib.sha1("\n".join(requests).encode()).hexdigest(),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    return items
