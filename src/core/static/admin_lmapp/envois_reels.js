// Fiche de l'entreprise : confirmation avant de changer « envois réels activés » (de vrais textos partent aux clients)
document.addEventListener("DOMContentLoaded", () => {
  const c = document.getElementById("id_envois_actifs");
  if (!c) return;
  c.addEventListener("change", () => {
    const q = c.checked
      ? "Allumer les envois réels? De vrais textos et courriels partiront aux clients de cette entreprise."
      : "Éteindre les envois réels? Plus rien ne partira aux clients (les messages resteront « Préparé »).";
    if (!confirm(q)) c.checked = !c.checked;
  });
});
