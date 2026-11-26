# Audit technique — 26 novembre 2026

Base examinée : 8fdfbfd4bd75779b5a08a385d04803ce10a96ff1. Dépôt agent-instagram-top7 uniquement.

## Constats vérifiés
- Trois workflows appellent un module inexistant (illiyadera_queue). Le journal Comics du run 45811090409 confirme l'erreur.
- La réparation V10 échoue sur trois tests de calendrier (run 45815400018) et prévoit de redémarrer les agents, malgré son intitulé sans publication.
- Les succès BD et manga du jour ont ignoré les étapes de programmation : aucun envoi ne peut être déduit de ces succès.
- Le README ancien décrivait des brouillons manuels alors que la production est automatique.
- public_media contient 186 fichiers totalisant 121 972 059 octets dans l'arbre étudié. Ces médias sont des ressources publiques potentiellement encore nécessaires à Buffer.
- Les scripts manga versionnés sont encore exécutés par le workflow d'audit. Leur suppression aveugle casserait l'audit.

## Changements proposés
Correction des trois appels de module, garde main sur les agents modifiant l'état, verrou commun photothèque/production, absence d'arbitrage Comics sur plan vide, normalisation des tirets BDZoom et sélection des rangs 1 à 7 du snapshot BD. Calendrier provisoire conforme à l'intention documentée V10, déplacement limité aux anecdotes plus lointaines en remplissage, refus d'envoi si lecture globale Buffer échoue. Tests adaptés et validation PR sans secrets. Retrait de l'installateur V10 à usage unique et du duplicata de dépendances.

## Points à valider avant fusion
- La suite complète doit être verte ; aucune exécution locale complète n'a été possible dans l'environnement d'audit.
- Vérifier les créneaux, la capacité et les reçus dans Buffer avant toute reprise de programmation réelle.
- Vérifier les anciens scénarios de reprise d'anecdotes : les tests historiques peuvent présupposer l'ancienne politique de calendrier.
- La suppression d'une anecdote et la création du Top sont deux opérations distinctes ; risque de perte de créneau en cas d'échec intermédiaire. Préférer à terme une stratégie durable avec journal d'intention et réconciliation, sans réessais aveugles.
- Les médias publics et reçus sont volontairement préservés. Un nettoyage doit d'abord établir les URLs encore utilisées, y compris les contenus programmés. Ne pas réécrire l'historique Git.
- Les anciens modules encore importés ou testés ne sont pas supprimés sans preuve de non-usage.
- Les guides historiques MISE_EN_SERVICE et GUIDE_GITHUB_DEBUTANT peuvent contenir des procédures devenues obsolètes ; les consulter comme archives, non comme procédure de déploiement.
- Vérifier les droits de réutilisation des visuels et les licences avant publication.

## Validation du premier commit et enrichissement éditorial

La CI a exécuté 298 tests : 296 réussis, 2 échecs de priorité des mises à jour d'anecdotes. Le budget de préparation réserve maintenant les réparations des publications existantes. Le coût zéro est formalisé, la découverte éditoriale séparée de la banque validée, six récits originaux sourcés sont ajoutés avec pistes de visuels à vérifier, et le rapprochement des titres manga est renforcé. La validation du nouveau commit et la disponibilité des images restent à contrôler.

## Troisième intervention : sécurité et preuves

Deuxième CI : 300 tests réussis sur 301. Correction du titre de BD identifié par un sous-titre exact délimité. Contrôle des médias publics avant l'arbitrage Manga/Comics ; pas d'arbitrage pour une édition déjà reçue. Plafond Free strict, relecture de la queue avant suppression, refus de modifier un Top manga/comics inconnu sans reçu correspondant. Les légendes indiquent le périmètre des palmarès sans nommer les sources commerciales. Déduplication des faits par empreinte et trois récits supplémentaires documentés ; audit des médias sans suppression. Les scripts historiques restent présents tant que leur dépendance n'est pas réfutée. Les suppressions d'anecdotes et créations Buffer ne sont pas transactionnelles ; risque résiduel en cas de panne après arbitrage. Ne pas fusionner sans CI verte.

## Quatrième intervention : calendrier

CI du troisième commit réussie. Centralisation des créneaux, des marges et du fuseau. Suppression du report automatique du Comics mensuel au troisième dimanche (décision : respecter le deuxième dimanche strictement). Validation des nouvelles anecdotes contre leur date et heure, tri chronologique des arbitrages Comics, vérification du créneau arbitré lors des envois de production. Le calendrier historique BD reste en compatibilité ; la production utilise la marge commune de 45 min. La CI du nouveau commit reste à vérifier. Aucun appel Buffer réalisé.

## Cinquième intervention : ordre et réutilisation

CI du calendrier : 312 tests réussis. Blocage des éditions antérieures à un reçu plus récent, séparation des cadences Comics, traitement Comics chronologique et arbitrage immédiatement avant chaque envoi, arrêt des arbitrages suivants en cas d'échec. Réutilisation possible d'une anecdote libérée si son carrousel est intact, son fait admissible et son créneau encore libre. Les reçus locaux ne constituent pas une lecture live de Buffer. La mise à jour du registre après un arrêt brutal du runner reste un risque non transactionnel. La CI du nouveau commit doit être vérifiée avant fusion.
