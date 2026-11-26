#!/usr/bin/env python3
"""Réparation atomique V10 du dépôt Illyadera. Aucune requête Buffer.

Exécuté dans une branche de travail GitHub Actions. Ne modifie les sources
que si les ancres attendues sont présentes, puis les tests doivent réussir
avant toute tentative de commit.
"""
from __future__ import annotations
import argparse
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent


def transform(path: str, changes: list[tuple[str, str]], *, must_contain=()) -> bool:
    dest = ROOT / path
    if not dest.is_file():
        raise RuntimeError(f"Fichier attendu introuvable: {path}")
    original = dest.read_text(encoding="utf-8")
    result = original
    for old, new in changes:
        if old == new:
            raise RuntimeError('Remplacement vide')
        if new in result:
            continue  # idempotence, même si la nouvelle forme contient l'ancienne
        elif old in result:
            if result.count(old) != 1:
                raise RuntimeError(f"Ancre non unique dans {path}: {old[:90]!r}")
            result = result.replace(old, new, 1)
        else:
            raise RuntimeError(f"Version inattendue de {path}: {old[:100]!r}")
    for marker in must_contain:
        if marker not in result:
            raise RuntimeError(f"Contrôle perdu dans {path}: {marker}")
    if dest.suffix == '.py':
        ast.parse(result, filename=str(dest))
    if original != result:
        dest.write_text(result, encoding="utf-8")
        print('MODIFIÉ', path)
        return True
    print('DÉJÀ CONFORME', path)
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true', help='Exécuter les changements sécurisés')
    args = p.parse_args()
    if not args.apply:
        p.error('Cette réparation exige --apply. Elle ne publie rien sur Buffer.')

    # Correction de faute de frappe: le module réel est illyadera_queue.py.
    for path in ('.github/workflows/hebdomadaire.yml',
                 '.github/workflows/manga_top7_collecte.yml',
                 '.github/workflows/comics_top7_auto.yml'):
        transform(path, [("python -m illiyadera_queue before-top", "python -m illyadera_queue before-top")],
                  must_contain=("python -m illyadera_queue before-top",))

    # Tant qu'aucun Top Comics n'est validé, le workflow ne doit pas préempter
    # une anecdote ni créer une erreur réseau artificielle.
    transform('.github/workflows/comics_top7_auto.yml', [(
        "          python -m illyadera_queue before-top --kind COMICS\n",
        """          python - <<'PY_CHECK'
          import json
          from pathlib import Path
          p=Path('sorties/comics_periodique/PLAN_BUFFER.json')
          plan=json.loads(p.read_text(encoding='utf8')) if p.is_file() else []
          if not isinstance(plan,list):raise SystemExit('Plan Buffer Comics corrompu')
          with open('comics_nombres_top.txt','w',encoding='utf8') as f:f.write(str(len(plan)))
          print('Tops Comics réellement prêts :',len(plan))
          PY_CHECK
          if [ "$(cat comics_nombres_top.txt)" -gt 0 ]; then
            python -m illyadera_queue before-top --kind COMICS
          else
            echo 'Aucun Top Comics certifié : aucune suppression de post Buffer.'
          fi
""")])

    # Les créneaux Buffer libérés ne sont pas observables en temps réel par
    # GitHub Actions : recontrôler régulièrement, sans toucher aux Tops.
    transform('.github/workflows/anecdotes_bd_auto.yml', [(
        """    - cron: '37 8 * * *'
      timezone: 'Europe/Paris'
    - cron: '47 15,16 * * *'
    # Rechargement rapide apres la publication habituelle des tops (17h/18h)
    - cron: '17 17,18 * * *'
      timezone: 'Europe/Paris'
""",
        """    # Contrôle toutes les heures en journée, puis refill lors du prochain
    # contrôle GitHub Actions : Buffer ne transmet pas ici d'évènement direct.
    - cron: '37 8-22 * * *'
      timezone: 'Europe/Paris'
""")])

    # Le tableau BDZoom emploie des tirets demi-cadratins « –1 » : ils
    # étaient ignorés par le parseur et lus à tort comme noms d'albums.
    # C'est l'origine la plus probable du journal « Albums non uniques ».
    transform('sources/collecte.py', [(
        "    s=norm(s).strip(' ()')\n    if 'nouveau'",
        "    s=norm(s).strip(' ()').replace('−','-').replace('–','-').replace('—','-')\n    if 'nouveau'"
    ),(
        "has_variation=bool(re.fullmatch(r'[+\\-−]\\s*\\d+|=|nouveau|retour|stable|idem',m))",
        "has_variation=bool(re.fullmatch(r'[+\\-−–—]\\s*\\d+|=|nouveau|retour|stable|idem',m))"
    )])

    # BDZoom propose parfois plus de sept rangs. La génération d'un Top 7
    # doit vérifier EXACTEMENT les sept premiers, pas les rangs annexes.
    # Rangs 1..7 ET titres distincts restent une obligation stricte.
    transform('agent.py', [(
        "        try:\n            count=verifier(entry)\n",
        """        try:
            if verified_snapshot and cat == 'BD':
                all_rows = sorted(entry.get('titres', []), key=lambda b: b.get('rang', 999))
                top_sept = all_rows[:7]
                if [b.get('rang') for b in top_sept] != list(range(1, 8)):
                    raise ValueError('Top BD: les sept premiers rangs vérifiés sont indispensables')
                entry = dict(entry)
                entry['titres'] = top_sept
                # Journal technique seulement ; jamais affiché sur Instagram.
                log.append('BD: rangs 1 à 7 conservés (rangs annexes non utilisés).')
                log.append('BD: titres contrôlés = ' + ' | '.join(b.get('titre', '') for b in top_sept))
            count=verifier(entry)
""")], must_contain=("count=verifier(entry)",))

    # Un poste Anecdote authentique peut être programmé EN AVANCE sur un jour
    # de Top, avec priorité permanente au Top à sa sortie.
    transform('anecdotes_auto/calendrier.py', [(
        """    if reserved_kind(day) and now < due-dt.timedelta(minutes=CONFIG['repli_top_minutes_avant']):
        return False,'RESERVE_AU_TOP'
    return True, 'REPLI_TOP' if reserved_kind(day) else 'JOUR_LIBRE'
""",
        """    # Programmation provisoire anticipée : une anecdote est remplacée si
    # un Top validé devient disponible (arbitrage par ID, texte et date exacts).
    return True, 'PROVISOIRE_TOP' if reserved_kind(day) else 'JOUR_LIBRE'
""")])

    # Les tests de calendrier doivent documenter la nouvelle règle plutôt que
    # conserver l'ancien refus d'anticiper.
    transform('tests/test_anecdotes_bd_auto.py', [(
        "self.assertEqual(eligible(dt.date(2026,11,24),now,[])[1],'RESERVE_AU_TOP')",
        "self.assertEqual(eligible(dt.date(2026,11,24),now,[]),(True,'PROVISOIRE_TOP'))"
    ),(
        "self.assertEqual(eligible(dt.date(2026,11,24),now,[]),(True,'REPLI_TOP'))",
        "self.assertEqual(eligible(dt.date(2026,11,24),now,[]),(True,'PROVISOIRE_TOP'))"
    )])

    # En cas de file pleine, un nouveau sujet daté plus tôt peut prendre la
    # place d'une anecdote PLUS LOINTAINE, et seulement d'une anecdote à nous.
    # Cela ne doit pas sacrifier un créneau proche pour remplir un créneau tardif.
    transform('illyadera_queue.py', [(
        """    elif len(posts)>=max_posts:
        selected=max(owned,key=lambda x:_dt(x[2]['dueAt'])) if owned else None
""",
        """    elif len(posts)>=max_posts:
        if priority == 'REMPLISSAGE':
            later=[x for x in owned if _dt(x[2]['dueAt']) > due]
            selected=max(later,key=lambda x:_dt(x[2]['dueAt'])) if later else None
            if selected is None:
                return {'action':'AUCUNE_ANECDOTE_PLUS_LOINTAINE','date':target,
                        'file':len(posts)}
        else:
            selected=max(owned,key=lambda x:_dt(x[2]['dueAt'])) if owned else None
""")])

    # Préparer le contenu y compris lorsque la file est pleine : la tentative
    # de réorganisation s'effectue APRÈS validation de toutes les images.
    transform('anecdotes_auto/run.py', [(
        """        if scheduled_count+creations_pretes>=max_count and reserved_kind(day) is None:
            continue
""",
        """        if scheduled_count+creations_pretes>=max_count:
            # Aucun traitement de médias coûteux si rien de plus lointain
            # ne peut libérer sans danger cette date (registre + Buffer).
            posts_live = all_scheduled if 'all_scheduled' in locals() and all_scheduled is not None else []
            can_move = any(
                isinstance(rec,dict) and rec.get('etat')=='PROGRAMME'
                and other_date > key and any(
                    p.get('id')==rec.get('id_buffer') and p.get('status')=='scheduled'
                    and (p.get('text') or '').strip()==(rec.get('texte_public') or '').strip()
                    and is_anecdote(p)
                    for p in posts_live)
                for other_date,rec in registry.items())
            if not can_move:
                continue
""") ,(
        """                if len(live)>=CONFIG['max_posts_programmes_canal']:
                    if reserved_kind(day):
                        from illyadera_queue import free_capacity_for_priority
                        free_capacity_for_priority(rec['due_at'],buffer=buffer,registry=registry,
                            max_posts=CONFIG['max_posts_programmes_canal'],priority='REPLI_TOP')
                    else:
                        results['ignores'].append(key+' : QUEUE_PLEINE (attente prochaine place)')
                        continue
""",
        """                if len(live)>=CONFIG['max_posts_programmes_canal']:
                    from illyadera_queue import free_capacity_for_priority
                    freed=free_capacity_for_priority(rec['due_at'],buffer=buffer,registry=registry,
                        max_posts=CONFIG['max_posts_programmes_canal'],priority='REMPLISSAGE')
                    if freed.get('action') not in ('ANECDOTE_LIBEREE','PLACE_DISPONIBLE'):
                        results['ignores'].append(key+' : QUEUE_PLEINE_SANS_POST_PLUS_LOINTAIN')
                        continue
""")], must_contain=("priority='REMPLISSAGE'",))

    # À la place de quelques contrôles isolés, tester le comportement prévu.
    # Un workflow "vert" ne doit plus être interprété comme "Buffer programmé".
    transform('.github/workflows/hebdomadaire.yml', [(
        "          if not ready:\n              print('::warning title=Top BD différé::'+why)\n",
        """          if not ready:
              from pathlib import Path as _P
              summary=os.environ.get('GITHUB_STEP_SUMMARY')
              if summary:
                  with _P(summary).open('a',encoding='utf8') as out:
                      out.write('## Top BD : NON PROGRAMMÉ\\n\\n'+why+'\\n\\n')
              print('::warning title=Top BD différé::'+why)
""".replace('\\\\n','\\n')
    )])

    # Détecter visiblement l'absence de nouvelle période manga plutôt que
    # d'afficher un trompeur succès de publication.
    transform('.github/workflows/manga_top7_collecte.yml', [(
        """          print('Edition:',edition,'Certificat:',report['statut_ventes'],
                'Couvertures:',report['couvertures'],'/7','Programme:',ready)
""",
        """          print('Edition:',edition,'Certificat:',report['statut_ventes'],
                'Couvertures:',report['couvertures'],'/7','Programme:',ready)
          summary=os.environ.get('GITHUB_STEP_SUMMARY')
          if summary:
              with open(summary,'a',encoding='utf8') as out:
                  out.write(f'## Top manga : {"PRÊT" if ready else "NON PROGRAMMÉ"}\\n\\n'
                            f'Édition : {edition} ; certificat : {report["statut_ventes"]} ; '
                            f'couvertures : {report["couvertures"]}/7.\\n\\n')
""".replace('\\\\n','\\n')
    )])

    transform('.github/workflows/comics_top7_auto.yml', [(
        "          print('Tops Comics réellement prêts :',len(plan))\n",
        """          print('Tops Comics réellement prêts :',len(plan))
          import os
          summary=os.environ.get('GITHUB_STEP_SUMMARY')
          if summary:
              with open(summary,'a',encoding='utf8') as out:
                  out.write(f'## Comics : {len(plan)} classement(s) prêts pour Buffer\\n\\n')
""".replace('\\\\n','\\n')
    )])

    print('Réparation V10 appliquée. À VALIDER par la suite de tests AVANT commit.')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('ABANDON — aucune programmation Buffer :',type(exc).__name__,str(exc),file=sys.stderr)
        raise
