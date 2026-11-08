# Correspondances de colonnes par logiciel d'origine (PRD Q3)

Un fichier `<logiciel>.json` par logiciel concurrent dont on a reçu un vrai export (Excel ou CSV),
fait par le déneigeur lui-même depuis son compte. Format : l'entête exacte du fichier exporté, et la
colonne du gabarit LMAPP où elle va (`""` pour l'ignorer) :

    {"Nom du client": "nom", "Tél. cellulaire": "cellulaire", "Solde": "solde_du", "Code interne": ""}

Utilisation : `manage.py importer_clients fichier.xlsx --entreprise martin --depuis nom_du_logiciel`
(ou `--correspondance chemin.json`). L'essai à blanc montre où va chaque colonne : le vérifier avant
`--appliquer`. Ne jamais mettre de données de clients dans ces fichiers (entêtes seulement).
