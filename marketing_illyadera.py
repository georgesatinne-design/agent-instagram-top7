"""Agent marketing transversal, sans API payante ni mutation Buffer.

Read actual sent-post metrics, compare only mature comparable posts, choose
bounded editorial CTA policies. Never fabricate missing data; never change
calendar, prices, rankings, sources or images on the basis of engagement.
Raw metrics are ephemeral; only aggregate non-sensitive recommendations persist.
"""
from __future__ import annotations
import argparse,datetime as dt,json,math,statistics,re,unicodedata
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'marketing_state'/'strategie.json'
KINDS=('BD','MANGA','COMICS_HEBDO','COMICS_MENSUEL','ACTUS','ANECDOTE')
DEFAULT={'BD':'save','MANGA':'comment','COMICS_HEBDO':'comment','COMICS_MENSUEL':'save','ACTUS':'share','ANECDOTE':'comment'}
CTA={
 'BD':{'save':'Garde ce classement pour ta prochaine visite en librairie.','share':'Partage ce classement avec un lecteur de BD.','comment':'Quel album de ce classement as-tu envie de lire ?'},
 'MANGA':{'save':'Garde ce classement pour ta prochaine lecture.','share':'Partage ce classement avec un fan de manga.','comment':'Quel manga de ce classement recommandes-tu ?'},
 'COMICS_HEBDO':{'save':'Garde cette sélection pour ta prochaine lecture.','share':'Partage ces titres avec un fan de comics.','comment':'Quel comics de ce classement as-tu lu ?'},
 'COMICS_MENSUEL':{'save':'Garde ce classement pour ta prochaine visite en librairie.','share':'Partage ce bilan avec un fan de comics.','comment':'Quel comics de ce mois as-tu préféré ?'},
 'ACTUS':{'save':'Garde ces cinq infos pour retrouver les sources.','share':'Partage cette sélection avec un passionné du 9e art.','comment':'Laquelle de ces cinq actualités te semble la plus marquante ?'},
 'ANECDOTE':{'save':'Garde cette anecdote pour la raconter plus tard.','share':'Partage cette anecdote avec un passionné du 9e art.'},
}
TAGS={'BD':['BandeDessinee','BD','9eArt','LectureBD'],
'MANGA':['Manga','MangaFrance','LectureManga','9eArt'],
'COMICS_HEBDO':['Comics','ComicsFrance','LectureComics','9eArt'],
'COMICS_MENSUEL':['Comics','ComicsFrance','LectureComics','9eArt'],
'ACTUS':['ActualitesBD','BandeDessinee','Manga','Comics','9eArt'],
'ANECDOTE':['BandeDessinee','BD','9eArt','PassionBD']}
QUERY="""query Marketing($org: OrganizationId!, $channel: ChannelId!, $cursor: String) {
 posts(first:50,after:$cursor,input:{organizationId:$org,filter:{status:[sent],channelIds:[$channel]}}){
 edges{node{id text dueAt channelId metadata{... on InstagramPostMetadata{type}} metrics{type name value unit} metricsUpdatedAt}}
 pageInfo{hasNextPage endCursor}
 }}"""
def read_policy():
    try:
        p=json.loads(STATE.read_text(encoding='utf8'))
        age=(dt.date.today()-dt.date.fromisoformat(p['date'])).days
        return p if 0<=age<=14 and p.get('status')=='MESURES_DISPONIBLES' else {}
    except (OSError,ValueError,KeyError,TypeError):return {}
def action(kind,policy=None):
    p=read_policy() if policy is None else policy
    chosen=(p.get('formats',{}).get(kind,{}) or {}).get('cta')
    return chosen if chosen in ('save','share','comment') else DEFAULT[kind]
def cta(kind,question=None,policy=None):
    a=action(kind,policy)
    if a=='comment' and question:return question
    return CTA[kind].get(a,question or 'Tu connaissais cette histoire ?')
def tags(kind,topic=None):
    out=list(TAGS[kind])
    if topic:
        tag=re.sub(r'[^\w]','',str(topic),flags=re.UNICODE)
        if 3<=len(tag)<=28 and tag.lower() not in {x.lower() for x in out}:out=out[:4]+[tag]
    return ' '.join('#'+t for t in out[:5])
def key(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(s).lower()) if not unicodedata.combining(c) and c.isalnum())
def metrics(post):
    aliases={'reach':'reach','accountsreached':'reach','portee':'reach','impressions':'views','views':'views','likes':'likes','likecount':'likes','comments':'comment','commentcount':'comment','shares':'share','sharecount':'share','saves':'save','saved':'save','savecount':'save','savedcount':'save'}
    out={}
    for item in post.get('metrics') or []:
        k=aliases.get(key(item.get('type',''))) or aliases.get(key(item.get('name','')))
        if not k:continue
        try:v=float(item.get('value'))
        except (ValueError,TypeError):continue
        if math.isfinite(v) and v>=0:out[k]=v
    return out
def classify(post):
    from audit_buffer import category
    if (post.get('metadata') or {}).get('type')=='story':return 'STORY'
    return category(post.get('text') or '')
def summarize(posts,now):
    groups=defaultdict(list);seen=set()
    for post in posts:
        if not post.get('id') or post['id'] in seen:continue
        seen.add(post['id'])
        k=classify(post)
        if k not in KINDS:continue
        try:
            date=dt.datetime.fromisoformat(post['dueAt'].replace('Z','+00:00'))
            age=(now-date).total_seconds()/86400
        except (ValueError,TypeError,KeyError):continue
        if not 2<=age<=28:continue
        m=metrics(post)
        if m.get('reach',0)>0:groups[k].append(m)
    formats={}
    for k in KINDS:
        rows=groups[k];counts={};rates={}
        for a in ('save','share','comment'):
            ratios=[m[a]/m['reach'] for m in rows if a in m]
            counts[a]=len(ratios)
            if len(ratios)>=4:rates[a]=statistics.median(ratios)
        default=DEFAULT[k];winner=default
        # require at least 4 matched samples and a meaningful relative uplift;
        # do not infer causality or change timing on a small observational sample.
        if len(rates)==3 and rates.get(default,0)>0:
            best=max(rates,key=rates.get)
            if rates[best]>=1.35*rates[default] and rates[best]-rates[default]>=.002:winner=best
        formats[k]={'cta':winner,'echantillon':len(rows),'preuve':'SIGNAL_OBSERVATIONNEL' if winner!=default else 'REGLE_EDITORIALE',
                    'mesures_comparables':counts}
    return {'date':now.date().isoformat(),'status':'MESURES_DISPONIBLES' if any(groups.values()) else 'AUCUNE_MESURE_EXPLOITABLE','formats':formats,
            'calendrier':'INCHANGE','notes':'Mesures observationnelles; aucun effet causal supposé. Aucun chiffre individuel publié.'}
def collect(buffer):
    cursor=None;out=[]
    for i in range(5):
        r=buffer.call(QUERY,{'org':buffer.organization(),'channel':buffer.channel_id,'cursor':cursor}).get('posts')
        if not isinstance(r,dict) or not isinstance(r.get('edges'),list):raise RuntimeError('Réponse métriques incomplète')
        out.extend(x['node'] for x in r['edges'] if x.get('node',{}).get('channelId')==buffer.channel_id)
        p=r.get('pageInfo') or {}
        if p.get('hasNextPage') is False:return out
        if p.get('hasNextPage') is not True or not p.get('endCursor') or p['endCursor']==cursor:raise RuntimeError('Pagination incomplète')
        cursor=p['endCursor']
    return out
def main():
    from anecdotes_auto.buffer import Buffer
    now=dt.datetime.now(dt.timezone.utc)
    try:result=summarize(collect(Buffer()),now)
    except Exception as exc:
        result=summarize([],now);result['status']='ACCES_METRIQUES_NON_CONFIRME';result['cause']=type(exc).__name__
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');tmp.replace(STATE)
    print('MARKETING',result['status'],'formats',[(k,v['echantillon'],v['cta']) for k,v in result['formats'].items()])
if __name__=='__main__':main()
