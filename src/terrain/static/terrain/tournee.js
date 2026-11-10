// Tournée hors ligne (PRD F10). Chaque tape « Fait » ou « Sauté » est d'abord gardée
// dans le cellulaire (localStorage), affichée tout de suite, puis envoyée au serveur.
// Sans réseau, la file attend et part d'elle-même au retour du signal, avec l'heure
// réelle de chaque tape. Le serveur répond par les passages acceptés, retirés de la file.
document.addEventListener("alpine:init", () => {
  Alpine.data("tournee", (donnees) => ({
    ...donnees,
    choisiId: donnees.choisi,
    file: [],
    horsLigne: !navigator.onLine,
    envoiEnCours: false,
    note: "",
    message: "",
    menuSaute: false,
    gps: false,
    gpsEtat: "",
    surveillance: null,
    dernierEnvoi: null,
    photoEnvoi: false,

    get cleFile() { return "lmapp-tournee-" + this.operation.id; },

    init() {
      try { this.file = JSON.parse(localStorage.getItem(this.cleFile) || "[]"); } catch (e) { this.file = []; }
      // Page rechargée (ou ouverte hors ligne depuis le cache) : réappliquer ce qui attend encore
      for (const item of this.file) this.appliquer(item, true);
      window.addEventListener("online", () => { this.horsLigne = false; this.envoyer(); });
      window.addEventListener("offline", () => { this.horsLigne = true; });
      setInterval(() => this.envoyer(), 30000);
      this.envoyer();
      if (localStorage.getItem("lmapp-gps") === "1" && this.avis_proximite) this.activerGps();
      this.garderEcranAllume();
    },

    // Téléphone sur le support : l'écran reste allumé pendant l'opération (Wake Lock; relâché par le
    // système quand la page passe en arrière-plan, repris au retour)
    async garderEcranAllume() {
      if (!("wakeLock" in navigator)) return;
      const demander = async () => { try { await navigator.wakeLock.request("screen"); } catch (e) { /* refusé : tant pis */ } };
      await demander();
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") demander(); });
    },

    // G1 : position pendant que l'écran est ouvert (l'iPhone ne permet pas plus en arrière-plan)
    activerGps() {
      if (!("geolocation" in navigator)) { this.gpsEtat = "Ce téléphone ne donne pas sa position."; return; }
      this.gps = true; this.gpsEtat = "Recherche de la position…";
      localStorage.setItem("lmapp-gps", "1");
      this.surveillance = navigator.geolocation.watchPosition(
        (pos) => this.nouvellePosition(pos),
        (err) => { this.gpsEtat = err.code === 1 ? "Position refusée : la permettre dans Réglages, Safari, Position." : "Position introuvable pour l'instant."; },
        { enableHighAccuracy: true, maximumAge: 15000, timeout: 30000 });
    },
    arreterGps() {
      if (this.surveillance !== null) navigator.geolocation.clearWatch(this.surveillance);
      this.surveillance = null; this.gps = false; this.gpsEtat = "";
      localStorage.setItem("lmapp-gps", "0");
    },
    distanceM(a, b) {
      const r = 6371000, rad = Math.PI / 180;
      const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
      const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
      return 2 * r * Math.asin(Math.sqrt(h));
    },
    async nouvellePosition(pos) {
      const ici = { lat: pos.coords.latitude, lon: pos.coords.longitude, precision: Math.round(pos.coords.accuracy), t: Date.now() };
      this.gpsEtat = "Position active (précision " + ici.precision + " m).";
      const d = this.dernierEnvoi;
      // Au plus une fois par 30 secondes, ou tout de suite après 150 m de route
      if (d && Date.now() - d.t < 30000 && this.distanceM(d, ici) < 150) return;
      this.dernierEnvoi = ici;
      try {
        const r = await fetch(this.position, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": this.jetonCsrf() },
          body: JSON.stringify({ operation: this.operation.id, lat: ici.lat, lon: ici.lon, precision: ici.precision }),
        });
        if (r.ok) {
          const rep = await r.json();
          this.nb_avis = rep.nb_avis;
          if (rep.avis) this.message = rep.avis + (rep.avis > 1 ? " avis de proximité préparés." : " avis de proximité préparé.");
        }
      } catch (e) { /* hors ligne : la prochaine position partira au retour du réseau */ }
    },

    get courant() {
      return this.arrets.find((a) => a.id === this.choisiId) || this.arrets.find((a) => !a.passage) || null;
    },
    get faits() { return this.arrets.filter((a) => a.passage && a.passage.statut === "fait").length; },
    get sautes() { return this.arrets.filter((a) => a.passage && a.passage.statut === "saute").length; },
    get progression() { return this.arrets.length ? Math.round(100 * (this.faits + this.sautes) / this.arrets.length) : 0; },
    get enAttente() { return this.file.length; },

    choisir(id) {
      this.choisiId = id; this.menuSaute = false; this.note = "";
      this.$nextTick(() => document.getElementById("arret").scrollIntoView({ behavior: "smooth" }));
    },

    appliquer(item, attente) {
      const a = this.arrets.find((x) => x.id === item.adresse);
      if (!a) return;
      const heure = new Date(item.quand);
      a.passage = {
        statut: item.statut, raison: item.raison,
        raison_texte: (this.raisons.find((r) => r[0] === item.raison) || ["", ""])[1],
        heure: heure.toTimeString().slice(0, 5), note: item.note, attente: attente,
      };
    },

    marquer(statut, raison) {
      const a = this.courant;
      if (!a) return;
      const item = {
        cle: Date.now() + "-" + Math.random().toString(36).slice(2, 8),
        operation: this.operation.id, adresse: a.id, statut: statut, raison: raison || "",
        note: this.note.trim(), quand: new Date().toISOString(),
      };
      // Une correction du même arrêt remplace la tape pas encore envoyée
      this.file = this.file.filter((x) => x.adresse !== a.id).concat([item]);
      this.sauver();
      this.appliquer(item, true);
      this.message = a.client + " : " + (statut === "fait" ? "fait." : "sauté.");
      this.choisiId = null; this.menuSaute = false; this.note = "";
      window.scrollTo({ top: 0, behavior: "smooth" });
      this.envoyer();
    },

    sauver() { localStorage.setItem(this.cleFile, JSON.stringify(this.file)); },

    // Photo du passage (F7) : réduite, heure et position du moment, envoyée tout de suite.
    // Pas de file hors ligne pour les photos (trop lourdes pour le cellulaire) : sans réseau, on le dit.
    async photo(ev) {
      const a = this.courant, fichier = ev.target.files[0];
      ev.target.value = "";
      if (!a || !fichier || this.photoEnvoi) return;
      this.photoEnvoi = true;
      const quand = new Date().toISOString();
      const [reduite, pos] = await Promise.all([window.reduirePhoto(fichier), window.positionRapide()]);
      const d = new FormData();
      d.append("adresse", a.id); d.append("quand", quand);
      d.append("photo", reduite || fichier, reduite ? "passage.jpg" : fichier.name);
      if (pos) { d.append("lat", pos.lat); d.append("lng", pos.lng); d.append("precision", pos.precision); }
      try {
        const r = await fetch(this.photo_url, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": this.jetonCsrf() }, body: d });
        const rep = await r.json();
        if (!r.ok) throw new Error(rep.erreur || "HTTP " + r.status);
        a.photos = rep.photos;
        this.message = a.client + " : photo gardée" + (pos ? "." : " (sans position).");
      } catch (e) {
        alert(navigator.onLine ? "Photo pas enregistrée : " + e.message : "Pas de réseau : la photo n'est pas partie. La reprendre plus tard.");
      } finally {
        this.photoEnvoi = false;
      }
    },

    jetonCsrf() {
      const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
      return m ? decodeURIComponent(m[1]) : "";
    },

    async envoyer() {
      if (this.envoiEnCours || !this.file.length) return;
      this.envoiEnCours = true;
      const lot = this.file.slice();
      try {
        const r = await fetch(this.synchro, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": this.jetonCsrf() },
          body: JSON.stringify({ passages: lot }),
        });
        if (r.status === 403 || r.redirected) { this.message = "Session expirée : se reconnecter (les passages restent en attente)."; return; }
        if (!r.ok) throw new Error("HTTP " + r.status);
        const rep = await r.json();
        const faites = new Set(rep.acceptes.map((x) => x.cle).concat(rep.refuses));
        for (const x of rep.acceptes) {
          const a = this.arrets.find((y) => y.id === x.adresse);
          // Seulement si aucune nouvelle tape n'attend pour cet arrêt
          if (a && !this.file.some((f) => f.adresse === x.adresse && !faites.has(f.cle))) a.passage = x.passage;
        }
        if (rep.refuses.length) this.message = rep.refuses.length + " passage(s) refusé(s) par le serveur (opération terminée ou arrêt retiré).";
        this.file = this.file.filter((x) => !faites.has(x.cle));
        this.sauver();
        this.horsLigne = false;
      } catch (e) {
        this.horsLigne = true;  // pas de réseau : on réessaie au retour du signal et toutes les 30 secondes
      } finally {
        this.envoiEnCours = false;
      }
    },
  }));
});
