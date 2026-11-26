"""Réconciliation automatique, lecture seule côté Buffer.

Les éditions confirmées exactement reconstruisent un reçu. Une édition non
confirmable après son échéance est classée sans renvoi : les éditions suivantes
continuent et l'agent anecdotes peut occuper les créneaux libres.
"""
import datetime as dt
import json
from pathlib import Path
from collections import Counter
from calendrier_editorial import parse_due,validate_slot
from historique_editions import edition_key
from intentions_tops import fingerprint
from journal_publication import reconcile_intents
from audit_buffer import category,report

def read_json(path):
    return json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}

def save_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    tmp.replace(path)

def reconcile_tops(intents,posts,*,root,now):
    root=Path(root);counts=Counter()
    for edition,intent in intents.items():
        kind,_=edition_key(edition)
        if intent.get('etat')=='EXPIRE_INCERTAIN':continue
        receipt_dir={'BD':'buffer_receipts','MANGA':'manga_buffer_receipts',
                      'COMICS_HEBDO':'comics_buffer_receipts','COMICS_MENSUEL':'comics_buffer_receipts'}[kind]
        path=root/receipt_dir/(edition+'.json')
        prior=read_json(path)
        if prior.get('statut')=='POST_PROGRAMME':
            # Existing authoritative receipt is never rewritten.
            counts['recu_existant']+=1;continue
        due=parse_due(intent['due_at'])
        matches=[p for p in posts if p.get('status')=='scheduled' and category(p.get('text',''))==kind
                 and parse_due(p['dueAt'])==due and fingerprint(p['text'])==intent.get('empreinte_texte')
                 and (not intent.get('id_buffer') or p.get('id')==intent['id_buffer'])]
        if len(matches)==1:
            p=matches[0]
            validate_slot(kind,p['dueAt'],now=now,check_margin=False)
            meta=intent.get('recu') or {}
            rec={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':'RECU_RECONSTRUIT_AUTO',
                 'edition':edition,'id_buffer':p['id'],'status_buffer':'scheduled',
                 'date_programmee_utc':p['dueAt'],'pages':6 if kind=='COMICS_HEBDO' else 8}
            if kind=='BD':
                if meta.get('empreinte_classement'):rec['empreinte_classement']=meta['empreinte_classement']
            elif kind=='MANGA':
                rec['version_contenu']=meta.get('version_contenu','manga_sans_sources_v1')
            else:
                rec.update(cadence=kind.removeprefix('COMICS_'),
                           version_contenu=meta.get('version_contenu','comics_top5_top7_2026_v1'),
                           texte_public=p['text'])
            save_json(path,rec)
            intent.update(etat='CONFIRME',id_buffer=p['id'])
            counts['reconstitues']+=1
        elif len(matches)>1:counts['ambigus']+=1
        elif due<=now:
            intent['etat']='EXPIRE_INCERTAIN'
            counts['expires_sans_renvoi']+=1
        else:counts['en_attente']+=1
    return dict(counts)

def run(*,root=Path('.'),buffer=None,now=None):
    from anecdotes_auto.buffer import Buffer
    root=Path(root);now=now or dt.datetime.now(dt.timezone.utc)
    posts=(buffer if buffer is not None else Buffer()).list_scheduled()
    # Validate all dates and queue shape before touching any state.
    result=report(posts)
    path=root/'anecdotes_state'/'intentions_tops.json'
    intents=read_json(path)
    old=json.dumps(intents,sort_keys=True)
    result['reconciliation_tops']=reconcile_tops(intents,posts,root=root,now=now)
    if json.dumps(intents,sort_keys=True)!=old:save_json(path,intents)
    registry_path=root/'anecdotes_state'/'programmes.json'
    registry=read_json(registry_path)
    repaired=reconcile_intents(registry,posts,now)
    if repaired:save_json(registry_path,registry)
    result['reconciliation_liberations']=len(repaired)
    return result

def main():
    try:result=run()
    except Exception as exc:
        print('Réconciliation non effectuée : '+type(exc).__name__)
        raise SystemExit(1) from None
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
