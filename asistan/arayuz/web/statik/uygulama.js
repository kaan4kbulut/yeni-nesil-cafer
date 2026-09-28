// PWA istemcisi: sohbet (SSE), görevler, onaylar. Anahtar tarayıcıda (localStorage), her istekte Authorization başlığı.
const $ = (s) => document.querySelector(s);
let anahtar = localStorage.getItem("cafer_anahtar") || "";
let sohbetId = localStorage.getItem("cafer_sohbet") || ("web-" + Date.now());
localStorage.setItem("cafer_sohbet", sohbetId);

function basliklar() { return { "Authorization": "Bearer " + anahtar, "Content-Type": "application/json" }; }
async function api(yol, secenek = {}) {
  const r = await fetch(yol, { ...secenek, headers: { ...basliklar(), ...(secenek.headers || {}) } });
  if (r.status === 401) { anahtar = ""; localStorage.removeItem("cafer_anahtar"); $("#giris").showModal(); throw new Error("anahtar"); }
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.status === 204 ? null : r.json();
}
function durum(m) { $("#durum").textContent = m; }

// sekmeler
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach((x) => x.classList.toggle("secili", x === b));
  document.querySelectorAll(".sekme").forEach((s) => s.classList.toggle("acik", s.id === "sekme-" + b.dataset.sekme));
  if (b.dataset.sekme === "gorevler") gorevleriYukle();
  if (b.dataset.sekme === "onaylar") onaylariYukle();
}));

// giriş
$("#giris form").addEventListener("submit", () => {
  anahtar = $("#anahtar").value.trim();
  localStorage.setItem("cafer_anahtar", anahtar);
  saglik();
});
async function saglik() {
  try {
    const s = await (await fetch("/saglik")).json();
    durum("kademe: " + s.kademe + " · " + s.surum);
    if (!anahtar) $("#giris").showModal(); else await onaylariYukle();
  } catch (e) { durum("sunucuya ulaşılamadı"); }
}

// sohbet (SSE: fetch gövdesi satır satır okunur; EventSource POST yapamaz)
function mesajEkle(sinif, metin) {
  const d = document.createElement("div"); d.className = "mesaj " + sinif; d.textContent = metin;
  $("#mesajlar").appendChild(d); d.scrollIntoView({ block: "end" }); return d;
}
$("#sohbet-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const metin = $("#metin").value.trim(); if (!metin) return;
  $("#metin").value = ""; mesajEkle("kullanici", metin);
  const cevap = mesajEkle("asistan", "");
  try {
    const r = await fetch("/sohbet", { method: "POST", headers: basliklar(), body: JSON.stringify({ metin, sohbet_id: sohbetId }) });
    if (r.status === 401) { $("#giris").showModal(); return; }
    const okuyucu = r.body.getReader(); const dec = new TextDecoder(); let tampon = "";
    for (;;) {
      const { value, done } = await okuyucu.read(); if (done) break;
      tampon += dec.decode(value, { stream: true });
      let i; while ((i = tampon.indexOf("\n\n")) >= 0) {
        const satir = tampon.slice(0, i).trim(); tampon = tampon.slice(i + 2);
        if (!satir.startsWith("data:")) continue;
        const olay = JSON.parse(satir.slice(5));
        if (olay.tur === "metin") cevap.textContent += olay.metin;
        else if (olay.tur === "arac") mesajEkle("arac", "⚙ " + olay.ad);
        else if (olay.tur === "not") mesajEkle("arac", olay.metin);
        else if (olay.tur === "hata") cevap.textContent += "\n[hata] " + olay.metin;
      }
    }
  } catch (err) { cevap.textContent += "\n[bağlantı koptu] " + err.message; }
});
$("#metin").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#sohbet-form").requestSubmit(); } });

// görevler
async function gorevleriYukle() {
  const g = await api("/gorev"); const ul = $("#gorev-listesi"); ul.innerHTML = "";
  for (const t of g.gorevler) {
    const li = document.createElement("li"); li.className = t.durum;
    // K12-A11: görev metni modelden/sunucudan gelir; HTML olarak basılmaz (textContent)
    const durum = document.createElement("span"); durum.className = "durum"; durum.textContent = t.durum;
    li.append(durum, t.istek.slice(0, 80));
    li.addEventListener("click", async () => { const a = await api("/gorev/" + t.gorev_id); $("#gorev-ayrinti").textContent = a.rapor || a.adimlar.map((s) => `${s.durum} ${s.id}. ${s.amac} · ${s.yetenek}`).join("\n"); });
    ul.appendChild(li);
  }
}
$("#gorev-form").addEventListener("submit", async (e) => {
  e.preventDefault(); const istek = $("#gorev-istek").value.trim(); if (!istek) return;
  $("#gorev-istek").value = "";
  await api("/gorev", { method: "POST", body: JSON.stringify({ istek }) });
  setTimeout(gorevleriYukle, 800);
});

// onaylar
async function onaylariYukle() {
  const o = await api("/onaylar"); const ul = $("#onay-listesi"); ul.innerHTML = "";
  $("#onay-sayisi").textContent = o.onaylar.length ? "(" + o.onaylar.length + ")" : "";
  for (const b of o.onaylar) {
    const li = document.createElement("li"); li.className = "bekliyor_onay";
    const ne = document.createElement("b"); ne.textContent = b.ne;  // K12-A11: XSS yok
    const kucuk = document.createElement("small"); kucuk.textContent = b.istek.slice(0, 100);
    li.append(ne, document.createElement("br"), kucuk, document.createElement("br"));
    const evet = document.createElement("button"); evet.textContent = "onayla";
    const hayir = document.createElement("button"); hayir.textContent = "reddet"; hayir.className = "ikincil";
    evet.onclick = () => api("/gorev/" + b.gorev_id + "/onayla", { method: "POST", body: JSON.stringify({ evet: true }) }).then(onaylariYukle);
    hayir.onclick = () => api("/gorev/" + b.gorev_id + "/onayla", { method: "POST", body: JSON.stringify({ evet: false }) }).then(onaylariYukle);
    li.append(evet, " ", hayir); ul.appendChild(li);
  }
}
setInterval(() => { if (anahtar) onaylariYukle().catch(() => {}); }, 30000);

saglik();
