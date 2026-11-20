# GitHub pour débutant — installation de l'agent Top 7

**But immédiat : déposer le projet sur GitHub et faire un premier test sans connecter Instagram ni Buffer.** Aucun mot de passe ou clé API ne doit être communiqué dans une conversation ou déposé dans les fichiers du projet.

## 1. Créer le dépôt

1. Ouvre https://github.com/new et connecte-toi à ton compte.
2. Dans **Repository name**, écris `agent-instagram-top7` (ou un nom similaire sans espaces).
3. Choisis ton compte personnel dans **Owner**.
4. Dans **Visibility**, choisis **Public** **uniquement si tu acceptes que le code, les trois fonds fournis et, plus tard, les images des brouillons soient visibles**. Ce montage utilise des URL publiques pour Buffer. Si tu préfères une installation privée, arrête-toi ici : il faudra définir un hébergement public séparé des images.
5. Ne coche ni **Add a README file**, ni **Add .gitignore**, ni **Choose a license** : ils sont déjà présents dans notre projet ou inutilement ajoutés.
6. Clique sur **Create repository**.

## 2. Télécharger et importer le programme

1. Télécharge le fichier `agent_instagram_top7_v6.zip` fourni dans ChatGPT.
2. Sur ton ordinateur, **décompresse** le fichier ZIP ; il ne faut pas envoyer simplement le ZIP sur GitHub.
3. Ouvre le dossier extrait `agent_instagram_top7_v6`.
4. Vérifie qu'il contient les fichiers `agent.py`, `visual_top7.py`, `requirements.txt` et les dossiers `assets`, `sources`, `templates`, `tests`, ainsi que **`.github`**, un dossier normalement masqué.
5. Pour afficher les éléments masqués : **Windows** → Explorateur de fichiers → Affichage → Afficher → Éléments masqués ; **Mac** → Finder → `Cmd + Maj + .`.
6. Dans le dépôt GitHub vide, clique sur le lien **uploading an existing file**. Si le dépôt est déjà rempli, passe par **Add file → Upload files**.
7. Sélectionne **le contenu du dossier** extrait (pas le dossier parent, sinon le code sera enfoui dans un sous-dossier) et glisse-dépose les fichiers et dossiers sur GitHub. Le dossier `.github` doit faire partie de la sélection.
8. En bas de la page, saisis `Installation initiale de l'agent Top 7` dans **Commit message**, puis clique sur le bouton de validation (**Commit changes** ou **Propose changes**, selon l'écran).
9. Sur la page principale du dépôt, vérifie que tu vois `agent.py` directement, et que le chemin **`.github/workflows/hebdomadaire.yml`** existe.

## 3. Premier test sans Buffer

1. Clique sur l'onglet **Actions** de ton dépôt. Si GitHub propose d'activer les workflows, lis l'avertissement et active-les seulement si le dépôt correspond bien à ce projet.
2. Dans la colonne de gauche, sélectionne **Agent Top 7 - brouillons Instagram uniquement**.
3. Clique sur **Run workflow**, choisis la branche `main`, puis confirme avec **Run workflow**.
4. Clique sur l'exécution qui apparaît. Le résultat sera **vert** si l'exécution réussit, **rouge** si une étape a échoué.
5. Ouvre le détail des étapes pour lire les erreurs éventuelles. En cas de réussite, récupère l'archive **`dossiers-a-valider`** dans la section **Artifacts**.
6. **Aucun secret Buffer n'ayant été défini à cette étape, aucun brouillon externe ne devrait être créé.** Ce premier test vérifie l'exécution de l'agent dans GitHub, pas la publication finale.

**Attention :** les collecteurs qui lisent des sites publics et récupèrent les couvertures n'ont pas été validés en conditions réelles. Une exécution verte peut seulement produire un rapport signalant des données manquantes ; cela ne signifie pas que les trois classements sont prêts.

## 4. Après le premier test

Reviens dans ChatGPT avec **l'URL publique du dépôt**, et précise si le premier lancement apparaît en vert ou en rouge. Ne partage ni mot de passe, ni jeton GitHub, ni clé Buffer.

On passera ensuite à : vérification des collecteurs réels ; connexion du compte Buffer gratuit ; récupération de l'identifiant du canal Instagram ; configuration des secrets **`BUFFER_API_KEY`** et **`BUFFER_CHANNEL_ID`** dans **Settings → Secrets and variables → Actions** ; test du dépôt d'un brouillon ; activation de la routine hebdomadaire après validation.

## Notes

- Le moteur graphique produit **8 pages** dans l'ordre 7 → 1 puis récapitulatif, avec `TOP` et le rang dans le rond et un bandeau `TOP DES VENTES` avec la période des ventes sur chacune.
- Toute future programmation ou publication Instagram requiert la validation explicite du propriétaire. Le workflow fourni ne demande que la création de **brouillons Buffer**, jamais une publication.
- GitHub Actions est gratuit avec les machines standard sur les dépôts publics, selon les conditions officielles actuelles. L'API Buffer est annoncée disponible sur le plan Free, avec limites.

Sources : https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository ; https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository ; https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
