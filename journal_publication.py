"""Journal de reprise des libérations Buffer, sans service externe supplémentaire.

Sur les workflows de production, un point de reprise est publié dans GitHub
AVANT toute suppression. Si le push échoue, la suppression n'a pas lieu.
Le code ne lance aucune commande git dans les tests ni hors production.
"""
from __future__ import annotations
import datetime as dt
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent
REGISTRY=ROOT/'anecdotes_state'/'programmes.json'
TOP_INTENTS=ROOT/'anecdotes_state'/'intentions_tops.json'

def checkpoint(path):
    if os.environ.get('ILLYADERA_DURABLE_JOURNAL')!='1':return
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_REF')!='refs/heads/main':
        raise RuntimeError('Journal durable interdit hors de main')
    path=Path(path).resolve()
    if path not in (REGISTRY.resolve(),TOP_INTENTS.resolve()):
        raise RuntimeError('Le journal ne peut enregistrer que les fichiers de reprise autorisés')
    relative=path.relative_to(ROOT).as_posix()
    def git(*args):
        return subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True,text=True,timeout=60)
    git('add','--',relative)
    if git('status','--porcelain','--',relative).stdout.strip():
        git('-c','user.name=github-actions[bot]','-c','user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit','--only','-m','Journal Illyadera avant arbitrage Buffer','--',relative)
    # Même si le commit existe déjà localement, confirmer sa persistance distante.
    git('push','origin','HEAD:main')

def reconcile_intents(registry,posts,now):
    """Uniquement depuis une lecture complète et réussie de la file.

    Absence après échéance != preuve d'une suppression. Aucun nouvel envoi
    n'est autorisé pour une intention ancienne ou un post modifié manuellement.
    """
    from calendrier_editorial import parse_due
    byid={p['id']:p for p in posts}
    outcomes=[]
    for date,rec in registry.items():
        if not isinstance(rec,dict) or rec.get('etat')!='LIBERATION_EN_COURS':continue
        intent=rec.get('intention_liberation') or {}
        identity=intent.get('id_buffer')
        try:
            due=parse_due(intent['due_at'])
            if not identity or not intent.get('priorite') or identity!=rec.get('id_buffer'):
                raise ValueError('Intention incomplète')
            post=byid.get(identity)
            if due<=now:
                rec['etat']='LIBERATION_A_VERIFIER'
            elif post is None:
                rec['etat']='LIBERE_POUR_'+intent['priorite']
                rec['ancien_id_buffer']=identity
            elif (post.get('status')=='scheduled' and post.get('text','').strip()==rec.get('texte_public','').strip()
                  and parse_due(post['dueAt'])==due):
                rec['etat']='PROGRAMME'
            else:
                rec['etat']='LIBERATION_A_VERIFIER'
        except (KeyError,ValueError,TypeError,AttributeError):
            rec['etat']='LIBERATION_A_VERIFIER'
        rec['reprise_liberation_utc']=now.isoformat()
        outcomes.append({'date':date,'etat':rec['etat']})
    return outcomes
