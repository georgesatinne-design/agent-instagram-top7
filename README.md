# Illyadera — agent Instagram BD, mangas et comics

Le projet collecte des classements de ventes et des anecdotes sourcées, fabrique des carrousels Instagram et programme les contenus éligibles via Buffer. Les publications programmées peuvent être publiées automatiquement par Buffer. Aucun classement ni couverture manquante ne doit être inventé.

## Production

| Contenu | Calendrier Europe/Paris | Entrée |
|---|---|---|
| BD Top 7 | Vendredi 17 h | surveillance_bd.py puis agent.py |
| Manga Top 7 | Mardi 18 h | manga_pipeline_auto.py |
| Comics Top 5 hebdomadaire | Jeudi 18 h | comics_pipeline_periodique.py |
| Comics Top 7 mensuel | Deuxième dimanche du mois suivant, 18 h | comics_pipeline_periodique.py |
| Anecdotes BD | 18 h, vendredi 17 h ; créneaux libres provisoires | anecdotes_auto.run |

Le calendrier de collecte GitHub Actions est distinct des heures de publication. Les agents partagent une file Buffer ; une anecdote appartenant à l'agent peut être déplacée pour un Top vérifié. Les publications manuelles ne doivent jamais être supprimées. Les reçus et le registre persistants participent à la prévention des doublons.

Les workflows de production opèrent uniquement sur main. La validation des pull requests ne reçoit pas de secrets Buffer et ne lance pas les workflows de production. Ne pas lancer les anciennes procédures de réparation.

## Contrôles locaux

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python agent.py --fichier donnees/demo_bd_2026.json --sortie sorties/maquette_bd
```

Les données de démonstration ne sont pas publiables. Les fonds et chartes d'origine restent dans assets, anecdotes_assets et templates. Les trois fonds et leur provenance sont conservés.

## Organisation

- Sources et couverture : sources/, illyadera_covers.py, manga_sources_hebdo.py, comics_sources_periodiques.py.
- Visuels : visual_top7.py, comics_visual_periodique.py, anecdotes_auto/visuels.py.
- Livraison : buffer_client.py, manga_buffer_auto.py, comics_deployer_periodique.py, comics_buffer_periodique.py, anecdotes_auto/buffer.py et illyadera_queue.py.
- Etat persistant : *_receipts/, *_history/, anecdotes_state/.
- Média public : public_media/ (URLs consommées par Buffer, ne pas supprimer sans contrôler les références actives).
- Audit manga : audit_manga_sources.py, verifier_manga.py et modules versionnés ; encore appelés par le workflow d'audit.

Un workflow vert ne prouve pas une publication : vérifier les rapports, les reçus et le statut Buffer. Le dépôt est public et les images mises en ligne sont accessibles publiquement, même avant publication Instagram. Les secrets doivent rester dans GitHub Actions, jamais dans les fichiers.

Voir [AUDIT_TECHNIQUE.md](AUDIT_TECHNIQUE.md) pour les limites et les décisions de nettoyage.

## Coût zéro et ligne éditoriale

Voir [POLITIQUE_COUT_ZERO.md](POLITIQUE_COUT_ZERO.md). Aucune dépendance payante ; les pistes éditoriales sont séparées des faits validés. Les métadonnées de fiches commerciales ne sont pas publiées comme anecdotes.

## Contrôle des médias

`python audit_medias.py` inventorie les doublons exacts et le volume public sans effacer un fichier. Les URLs utilisées par Buffer doivent être vérifiées avant toute purge. Les Top manga/comics sont contrôlés avant toute libération de capacité ; les légendes précisent la portée non exhaustive ou par enseigne lorsque nécessaire.

## Calendrier centralisé

Les créneaux de production sont définis dans `calendrier_publication.json` (section `calendrier_editorial`) et interprétés par `calendrier_editorial.py`. Les Tops sont programmés avec une marge de 45 min ; les anecdotes avec 30 min. Le mensuel ne migre pas au troisième dimanche. Un créneau arbitré est conservé jusqu'à l'envoi ou l'envoi échoue sans déplacement silencieux. Les anciennes fonctions de calendrier restent compatibles avec les tests historiques.
