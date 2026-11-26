"""Découverte automatique à partir de relations documentées, pas d'IA facturable.

Wikidata sert UNIQUEMENT d'index de recherche. Une relation n'est promue que
si une page institutionnelle autorisée confirme explicitement les deux noms,
la relation et le créateur. Aucune phrase de la source n'est republiée.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import re
import unicodedata
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests
from .catalogue import STATE, ROOT, read, write, valid_url, valid_fact, normalized

ENDPOINT='https://query.wikidata.org/sparql'
UA='IllyaderaEditorial/1.0 (https://github.com/georgesatinne-design/agent-instagram-top7)'
MAX_FACTS=3
MAX_PAGES=8

QUERY="""SELECT DISTINCT ?item ?itemLabel ?target ?targetLabel ?creator ?creatorLabel ?ref ?prop WHERE {
  {
    ?item wdt:P31 wd:Q1114461; wdt:P170 ?creator; p:P138 ?claim.
    ?claim ps:P138 ?target; prov:wasDerivedFrom/pr:P854 ?ref.
    ?target wdt:P31 wd:Q5.
    BIND("P138" AS ?prop)
  } UNION {
    VALUES ?type { wd:Q1004 wd:Q14406742 }
    ?item wdt:P31 ?type; wdt:P170 ?creator; p:P144 ?claim.
    ?claim ps:P144 ?target; prov:wasDerivedFrom/pr:P854 ?ref.
    BIND("P144" AS ?prop)
  }
  ?creator wdt:P31 wd:Q5.
  FILTER NOT EXISTS { ?claim wikibase:rank wikibase:DeprecatedRank }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
} ORDER BY ?item ?target ?ref ?creator LIMIT 60 OFFSET %d"""

def label(value):
    if not isinstance(value,str):return ''
    value=' '.join(value.split())
    # No instructions, markup, numeric-only IDs or ambiguous short anchors.
    if not 4<=len(value)<=65 or not re.fullmatch(r"[\w\s'’ .,&()!?:\-–]+",value):return ''
    if re.fullmatch(r'Q\d+',value) or not any(c.isalpha() for c in value):return ''
    return value

def entity_id(url):
    m=re.fullmatch(r'https?://www\.wikidata\.org/entity/(Q[1-9]\d*)',url or '')
    return m.group(1) if m else ''

def fold(s):
    return ' '.join(normalized(s).replace('’',"'").split())

def explicit_relation(html,subject,target,creator,prop):
    # Restrict to editorial paragraphs; never treat navigation, scripts,
    # comments, unrelated co-occurrences or lists as a factual assertion.
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','nav','footer','header','aside','form','noscript']):tag.decompose()
    blocks=soup.select('article p, main p')
    if not blocks:blocks=soup.select('p')
    sentences=[]
    for p in blocks:
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ])',p.get_text(' ',strip=True)):
            s=fold(sentence)
            if 12<=len(s)<=450:sentences.append(s)
    a,b,c=map(fold,(subject,target,creator))
    def anchor(x):return r'(?<!\w)'+re.escape(x)+r'(?!\w)'
    # Short exact positive relations only. No inference from approximate mentions.
    verbs={'P138':r"(?:was named after|is named after|takes its name from|tire son nom de|doit son nom a|a ete nomme d'apres)",
           'P144':r"(?:was based on|is based on|is an adaptation of|adapte|est une adaptation de|est inspire de|est inspiree de)"}
    if prop not in verbs:return None
    relation=re.compile(anchor(a)+r'\s+'+verbs[prop]+r'\s+(?:the\s+|le\s+|la\s+)?'+anchor(b))
    # The creator must be explicit, not simply present on the same page.
    creation=re.compile(anchor(a)+r'\s+(?:was created by|was written by|created by|written by|a ete cree par|a ete creee par|est signe par|est signee par)\s+'+anchor(c))
    inverse=re.compile(anchor(c)+r'\s+(?:created|wrote|a cree|a ecrit)\s+'+anchor(a))
    evidence=[s for s in sentences if relation.search(s) and not re.search(r'\b(?:not|never|perhaps|possibly|supposedly|rumor|rumeur|peut-etre|probablement|hypothese)\b',s)]
    creators=[s for s in sentences if creation.search(s) or inverse.search(s)]
    if not evidence or not creators:return None
    return hashlib.sha256((evidence[0]+'|'+creators[0]).encode()).hexdigest()

def fact_from_row(row,html,now):
    def value(k):return (row.get(k) or {}).get('value','')
    subject,target,creator=map(label,(value('itemLabel'),value('targetLabel'),value('creatorLabel')))
    ids=[entity_id(value(k)) for k in ('item','target','creator')]
    url=value('ref');prop=value('prop')
    if not all((subject,target,creator,*ids)) or len(set(ids))!=3 or not valid_url(url):return None
    if len({fold(subject),fold(target),fold(creator)})!=3:return None
    evidence=explicit_relation(html,subject,target,creator,prop)
    if not evidence:return None
    if prop=='P138':
        hook=f"D'où vient le nom de {subject} ?"
        fait=f"Le personnage {subject} tient son nom de {target}."
        contexte=f"Ce personnage a été créé par {creator}."
        detail="Le lien attesté concerne le nom du personnage, et non nécessairement son apparence ou toute sa biographie."
        question="Quel autre nom de personnage t'intrigue ?"
        theme='PERSONNAGES'
    elif prop=='P144':
        hook=f"Et si {subject} venait d'une autre œuvre ?"
        fait=f"« {subject} » est une adaptation de « {target} »."
        contexte=f"Le créateur de cette bande dessinée est {creator}."
        detail="Le récit dessiné a donc une œuvre de départ : les deux versions peuvent être comparées pour retrouver ce qui a changé."
        question="Préfères-tu découvrir une adaptation ou son œuvre d'origine ?"
        theme='COULISSES'
    else:return None
    slug=re.sub(r'[^a-z0-9]+','-',fold(subject)).strip('-')[:38]
    fact={'id':f'archive-{ids[0].lower()}-{prop.lower()}-{ids[1].lower()}',
          'topic':slug or ids[0].lower(),'theme':theme,'hook':hook,'fait':fait,
          'contexte':contexte,'detail':detail,'question':question,
          'transition':'Revenons à l’origine de cette création…','url_source':url,
          'preuve_courte':f'Relation {prop} : {subject} / {target} ; créateur {creator} ; deux assertions explicites dans la source.',
          'type_preuve':'SOURCE_INSTITUTIONNELLE_CORROBOREE',
          'controle_editorial':'RELATION_ET_CREATEUR_CONFIRMES_PAR_ARCHIVE',
          'controle_date_utc':now.isoformat(),'empreinte_page_sha256':hashlib.sha256(html.encode()).hexdigest(),
          'preuve_structuree':{'item':ids[0],'target':ids[1],'creator':ids[2],
                              'propriete':prop,'empreinte_assertions':evidence,
                              'subject_label':subject,'target_label':target,'creator_label':creator}}
    return fact if valid_fact(fact) else None

def scenes_for(fact):
    """Trois recherches distinctes, exclusivement ancrées dans les noms prouvés."""
    meta=fact.get('preuve_structuree') or {}
    a,b,c=map(label,(meta.get('subject_label'),meta.get('target_label'),meta.get('creator_label')))
    if not all((a,b,c)) or fact.get('type_preuve')!='SOURCE_INSTITUTIONNELLE_CORROBOREE':return None
    # Les recherches restent soumises aux contrôles de licence et de pertinence.
    return [(1,'LE PERSONNAGE OU L’ŒUVRE',a+' comic illustration statue',(a,),('comic','manga','bande dessinee','statue','illustration')),
            (3,'LE CRÉATEUR',c+' cartoonist portrait',(c,),('portrait','cartoonist','mangaka','dessinateur','author')),
            (4,'L’ORIGINE DU RÉCIT',b+' '+('portrait' if meta.get('propriete')=='P138' else 'illustration'),(b,),('portrait','illustration','book','livre','photograph'))]

def enrich(*,session=None,now=None,root=None,state=None,fetch_html=None):
    """Au plus une requête SPARQL et huit pages par jour, réserve documentaire bornée."""
    from .decouverte import html_get
    from .storytelling import editorial_eligible
    session=session or requests.Session();now=now or dt.datetime.now(dt.timezone.utc)
    root=ROOT if root is None else root;state=STATE if state is None else state
    fetch_html=fetch_html or html_get
    path=state/'decouvertes.json';cursor_path=state/'decouverte_structuree_rapport.json'
    previous=read(cursor_path,{}) or {}
    if previous.get('jour')==now.date().isoformat():return previous
    old=(read(path,{}) or {}).get('faits',[])
    existing={f['id']:f for f in old if valid_fact(f)}
    seed=(read(root/'banque_initiale.json',{}) or {}).get('faits',[])
    registry=read(state/'programmes.json',{}) or {}
    used={r.get('fact_id') for r in registry.values() if isinstance(r,dict) and r.get('etat') in
          ('PROGRAMME','EN_ATTENTE','EN_ATTENTE_MAJ','EXPIRE_INCERTAIN')}
    unused=sum(editorial_eligible(f) and f['id'] not in used for f in [*seed,*existing.values()])
    offset=max(0,int(previous.get('offset_suivant',0)))%600
    result={'jour':now.date().isoformat(),'nouveaux':0,'pages':0,'offset_suivant':offset,'faits_inutilises':unused}
    # Ne pas stocker de milliers de textes. La recherche reprend sous le seuil.
    if unused>=30 or len(existing)>=250:
        result['statut']='RESERVE_SUFFISANTE';write(cursor_path,result);return result
    try:
        response=session.get(ENDPOINT,params={'query':QUERY%offset,'format':'json'},headers={'User-Agent':UA,'Accept':'application/sparql-results+json'},timeout=22)
        response.raise_for_status()
        rows=response.json()['results']['bindings']
        if not isinstance(rows,list):raise ValueError('Résultat non structuré')
    except (requests.RequestException,ValueError,KeyError,TypeError):
        result['statut']='INDEX_INDISPONIBLE';write(cursor_path,result);return result
    cache={};seen={(fold(f.get('fait','')),fold(f.get('contexte',''))) for f in [*seed,*existing.values()]}
    for row in rows[:60]:
        if result['nouveaux']>=MAX_FACTS:break
        if not isinstance(row,dict):continue
        url=(row.get('ref') or {}).get('value','')
        if not valid_url(url):continue
        if url not in cache:
            if result['pages']>=MAX_PAGES:break
            result['pages']+=1
            try:cache[url]=fetch_html(url,session,12)
            except (requests.RequestException,ValueError,KeyError):cache[url]=''
        if not cache[url]:continue
        fact=fact_from_row(row,cache[url],now)
        if not fact or fact['id'] in existing:continue
        key=(fold(fact['fait']),fold(fact['contexte']))
        if key in seen:continue
        existing[fact['id']]=fact;seen.add(key);result['nouveaux']+=1
    result['offset_suivant']=(offset+60)%600 if len(rows)>=60 else 0
    result['statut']='TERMINE'
    if result['nouveaux']:write(path,{'faits':list(existing.values())})
    write(cursor_path,result)
    return result
