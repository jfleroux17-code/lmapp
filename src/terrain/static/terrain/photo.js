// Réduction d'une photo dans le cellulaire avant l'envoi (A5, F7) : 1600 px au plus, JPEG.
// Pillow n'est pas une dépendance de l'app : c'est le navigateur qui fait le travail.
// Rend un Blob, ou null si le navigateur ne sait pas lire ce format (on envoie alors l'original).
window.reduirePhoto = async function (fichier) {
  try {
    const image = await createImageBitmap(fichier);
    const echelle = Math.min(1, 1600 / Math.max(image.width, image.height));
    const toile = document.createElement("canvas");
    toile.width = Math.round(image.width * echelle);
    toile.height = Math.round(image.height * echelle);
    toile.getContext("2d").drawImage(image, 0, 0, toile.width, toile.height);
    return await new Promise((ok) => toile.toBlob(ok, "image/jpeg", 0.82));
  } catch (e) {
    return null;
  }
};

// Position du moment, si le cellulaire la donne vite (5 secondes au plus); sinon null, la photo part quand même.
window.positionRapide = function () {
  return new Promise((ok) => {
    if (!navigator.geolocation) return ok(null);
    navigator.geolocation.getCurrentPosition(
      (p) => ok({ lat: p.coords.latitude, lng: p.coords.longitude, precision: Math.round(p.coords.accuracy) }),
      () => ok(null), { enableHighAccuracy: true, timeout: 5000, maximumAge: 60000 });
  });
};
