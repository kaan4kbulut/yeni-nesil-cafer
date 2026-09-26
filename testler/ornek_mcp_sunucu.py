"""Testler için en küçük MCP sunucusu (stdio, yalnızca standart kütüphane).

Araçlar: topla (yalnızca okur), not_yaz (değiştirir), hata_ver (her zaman hata döner).
"""

import json
import sys

TOOLS = [
    {"name": "topla", "description": "İki sayıyı toplar.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "not_yaz", "description": "Bir not kaydeder.",
     "inputSchema": {"type": "object", "properties": {"metin": {"type": "string"}}, "required": ["metin"]},
     "annotations": {"destructiveHint": False}},
    {"name": "hata_ver", "description": "Her zaman hata döner.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    out.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        continue  # bildirim
    if method == "initialize":
        print("sunucu başladı (günlük satırı, JSON değil)", file=sys.stderr, flush=True)
        reply(msg_id, {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                       "serverInfo": {"name": "ornek", "version": "1"}})
    elif method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments") or {}
        if name == "topla":
            reply(msg_id, {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]})
        elif name == "not_yaz":
            reply(msg_id, {"content": [{"type": "text", "text": f"kaydedildi: {args['metin']}"}]})
        else:
            reply(msg_id, {"content": [{"type": "text", "text": "bilerek hata"}], "isError": True})
    else:
        reply(msg_id, error={"code": -32601, "message": "yok"})
