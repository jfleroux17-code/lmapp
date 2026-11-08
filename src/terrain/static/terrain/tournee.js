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

    get cleFile() { return "lmapp-tournee-" + this.operation.id; },

    init() {
      try { this.file = JSON.parse(localStorage.getItem(this.cleFile) || "[]"); } catch (e) { this.file = []; }
      // Page rechargée (ou ouverte hors ligne depuis le cache) : réappliquer ce qui attend encore
      for (const item of this.file) this.appliquer(item, true);
      window.addEventListener("online", () => { this.horsLigne = false; this.envoyer(); });
      window.addEventListener("offline", () => { this.horsLigne = true; });
      setInterval(() => this.envoyer(), 30000);
      this.envoyer();
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
