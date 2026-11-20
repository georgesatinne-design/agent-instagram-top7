# Agent Instagram Top 7 — BD, mangas et comics (version 6)

**Version 6 : les trois fonds fournis par l’utilisateur sont intégrés à l’identique.** Aucun fond n’est plus manquant. Ce projet prépare des carrousels et peut tenter de déposer des brouillons dans Buffer, **sans programmer ni publier** sur Instagram.

## Identité visuelle fixée

| Catégorie | Fond original inclus | Bandeau | Texte du bandeau | Pastille rang |
|---|---|---|---|---|
| BD | `assets/fond_bd_original.jpeg` | violet `#5E376E` | jaune `#F7E952` | jaune `#F7E952` |
| Manga | `assets/fond_manga_original.png` | noir `#171717` | blanc `#FFFFFF` | jaune `#F7E952` |
| Comics | `assets/fond_comics_original.png` | rouge `#970017` | blanc cassé `#FFF9F0` | jaune `#FFE45E` |

Les fichiers sources ont été copiés sans modification. Leur empreinte SHA-256 et leurs dimensions originales sont dans `assets/fonds_provenance.json`. Le moteur les adapte au format Instagram **1080 × 1350** par cadrage ; le fond comics fourni est horizontal et sera donc recadré sur la maquette verticale. Les palettes manga et comics sont des **propositions à valider visuellement**, pas un choix explicitement donné par l’utilisateur.

Sur **chaque page**, le bandeau inférieur affiche distinctement **« TOP DES VENTES »**, la **catégorie**, et la **période de ventes vérifiée** (dates de début et de fin si disponibles). Les ronds jaunes comportent **« TOP » et le numéro de rang**.

Même logique pour les trois : **8 pages**, rangs **7 → 6 → 5 → 4 → 3 → 2 → 1**, puis **récapitulatif**. Flèche vers le haut + nombre de places en **vert** (`#13853C`), flèche vers le bas + nombre de places en **rouge** (`#CB2434`), sur chaque page **et à côté de chaque titre du récapitulatif**. Stable `=`, nouvelle entrée `NOUVEAU`, information non vérifiable `—`. Jamais de déplacement inventé.

## Ce qui est testé

- 19 tests locaux automatisés : validation des rangs et dates, 8 pages dans le bon ordre, empreintes exactes des trois fonds, couleurs, évolutions, refus de couvertures manquantes, construction de brouillons Buffer simulés.
- Les aperçus manga/comics figurent dans `apercus/apercu_manga_comics_v5.jpg`. Ce sont des **maquettes fictives filigranées**, sans véritables couvertures et **non publiables**.

## Fonctionnement voulu

1. Vendredi (ou exécution manuelle) : `agent.py` tente de collecter les palmarès publics, en distinguant les catégories et les périmètres. Un Top 7 non vérifiable n’est pas inventé.
2. `visual_top7.py` crée les huit images, la légende et le dossier de contrôle, à partir des couvertures **exactement appariées**. S’il manque une couverture, pas d’envoi chez Buffer.
3. Un workflow GitHub Actions (`.github/workflows/hebdomadaire.yml`) peut héberger les images et déposer un post **dans les brouillons Buffer**, uniquement si les comptes, secrets, données et couvertures sont valides.
4. Le propriétaire vérifie puis programme manuellement dans Buffer pour le jour choisi. **Aucun post automatique sans validation.**

La tâche hebdomadaire ChatGPT, si elle existe, est indépendante de ce workflow GitHub et ne dépose pas d’elle-même les fichiers dans ce chat.

## Installation

Lire **[MISE_EN_SERVICE.md](MISE_EN_SERVICE.md)** pour les actions de mise en service. Pour tester le projet localement :

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python agent.py --fichier donnees/demo_bd_2026.json --sortie sorties/maquette_bd
```

`demo_bd_2026.json` contient des données de démonstration non revalidées ; les images générées avec `--fichier` sont filigranées et ne peuvent pas être envoyées automatiquement à Buffer.

## Ce qui n’est PAS encore prouvé

La collecte réellement exécutée sur les sites publics, le téléchargement des couvertures de chaque catégorie et le dépôt réel d’un brouillon chez Buffer **ne sont pas encore validés en production**. Aucun compte GitHub, Instagram ni Buffer n’a été connecté ou activé ici. Le code seul ne rend pas l’agent autonome : le workflow doit être installé et testé dans le compte de son propriétaire.

Pour ce montage gratuit, les huit visuels des brouillons sont déposés dans un **dépôt GitHub public** afin que Buffer les télécharge : même non publiés sur Instagram, ces fichiers seront visibles par quiconque possède leur URL. Si ce n’est pas acceptable, ne pas connecter Buffer sans concevoir un autre hébergement.

Ressources : https://developers.buffer.com/examples/create-draft-post.html • https://developers.buffer.com/guides/hosting-media.html • https://docs.github.com/actions
