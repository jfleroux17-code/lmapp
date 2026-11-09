// Service worker de LMAPP (PRD F10) : l'app s'ouvre même sans réseau.
//  - /static/ : fichiers à nom unique (empreinte), gardés en cache sans limite de temps;
//  - pages : le réseau d'abord; sans réseau, la dernière copie gardée (tournée, fiches, accueil);
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
  if (req.mode === "navigate" && PAGES_GARDEES.some((m) => m.test(url.pathname))) {
    e.respondWith(fetch(req).then((rep) => {
      // Seulement les vraies pages (pas une redirection vers la connexion)
      if (rep.ok && !rep.redirected) { const copie = rep.clone(); caches.open(CACHE_PAGES).then((c) => c.put(url.pathname, copie)); }
      return rep;
    }).catch(() => caches.match(url.pathname).then((r) => r || caches.match("/tournee/")).then((r) => r || new Response(
      "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><body style='background:#000000;color:#f5f7fa;font:18px system-ui;padding:2em'>" +
      "<h1>Hors ligne</h1><p>Cette page n'a pas encore été ouverte sur ce téléphone. La tournée reste disponible si elle a été ouverte une fois.</p>",
      { headers: { "Content-Type": "text/html; charset=utf-8" } }))));
  }
});

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
