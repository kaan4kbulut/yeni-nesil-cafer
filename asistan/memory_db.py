"""Hafıza deposu: SQLite + anlamsal arama (embedding). learning.py'nin hafıza ve beceri kayıtları burada durur.

Kayıt türleri: tercih · bilgi · ders (kullanıcı hafızası), beceri (işe yarayan yöntem), hata (neyin neden başarısız
olduğu). Her kaydın metninden bir anlam vektörü çıkarılır (Ollama, `nomic-embed-text`); arama bu vektörlerle
yapılır, böylece "rapor" araması "Excel özet tablosu"nu da bulur. Embedding modeli yoksa ya da Ollama kapalıysa
kelime köküne dayalı eski arama kullanılır; vektörü eksik kayıtlar model gelince aramada tamamlanır.

Numpy gerekmez (programın kendi Python'unda yok): vektörler float32 olarak saklanır, kosinüs düz Python'la.
"""

import json
import math
import sqlite3
import threading
import time
import uuid
from array import array
from pathlib import Path

import httpx

from .config import DATA_DIR

DB_FILE = DATA_DIR / "hafiza.db"
EMBED_MODEL = "nomic-embed-text"
EMBED_URL = "http://localhost:11434"
# nomic-embed-text görev önekleri ister: sorgu ve belge farklı kodlanır
_PREFIX = {"query": "search_query: ", "document": "search_document: "}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_embed_ok: tuple[float, bool] | None = None  # (zaman, model var mı) — her aramada Ollama'ya sorulmasın


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_FILE), check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL, updated REAL NOT NULL, vec BLOB, vec_model TEXT)""")
        _conn.execute("CREATE INDEX IF NOT EXISTS items_kind ON items(kind)")
        _conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        # eşitleme (Aşama 6): silinen kayıtlar da karşı tarafa gitsin diye iz bırakır
        _conn.execute("CREATE TABLE IF NOT EXISTS deleted (id TEXT PRIMARY KEY, time REAL NOT NULL)")
        _conn.commit()
    return _conn


def reset_for_tests(path: Path) -> None:
    """Testler: başka bir veritabanı dosyası kullan."""
    global _conn, DB_FILE, _embed_ok
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, DB_FILE, _embed_ok = None, path, None


# ---------------------------------------------------------------- embedding

def embedding_available(url: str = EMBED_URL) -> bool:
    global _embed_ok
    now = time.time()
    if _embed_ok and now - _embed_ok[0] < 60:
        return _embed_ok[1]
    try:
        names = [m.get("name", "") for m in httpx.get(url + "/api/tags", timeout=3).json().get("models", [])]
        ok = any(n.split(":")[0] == EMBED_MODEL for n in names)
    except Exception:
        ok = False
    _embed_ok = (now, ok)
    return ok


def embed(texts: list[str], task: str = "document", url: str = EMBED_URL) -> list[list[float]] | None:
    """Metinlerin anlam vektörleri; model yoksa None (arama kelimeye döner)."""
    if not texts or not embedding_available(url):
        return None
    try:
        resp = httpx.post(url + "/api/embed", json={
            "model": EMBED_MODEL, "input": [_PREFIX[task] + t[:2000] for t in texts], "keep_alive": "10m",
            "truncate": True}, timeout=httpx.Timeout(60, connect=5))
        resp.raise_for_status()
        vecs = resp.json().get("embeddings") or []
    except Exception:
        return None
    return vecs if len(vecs) == len(texts) else None


def _pack(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def _unpack(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return a.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------- kayıtlar

def _row(r: sqlite3.Row) -> dict:
    item = json.loads(r["data"] or "{}")
    item.update(id=r["id"], kind=r["kind"], text=r["text"], created=r["created"], updated=r["updated"])
    return item


def items(kinds: tuple[str, ...] | None = None) -> list[dict]:
    """Kayıtlar, eskiden yeniye."""
    with _lock:
        if kinds:
            q = f"SELECT * FROM items WHERE kind IN ({','.join('?' * len(kinds))}) ORDER BY created"
            rows = _db().execute(q, kinds).fetchall()
        else:
            rows = _db().execute("SELECT * FROM items ORDER BY created").fetchall()
    return [_row(r) for r in rows]


def get(item_id: str) -> dict | None:
    with _lock:
        r = _db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return _row(r) if r else None


def put(kind: str, text: str, data: dict | None = None, item_id: str | None = None,
        created: float | None = None) -> dict:
    """Ekler ya da (item_id verilirse) günceller; vektörü hemen çıkarmayı dener."""
    data = {k: v for k, v in (data or {}).items() if k not in ("id", "kind", "text", "created", "updated")}
    now = time.time()
    vecs = embed([text])
    with _lock:
        db = _db()
        if item_id and db.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
            db.execute("UPDATE items SET kind=?, text=?, data=?, updated=?, vec=?, vec_model=? WHERE id=?",
                       (kind, text, json.dumps(data, ensure_ascii=False), now,
                        _pack(vecs[0]) if vecs else None, EMBED_MODEL if vecs else None, item_id))
        else:
            item_id = item_id or uuid.uuid4().hex[:8]
            db.execute("INSERT INTO items (id, kind, text, data, created, updated, vec, vec_model) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (item_id, kind, text, json.dumps(data, ensure_ascii=False), created or now, now,
                        _pack(vecs[0]) if vecs else None, EMBED_MODEL if vecs else None))
        db.commit()
    return get(item_id)


def update_data(item_id: str, **fields) -> None:
    """Yalnızca ek alanları günceller (sayaçlar gibi); vektör değişmez."""
    with _lock:
        item = get(item_id)
        if item is None:
            return
        data = {k: v for k, v in item.items() if k not in ("id", "kind", "text", "created", "updated")}
        data.update(fields)
        _db().execute("UPDATE items SET data=?, updated=? WHERE id=?",
                      (json.dumps(data, ensure_ascii=False), time.time(), item_id))
        _db().commit()


def delete(item_id: str) -> None:
    with _lock:
        _db().execute("DELETE FROM items WHERE id=?", (item_id,))
        _db().execute("INSERT OR REPLACE INTO deleted (id, time) VALUES (?, ?)", (item_id, time.time()))
        _db().commit()


def trim(kind: str, keep: int) -> None:
    """Bir türden en eski kayıtları siler (en çok `keep` kalır)."""
    with _lock:
        old = _db().execute("SELECT id FROM items WHERE kind=? AND id NOT IN (SELECT id FROM items WHERE kind=? "
                            "ORDER BY updated DESC LIMIT ?)", (kind, kind, keep)).fetchall()
        for r in old:
            delete(r["id"])


# ---------------------------------------------------------------- eşitleme (yerel ↔ bulut, Aşama 6)

def changes_since(since: float) -> dict:
    """Bu zamandan sonra değişen kayıtlar ve silinenler (vektörler gönderilmez; karşı taraf kendisi çıkarır)."""
    with _lock:
        rows = _db().execute("SELECT id, kind, text, data, created, updated FROM items WHERE updated > ?",
                             (since,)).fetchall()
        gone = _db().execute("SELECT id, time FROM deleted WHERE time > ?", (since,)).fetchall()
    return {"items": [dict(r) for r in rows], "deleted": [dict(r) for r in gone]}


def apply_changes(changes: dict) -> int:
    """Karşı taraftan gelen değişiklikleri uygular: aynı kayıtta yenisi kazanır, silme daha yeniyse siler.
    Uygulanan değişiklik sayısını döndürür."""
    n = 0
    with _lock:
        db = _db()
        for d in changes.get("deleted") or []:
            r = db.execute("SELECT updated FROM items WHERE id=?", (d["id"],)).fetchone()
            if r is not None and r["updated"] <= d["time"]:
                db.execute("DELETE FROM items WHERE id=?", (d["id"],))
                n += 1
            db.execute("INSERT OR REPLACE INTO deleted (id, time) VALUES (?, ?)", (d["id"], d["time"]))
        for it in changes.get("items") or []:
            gone = db.execute("SELECT time FROM deleted WHERE id=?", (it["id"],)).fetchone()
            if gone is not None and gone["time"] >= it["updated"]:
                continue  # burada daha sonra silinmiş
            r = db.execute("SELECT updated FROM items WHERE id=?", (it["id"],)).fetchone()
            if r is not None and r["updated"] >= it["updated"]:
                continue  # buradaki daha yeni
            db.execute("INSERT OR REPLACE INTO items (id, kind, text, data, created, updated, vec, vec_model) "
                       "VALUES (?,?,?,?,?,?,NULL,NULL)",
                       (it["id"], it["kind"], it["text"], it.get("data") or "{}", it["created"], it["updated"]))
            db.execute("DELETE FROM deleted WHERE id=?", (it["id"],))
            n += 1
        db.commit()
    return n


def _backfill(limit: int = 64) -> None:
    """Vektörü olmayan kayıtları (model sonradan kuruldu, Ollama kapalıydı) toplu olarak tamamlar."""
    with _lock:
        rows = _db().execute("SELECT id, text FROM items WHERE vec IS NULL OR vec_model != ? LIMIT ?",
                             (EMBED_MODEL, limit)).fetchall()
    if not rows:
        return
    vecs = embed([r["text"] for r in rows])
    if not vecs:
        return
    with _lock:
        _db().executemany("UPDATE items SET vec=?, vec_model=? WHERE id=?",
                          [(_pack(v), EMBED_MODEL, r["id"]) for r, v in zip(rows, vecs)])
        _db().commit()


def search(query: str, kinds: tuple[str, ...], k: int = 5, min_score: float = 0.0,
           keyword_score=None, task: str = "query") -> list[tuple[float, dict]]:
    """En ilgili kayıtlar [(puan, kayıt)], en iyi önce. Vektör varsa kosinüs benzerliği; yoksa keyword_score(sorgu,
    kayıt) (learning.py'nin kelime kökü puanı) kullanılır. task="document": "aynı kayıt mı" karşılaştırması
    (iki belge; aynı bilgi 0.92+, benzer ama farklı iş ~0.78 — nomic-embed-text, 2026-09-25 ölçümü)."""
    if not query.strip():
        return []
    qvec = embed([query], task)
    if qvec:
        _backfill()
    with _lock:
        q = f"SELECT * FROM items WHERE kind IN ({','.join('?' * len(kinds))})"
        rows = _db().execute(q, kinds).fetchall()
    scored = []
    for r in rows:
        if qvec and r["vec"] is not None and r["vec_model"] == EMBED_MODEL:
            score = cosine(qvec[0], _unpack(r["vec"]))
        elif keyword_score is not None:
            score = keyword_score(query, _row(r))
        else:
            continue
        if score >= min_score:
            scored.append((score, _row(r)))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def semantic() -> bool:
    """Arama şu an anlam üzerinden mi (embedding modeli hazır mı)?"""
    return embedding_available()


def meta(key: str, value: str | None = None) -> str | None:
    with _lock:
        if value is not None:
            _db().execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
            _db().commit()
            return value
        r = _db().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None
