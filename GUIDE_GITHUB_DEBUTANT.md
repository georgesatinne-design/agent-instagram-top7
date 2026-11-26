# Guide GitHub — dépôt Illyadera existant

Ce dépôt est déjà installé et connecté à GitHub Actions. Les anciennes consignes d'import d'un ZIP V6 et de création manuelle de brouillons sont obsolètes.

- Onglet **Pull requests** : examiner les changements avant fusion.
- Onglet **Actions** : consulter « Validation hors production » et ses résultats.
- Après fusion, « Buffer - audit et réconciliation automatiques » contrôle la file sans mutation Buffer, sans action manuelle obligatoire.
- Settings → Secrets and variables → Actions : conserver les secrets Buffer existants, ne jamais les copier dans ChatGPT. Les variables non secrètes sont distinctes des secrets.
- Pour mettre temporairement les agents producteurs en pause, utiliser la variable `ILLYADERA_PAUSE_PUBLICATION=1` (après installation de cette version). Les posts déjà programmés dans Buffer restent programmés.
- Ne pas supprimer les reçus, médias publics ou historiques pour corriger une erreur.

Voir [MISE_EN_SERVICE.md](MISE_EN_SERVICE.md), [README.md](README.md) et [POLITIQUE_COUT_ZERO.md](POLITIQUE_COUT_ZERO.md). Aucun nouveau compte payant nécessaire.
