// service worker: uygulama kabuğu çevrimdışı açılır; API istekleri hep ağdan (onay ve görev durumu taze kalsın)
const KABUK = "cafer-kabuk-v1";
const DOSYALAR = ["/", "/stil.css", "/uygulama.js", "/manifest.webmanifest", "/simge.svg"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(KABUK).then((c) => c.addAll(DOSYALAR))));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== KABUK).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || !DOSYALAR.includes(url.pathname)) return;
  e.respondWith(caches.match(e.request).then((c) => c || fetch(e.request)));
});
