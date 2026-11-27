"""Annulation unique de la story indépendante du 27 novembre; aucune création."""
import json,datetime as dt,subprocess
from pathlib import Path
from anecdotes_auto.buffer import Buffer,parse
ROOT=Path(__file__).resolve().parent
RECEIPT=ROOT/'stories_state'/'2026-11-27.json'
ID='6b08e45070e2a88e2ceaf39f'
TEXT='📲 STORY ILLYADERA — 2026-11-27 — TOP 7 BD'
DUE='2026-11-27T19:00:00.000Z'
QUERY="""query CleanupStory($organizationId: OrganizationId!, $channelId: ChannelId!) {
 posts(first: 80,input:{organizationId:$organizationId,filter:{channelIds:[$channelId],status:[scheduled]}}) {
 pageInfo {hasNextPage} edges {node {id text dueAt status channelId metadata {... on InstagramPostMetadata {type}}}}
 }
}"""
def lookup(buf):
    a=buf.call(QUERY,{'organizationId':buf.organization(),'channelId':buf.channel_id}).get('posts')
    if not isinstance(a,dict) or (a.get('pageInfo') or {}).get('hasNextPage') is not False:raise RuntimeError('Lecture incomplète')
    return [p for e in a['edges'] if (p:=e['node']).get('id')==ID]
def save(r,state):
    r['etat']=state;r['confirmation_annulation_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    RECEIPT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    rel=RECEIPT.relative_to(ROOT).as_posix()
    def git(*args):subprocess.run(['git',*args],cwd=ROOT,check=True,timeout=60)
    git('add','--',rel);git('commit','-m','Annulation story indépendante sur demande','--',rel);git('push','origin','HEAD:main')
def main():
    r=json.loads(RECEIPT.read_text(encoding='utf8'))
    if r['id_buffer']!=ID or r['text']!=TEXT or parse(r['due'])!=parse(DUE):raise RuntimeError('Reçu inattendu')
    b=Buffer();posts=lookup(b)
    if not posts:
        if r['etat']=='ANNULEE':print('STORY_ANNULEE_VERIFIEE');return
        if parse(DUE)<=dt.datetime.now(dt.timezone.utc):raise RuntimeError('Story possiblement déjà publiée, aucune suppression')
        save(r,'ABSENTE_DE_LA_FILE');print('STORY_ABSENTE_FILE');return
    if len(posts)!=1:raise RuntimeError('Identité ambiguë')
    p=posts[0]
    if p.get('status')!='scheduled' or p.get('channelId')!=b.channel_id or p.get('text') not in ('',TEXT) or parse(p['dueAt'])!=parse(DUE) or (p.get('metadata') or {}).get('type')!='story':raise RuntimeError('Story non identifiée')
    if lookup(b)!=posts:raise RuntimeError('Story modifiée')
    save(r,'ANNULATION_EN_COURS')
    b.delete_own(ID)
    if lookup(b):raise RuntimeError('Annulation non confirmée')
    save(r,'ANNULEE');print('STORY_ANNULEE_VERIFIEE',ID)
if __name__=='__main__':main()
