/* Témoins et mesure d'audience (Loi 25) : rien de Google ne se charge avant un « Accepter ».
   Mode Consentement de Google v2 : tout refusé par défaut; Tag Manager chargé seulement après
   l'acceptation (pas de pings sans témoins avant). Choix gardé dans le navigateur (localStorage).
   Lien « Témoins » au bas des pages : rouvre le bandeau pour changer d'idée. */
(function () {
  var GTM = "GTM-TPG648K6";
  var CLE = "ld-consentement";
  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  gtag("consent", "default", {
    ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
    analytics_storage: "denied", functionality_storage: "denied", personalization_storage: "denied",
    security_storage: "granted", wait_for_update: 500
  });

  function lire() { try { return localStorage.getItem(CLE); } catch (e) { return null; } }
  function ecrire(v) { try { localStorage.setItem(CLE, v); } catch (e) {} }

  var charge = false;
  function chargerGTM() {
    if (charge) return;
    charge = true;
    gtag("consent", "update", {
      ad_storage: "granted", ad_user_data: "granted", ad_personalization: "granted",
      analytics_storage: "granted", functionality_storage: "granted", personalization_storage: "granted"
    });
    window.dataLayer.push({ "gtm.start": new Date().getTime(), event: "gtm.js" });
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtm.js?id=" + GTM;
    document.head.appendChild(s);
  }

  function effacerTemoins() {
    var noms = document.cookie.split(";").map(function (c) { return c.split("=")[0].trim(); });
    var domaines = ["", location.hostname, "." + location.hostname.replace(/^www\./, "")];
    noms.forEach(function (n) {
      if (!/^(_ga|_gid|_gat|_gcl|_fbp|_fbc)/.test(n)) return;
      domaines.forEach(function (d) {
        document.cookie = n + "=; Max-Age=0; path=/" + (d ? "; domain=" + d : "");
      });
    });
  }

  function bandeau() {
    if (document.getElementById("temoins")) return;
    var b = document.createElement("div");
    b.id = "temoins";
    b.setAttribute("role", "dialog");
    b.setAttribute("aria-label", "Témoins");
    b.innerHTML =
      '<p>On aimerait mesurer les visites du site (Google Analytics) et l\'effet de nos publicités. ' +
      'Rien n\'est activé sans votre accord. <a href="confidentialite.html#temoins">En savoir plus</a></p>' +
      '<div class="choix"><button type="button" data-choix="refuse">Refuser</button>' +
      '<button type="button" data-choix="accepte">Accepter</button></div>';
    b.addEventListener("click", function (e) {
      var choix = e.target.getAttribute && e.target.getAttribute("data-choix");
      if (!choix) return;
      var avant = lire();
      ecrire(choix);
      b.remove();
      if (choix === "accepte") chargerGTM();
      else if (avant === "accepte") { effacerTemoins(); location.reload(); }
    });
    document.body.appendChild(b);
  }

  if (lire() === "accepte") chargerGTM();

  document.addEventListener("DOMContentLoaded", function () {
    var choix = lire();
    if (choix !== "accepte" && choix !== "refuse") bandeau();
    document.querySelectorAll("[data-temoins]").forEach(function (a) {
      a.addEventListener("click", function (e) { e.preventDefault(); bandeau(); });
    });
  });
})();
