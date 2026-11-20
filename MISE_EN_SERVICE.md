# Mise en service — agent Instagram Top 7 v6

## Déjà fait : tu n’as plus de fonds à envoyer

Les trois fonds sont déjà installés : **BD violet**, **manga noir et blanc**, **comics rouge**. Les originaux sont archivés sans modification. Le carrousel de chaque catégorie est de huit pages, rangs 7 à 1, puis récapitulatif. Chaque page affiche « TOP DES VENTES » et la période des ventes, y compris le récapitulatif. Le rond jaune indique « TOP » et le rang. Les écarts de rang sont affichés en vert (↑) ou rouge (↓) sur chaque page et à côté des titres de la dernière page. Voir l’aperçu `apercus/apercu_manga_comics_v6.jpg` pour valider les couleurs du bandeau et de la pastille.

## Actions à effectuer sur tes comptes

### 1. Créer / préparer un dépôt GitHub

- Créer un compte sur https://github.com si besoin.
- Créer un dépôt pour ce projet. Le montage actuel avec Buffer exige un **dépôt public** pour les URL des huit images ; tu dois accepter que les médias de brouillon soient publiquement accessibles par lien.
- Dézipper `agent_instagram_top7_v6.zip` et importer le **contenu** (dont le dossier caché `.github`) **à la racine du dépôt**. Ne pas créer involontairement un niveau de dossier supplémentaire.
- Dans Settings → Actions → General → Workflow permissions, autoriser `Read and write permissions` au workflow. Attention, cette autorisation lui donne la possibilité d’écrire des fichiers dans le dépôt.

### 2. Préparer Buffer et Instagram

- Créer ou utiliser un compte gratuit sur https://buffer.com, puis connecter le bon canal Instagram.
- Générer la clé API dans Buffer (si ce droit est bien proposé à ton compte) et récupérer l’ID du canal Instagram avec `buffer_setup.py`.
- Dans GitHub → Settings → Secrets and variables → Actions, créer deux secrets : `BUFFER_API_KEY` et `BUFFER_CHANNEL_ID`. **Ne jamais coller de clé API ou de mot de passe dans ChatGPT ou dans le dépôt.**

### 3. Test réel, AVANT d’activer la routine

- Aller dans GitHub → Actions → « Agent Top 7 - brouillons Instagram uniquement » → « Run workflow ».
- Vérifier l’artefact « dossiers-a-valider » : données sourcées, dates, huit PNG dans l’ordre, correctes couvertures, récapitulatif, légende, évolutions, traces d’erreur.
- Si un Top 7 national manque, si une source change ou si une couverture n’est pas vérifiable, l’agent refuse le brouillon incomplet : c’est normal et doit être corrigé avant d’affirmer qu’il fonctionne en autonomie.
- Vérifier qu’un **brouillon**, pas un post programmé ni publié, apparaît dans Buffer. Contrôler huit images, légende et absence de doublon. N’approuver la charte manga/comics qu’après lecture des aperçus.

### 4. Utilisation une fois validé

- Automatique : le vendredi à **17 h, heure de Paris** (déclenchement GitHub susceptible de retard).
- À la demande : GitHub → Actions → « Run workflow ».
- Résultats : archive téléchargeable dans GitHub Actions + brouillons des posts complets dans Buffer si les contrôles passent. **Les fichiers ne sont pas encore livrés automatiquement dans cette conversation ChatGPT.**
- Tu valides et programmes la publication Instagram dans Buffer pour le jour choisi. Le système ne programme ni ne publie sans toi.

## À savoir

- Le projet est **testé localement**, mais pas déployé dans tes comptes : je ne peux pas prétendre qu’il tourne déjà chaque semaine.
- Les données de ventes et couvertures doivent venir de sites accessibles publiquement ; un classement d’enseigne ne doit pas être présenté comme national.
- L’envoi via API Buffer, les autorisations GitHub et le fonctionnement exact du canal Instagram doivent être vérifiés lors du test réel. Le budget visé reste **0 € supplémentaire**, mais vérifie les restrictions de tes offres gratuites avant toute activation.
