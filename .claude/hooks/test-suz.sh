#!/bin/sh
# Claude Code PreToolUse (Bash) kancası: test komutlarının çıktısını süzer — token tasarrufu.
# pytest / unittest / python -m pytest ile başlayan komut, çıktısı yalnızca FAIL/ERROR/error:/passed/failed
# satırları (+5 satır bağlam, en çok 80 satır) kalacak biçimde `updatedInput` ile değiştirilir.
# Zaten boruya/yönlendirmeye bağlı komutlara dokunulmaz. Hiçbir durumda komutu engellemez (çıkış 0).
girdi=$(cat)
komut=$(printf '%s' "$girdi" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$komut" ] && exit 0

case "$komut" in
  *"|"*|*">"*) exit 0 ;;   # kullanıcı/Claude zaten süzmüş ya da dosyaya yazıyor
esac

# Baştaki `cd X &&` ve ORTAM=deger öneklerini atlayarak asıl programa bak.
cekirdek=$(printf '%s' "$komut" | sed -E 's/^[[:space:]]*(cd [^&;|]*&&[[:space:]]*)?//; s/^([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*//')
if printf '%s' "$cekirdek" | grep -qE '^(pytest|py\.test|[^[:space:]]*/pytest|[^[:space:]]*python[0-9.]*(\.exe)?[[:space:]]+-m[[:space:]]+(pytest|unittest))([[:space:]]|$)'; then
  yeni="{ $komut; } 2>&1 | grep -A5 -E '(FAIL|ERROR|error:|passed|failed|Ran [0-9]+|^OK)' | head -80"
  jq -cn --arg c "$yeni" '{hookSpecificOutput:{hookEventName:"PreToolUse",updatedInput:{command:$c}}}'
fi
exit 0
