# Audit de sécurité : application et serveur ld1

Rédigé par Claude Code le 13 novembre 2026, à la demande de Jean-François Leroux. État relevé sur ld1 et dans le code ce jour-là.

## Ce qui est déjà solide

- **Exposition minimale** : seul le 443 est redirigé, le SSH est limité aux IP de SLAPP au routeur, clé seulement, `root` interdit, `fail2ban` actif. ufw refuse tout en entrée. Docker ne publie que le 443 de Caddy.
- **Conteneurs durcis** : système de fichiers en lecture seule, `cap_drop: ALL`, `no-new-privileges`, utilisateur non root, base et app sans accès Internet (seul le worker sort).
- **Application** : connexion exigée partout sauf 10 chemins vérifiés par un test; essais de connexion limités; webhooks Twilio signés; administration à une adresse neutre et réservée aux IP de JF; jetons publics de 192 bits; envois de fichiers limités (10 Mo, type vérifié par les premiers octets); aucun contenu de client affiché sans échappement; CSRF partout sauf les webhooks signés; HSTS, `nosniff`, `X-Frame-Options: DENY`, témoins `Secure`.
- **Double authentification** (Google Authenticator) en place depuis le 13 novembre 2026.
- **Sauvegardes** deux fois par jour, vérifiées, copiées hors site par COVE, test de restauration mensuel; surveillance avec alertes; journal des actions; registre des incidents (Loi 25).
- Mises à jour de sécurité automatiques d'Ubuntu (`unattended-upgrades` actif), AppArmor et seccomp actifs.

## Recommandations, de la plus importante à la moins importante

Légende : **Qui** = Claude Code (CC) ou JF. **Effort** : petit (moins d'une heure), moyen, grand.

### Élevé

1. **Rendre la double authentification obligatoire en prod** (JF, petit). Elle est en place mais au choix (`LMAPP_DOUBLE_AUTH_OBLIGATOIRE=0` dans le `.env` de la prod) pour que tu puisses accompagner Louis. Le jour où tu es avec lui : mettre `1`, puis `docker compose up -d`. Un mot de passe volé ou deviné ne suffira plus.
2. **Double authentification sur tous les comptes externes** (JF, petit). Ce sont les clés du royaume : Cloudflare, le registraire des domaines, GitHub, Twilio, le cPanel, les boîtes `@ledeneigeur.com` si le serveur le permet, COVE, Google (Analytics, Search Console), le Mikrotik et Hyper-V. Un accès à Cloudflare ou au registraire permet de détourner le site, l'app et les courriels.
3. **Réduire le jeton Cloudflare de ld1** (JF, petit). Depuis le 12 novembre, il a tous les droits sur 4 zones. Si ld1 était compromis, l'attaquant pourrait détourner les 4 domaines (site, app, courriel). Caddy n'a besoin que de « Zone, DNS, Modifier » sur `ledeneigeur.com`. Proposition : remettre ce jeton minimal dans `edge/.env`, et créer au besoin un jeton temporaire (expiration d'un jour) pour les changements ponctuels.
4. **DMARC en mode « quarantaine »** (CC avec ton go, petit). Aujourd'hui `p=none` : n'importe qui peut envoyer un faux courriel « de » `@ledeneigeur.com`, par exemple une fausse facture aux clients de Louis avec un autre courriel Interac. Après une semaine de rapports sans surprise : `p=quarantine`, puis `p=reject`.
5. **Sessions plus courtes pour l'administration** (CC, petit). Les sessions durent 90 jours partout, y compris pour ton compte de superutilisateur et `/admin/`. Proposition : 12 heures pour l'administration et les superutilisateurs, 90 jours gardés pour le cellulaire de terrain (gants, tournée). Ajouter « Déconnecter mes autres appareils » dans Plus. **Fait le 13 novembre 2026.**

### Moyen

6. **Politique de sécurité du contenu (CSP) et Permissions-Policy** (CC, moyen). Interdire tout script ou appel qui ne vient pas de ld1 limite les dégâts d'une faille XSS future. Alpine.js demande `'unsafe-eval'`; on garde quand même `default-src 'self'`, `frame-ancestors 'none'`, les tuiles d'OpenStreetMap permises, et `Permissions-Policy` (caméra et position pour l'app seulement, micro refusé). D'abord en mode « rapport seulement » une semaine.
7. **Redémarrage après les mises à jour du noyau** (JF décide, CC configure, petit). Les correctifs du noyau ne s'appliquent qu'au redémarrage, et `Automatic-Reboot` est éteint. Deux options : Livepatch d'Ubuntu Pro (gratuit pour 5 machines, aucun redémarrage), ou redémarrage automatique à 4 h du matin, hors saison de tournée, avec la surveillance en silence.
8. **Mises à jour des images et des dépendances** (CC, moyen, chaque mois). PostgreSQL et PostGIS, Caddy, l'image Python, et les paquets Python (`pip-audit` pour les failles connues). Aujourd'hui, les versions sont fixées et montées à la main : bien, mais il faut le faire régulièrement. Proposition : une vérification mensuelle, avec le test de restauration.
9. **Alertes de sécurité** (CC, petit). Courriel à JF pour : une connexion réussie à l'administration, un pic d'échecs de connexion (attaque), une double authentification activée ou réinitialisée, un nouvel administrateur. Ces gestes sont rares et devraient toujours être connus. **Fait le 13 novembre 2026.**
10. **Mots de passe hachés avec Argon2** (CC, petit). Django utilise PBKDF2, correct. Argon2 résiste mieux au cassage si la base était volée. Les mots de passe sont convertis tout seuls à la connexion suivante. **Fait le 13 novembre 2026.**
11. **Sauvegardes chiffrées** (JF vérifie, CC si besoin, petit). Les `.dump` sur ld1 sont en clair (permissions 600). Vérifier que COVE chiffre bien côté client avec une clé que seul JF a, et faire un vrai test de restauration **depuis COVE** (pas seulement depuis ld1) une fois par année.
12. **Console de COVE sur le port 5000** (JF, petit). Elle écoute sur toutes les interfaces; ufw la bloque, mais une erreur d'ufw l'exposerait. Si COVE le permet, la lier à `127.0.0.1`.

### Faible, à garder en tête

13. **Balayage externe régulier** (CC, petit, chaque mois) : nmap depuis l'extérieur, SSL Labs et Mozilla Observatory sur `louis.ledeneigeur.com`, comparés au balayage de référence de `docs/ouverture-443.md`.
14. **Sortie Internet du worker** : il peut joindre tout Internet. On pourrait la limiter à Twilio, Nominatim, Environnement Canada et le serveur de courriel. Gain réel mais modeste, et plus fragile (adresses qui changent).
15. **auditd** inactif : journal des gestes système (sudo, fichiers sensibles). Utile après un incident; optionnel ici.
16. **Plan de réponse aux incidents écrit** (JF et CC, petit) : qui fait quoi si une fuite ou une intrusion est soupçonnée (couper le 443 au Mikrotik, changer les secrets, aviser la CAI et les personnes, registre). Le registre existe, la marche à suivre pas encore.
17. **Poste de JF** : clé SSH protégée par une phrase de passe, disque chiffré, session verrouillée. Le poste de JF est la porte d'entrée de ld1.
18. **Hôte Hyper-V** : disque de la VM chiffré (BitLocker sur l'hôte), accès à la console Hyper-V réservé à JF.
19. **Site sur le cPanel** : « Always Use HTTPS » et HSTS dans Cloudflare, en-têtes de sécurité sur le cPanel. Le site est statique : risque faible.

## Proposition d'ordre

1. Tout de suite, sans risque : 2, 3, 5, 9, 10 (JF : 2 et 3; CC : 5, 9, 10).
2. Avec Louis : 1.
3. Dans la semaine : 4 (après lecture des rapports DMARC), 6 en mode rapport, 7 (choix de JF), 11, 12.
4. Ensuite, chaque mois : 8 et 13, avec le test de restauration.
