// Service worker de LMAPP (PRD F10) : l'app s'ouvre même sans réseau.
//  - /static/ : fichiers à nom unique (empreinte), gardés en cache sans limite de temps;
//  - pages : le réseau d'abord; sans réseau ou si le serveur répond une erreur (5xx, ex. redémarrage), la dernière
//    copie gardée (tournée, fiches, accueil), sinon une page qui réessaie toute seule (jamais d'écran blanc);
//  - jamais de cache pour les POST, la connexion, l'administration ni les PDF.
const VERSION = "{{ version }}";
const CACHE_STATIQUE = "lmapp-statique-" + VERSION;
const CACHE_PAGES = "lmapp-pages";
const A_PRECHARGER = {{ prechargement|safe }};
const PAGES_GARDEES = [/^\/$/, /^\/tournee\/$/, /^\/tournee\/collecter\/$/, /^\/clients\/\d+\/$/, /^\/comptes\/$/, /^\/factures\/$/];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_STATIQUE).then((c) => c.addAll(A_PRECHARGER)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((cles) => Promise.all(
    cles.filter((k) => k.startsWith("lmapp-statique-") && k !== CACHE_STATIQUE).map((k) => caches.delete(k))
  )).then(() => self.clients.claim()));
});

self.addEventListener("message", (e) => {
  if (e.data === "deconnexion") e.waitUntil(caches.delete(CACHE_PAGES));  // rien de personnel ne reste
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(req).then((r) => r || fetch(req).then((rep) => {
      if (rep.ok) { const copie = rep.clone(); caches.open(CACHE_STATIQUE).then((c) => c.put(req, copie)); }
      return rep;
    })));
    return;
  }
  if (req.mode !== "navigate") return;
  const gardee = PAGES_GARDEES.some((m) => m.test(url.pathname));
  // Serveur injoignable ou en erreur (redémarrage pendant une mise à jour : 502 de Caddy) : jamais d'écran blanc.
  // Page gardée : la dernière copie; sinon une page qui réessaie toute seule.
  const secours = () => (gardee ? caches.match(url.pathname) : Promise.resolve(null)).then((r) => r || attente(gardee));
  e.respondWith(fetch(req).then((rep) => {
    if (rep.status >= 500) return secours();
    // Seulement les vraies pages (pas une redirection vers la connexion)
    if (gardee && rep.ok && !rep.redirected) { const copie = rep.clone(); caches.open(CACHE_PAGES).then((c) => c.put(url.pathname, copie)); }
    return rep;
  }).catch(() => (gardee ? caches.match(url.pathname).then((r) => r || caches.match("/tournee/")) : Promise.resolve(null))
    .then((r) => r || attente(gardee))));
});

function attente(gardee) {
  return new Response(
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>" +
    "<body style='background:#000000;color:#f5f7fa;font:20px system-ui;padding:2em'>" +
    "<h1 style='font-size:28px'>Un instant</h1><p>Le serveur ne répond pas pour le moment (mise à jour ou réseau). " +
    "La page se recharge toute seule dans quelques secondes.</p>" +
    (gardee ? "" : "<p style='color:#9ca3af'>La tournée reste disponible si elle a été ouverte une fois sur ce téléphone.</p>") +
    "<button onclick='location.reload()' style='margin-top:1em;width:100%;min-height:56px;border:0;border-radius:16px;background:#f5c400;color:#000;font:600 20px system-ui'>Réessayer</button>" +
    "<script>setTimeout(function () { location.reload(); }, 8000);</script>",
    { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

// Notifications (E8) : un client a écrit, un virement Interac est arrivé
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { corps: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.titre || "Le Déneigeur", {
    body: d.corps || "", data: { url: d.url || "/" }, icon: "/static/icones/icone-192.png", badge: "/static/icones/icone-192.png",
  }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((fenetres) => {
    for (const f of fenetres) { if ("focus" in f) { f.navigate(url); return f.focus(); } }
    return clients.openWindow(url);
  }));
});
