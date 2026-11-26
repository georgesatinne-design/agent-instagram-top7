"""Banque éditoriale, validation stricte et sélection sans réutilisation."""
from __future__ import annotations
import hashlib,json,re,unicodedata
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent
ROOT_REPO=ROOT.parent
STATE=ROOT_REPO/'anecdotes_state'

def read(path,default=None):
    p=Path(path)
    return json.loads(p.read_text(encoding='utf8')) if p.is_file() else default

def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

CONFIG=read(ROOT/'config.json',{})
SOURCES=read(ROOT/'sources_autorisees.json',{})
DOMAINS={x['domaine'] for x in SOURCES['sources_primaires']}

def valid_url(url):
    try:
        p=urlparse(str(url))
        return (p.scheme=='https' and p.hostname in DOMAINS and not p.username and not p.password
                and p.port in (None,443) and len(url)<600)
    except (ValueError,TypeError):return False

def normalized(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s).lower()) if not unicodedata.combining(c))

def valid_fact(a):
    if not isinstance(a,dict):return False
    mandatory=('id','hook','fait','contexte','detail','url_source','preuve_courte','theme')
    if not all(isinstance(a.get(k),str) and a[k].strip() for k in mandatory):return False
    if not re.fullmatch(r'[a-z0-9-]{6,100}',a['id']):return False
    if not valid_url(a['url_source']):return False
    if any(len(a[k])>270 for k in ('fait','contexte','detail')):return False
    if len(a['hook'])>95 or len(a['preuve_courte'])>400:return False
    if a.get('type_preuve') not in ('SOURCE_PRIMAIRE_OFFICIELLE','METADONNEES_EDITEUR_OFFICIEL','SOURCE_INSTITUTIONNELLE_CORROBOREE'):return False
    if a.get('type_preuve')=='SOURCE_INSTITUTIONNELLE_CORROBOREE':
        meta=a.get('preuve_structuree') or {}
        if not isinstance(meta,dict) or meta.get('propriete') not in ('P138','P144'):return False
        if not all(re.fullmatch(r'Q[1-9]\d*',str(meta.get(k,''))) for k in ('item','target','creator')):return False
        if not re.fullmatch(r'[0-9a-f]{64}',str(meta.get('empreinte_assertions',''))):return False
    return True

def bank():
    data=(read(ROOT/'banque_initiale.json',{}) or {}).get('faits',[])
    discovered=(read(STATE/'decouvertes.json',{}) or {}).get('faits',[])
    out={}
    for a in [*discovered,*data]:
        if valid_fact(a):out[a['id']]=a
    return sorted(out.values(),key=lambda x:x['id'])

def topic(a):
    # Aucune source ne devient publique; groupe éditorial pour la diversité.
    s=a['id']
    return a.get('topic') or s.split('-')[0]

def fingerprint(a):
    raw=normalized(a['fait'])+'|'+normalized(a['contexte'])
    return hashlib.sha256(raw.encode()).hexdigest()[:18]

def select(bank_items,used_facts,used_topics,today,*,exclude_ids=()):
    """Choix déterministe, privilégie les faits jamais publiés, puis diversité."""
    from datetime import date
    day=date.fromisoformat(str(today))
    allowed=[]
    for a in bank_items:
        if a['id'] in exclude_ids or a['id'] in used_facts:continue
        hist=used_topics.get(topic(a))
        age=(day-date.fromisoformat(hist)).days if hist else 10**5
        if age<CONFIG.get('intervalle_sujet_jours',5):continue
        allowed.append((age,a))
    if not allowed:return None
    # Priorité au sujet le moins récent; une rotation stable évite la répétition.
    allowed.sort(key=lambda x:(-x[0],hashlib.sha256((str(day)+x[1]['id']).encode()).hexdigest()))
    return allowed[0][1]
