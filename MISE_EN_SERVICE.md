# Mise en service — Illyadera

Le dépôt est déjà installé. Ne pas réimporter une ancienne archive ZIP ni réinstaller les fonds. Le projet est public ; les médias accessibles par URL et les journaux non secrets peuvent être visibles. Aucun service payant supplémentaire.

## Validation avant fusion

1. Vérifier la CI « Validation hors production » sur la pull request : compilation et suite complète, sans accès Buffer.
2. Contrôler le diff et l'état de main. Ne pas écraser les reçus ni le registre existants.
3. Si une pause de production est nécessaire, créer la variable de dépôt Actions `ILLYADERA_PAUSE_PUBLICATION` avec la valeur `1` avant fusion ; elle bloque les quatre workflows producteurs après fusion. Les posts déjà programmés dans Buffer ne sont pas annulés. Par défaut, les agents gardent leur fonctionnement automatique.
4. Après fusion, lancer uniquement « Audit Buffer en lecture seule » depuis main, lire le résultat. Si erreur, conserver la pause et examiner les conflits ; ne pas relancer un workflow producteur pour diagnostiquer.
5. Retirer la variable de pause ou lui donner la valeur `0` une fois l'audit satisfaisant. Ne pas lancer tous les agents simultanément.

## Configuration

Les secrets GitHub Actions `BUFFER_API_KEY`, `BUFFER_CHANNEL_ID` et, si nécessaire, `BUFFER_ORGANIZATION_ID` restent secrets. Ne jamais les envoyer dans une conversation, un fichier ou un log. Utiliser Buffer Free et le runner standard GitHub Actions. Vérifier les plafonds et le budget du compte à zéro. Voir POLITIQUE_COUT_ZERO.md.

## Calendrier

Mardi 18h Manga ; jeudi 18h Comics Top 5 ; vendredi 17h BD ; deuxième dimanche 18h Comics Top 7 du mois précédent ; anecdotes aux créneaux libres. Heure Europe/Paris. Une anecdote peut être provisoire un jour de classement. Pas de report automatique du mensuel au troisième dimanche.

## En cas d'incident

Ne jamais effacer un reçu ou une intention de création pour forcer une relance. Si le journal indique une mutation incertaine, contrôler la queue et les publications passées en lecture seule. La présence d'un post exact à l'identité et au créneau attendus permet une réconciliation ; une absence ne prouve pas que l'opération n'a jamais eu lieu. Conserver les médias jusqu'à contrôle de leurs références. Une CI verte ne garantit ni l'accès aux sources ni la publication Instagram.
