# Mise en service — Illyadera automatique

Le dépôt est déjà installé. Ne pas réimporter une ancienne archive ni réinstaller les fonds. L'ensemble des producteurs, audits et diagnostics fonctionne automatiquement après fusion ; le déclenchement manuel est facultatif.

## Déploiement
La CI « Validation hors production » doit réussir avant fusion. Le workflow Buffer d'audit/réconciliation s'exécute automatiquement après modification de son code sur main, puis trois fois par jour. Il lit Buffer sans mutation et réconcilie uniquement les registres GitHub. Les quatre producteurs conservent leurs horaires automatiques. La variable facultative ILLYADERA_PAUSE_PUBLICATION=1 est un arrêt d'urgence, pas une étape obligatoire.

## Incidents
Une panne réseau ou une source incomplète n'autorise pas à inventer un classement. Les contrôles planifiés réessaient automatiquement les opérations sans mutation incertaine. Si une création a une réponse perdue, l'audit reconstitue le reçu lorsqu'un post exact est présent. Sinon, l'édition expire sans renvoi automatique ; les éditions suivantes continuent et les anecdotes peuvent remplir les créneaux libres. Les anomalies restent consignées, sans imposer une validation quotidienne par le propriétaire. Une perte de droits ou une connexion expirée peut exiger une action sur le compte.

## Configuration
Conserver les secrets BUFFER_API_KEY, BUFFER_CHANNEL_ID et éventuellement BUFFER_ORGANIZATION_ID dans GitHub Actions. Ne jamais les copier dans la conversation. Aucun abonnement supplémentaire. Respecter Buffer Free, les runners standards et le budget de facturation GitHub à zéro.

Calendrier Europe/Paris : mardi 18 h Manga ; jeudi 18 h Comics Top 5 ; vendredi 17 h BD ; deuxième dimanche 18 h Comics mensuel ; anecdotes sur les créneaux libres. Aucun report au troisième dimanche.
