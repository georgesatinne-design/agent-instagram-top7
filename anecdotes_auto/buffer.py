"""Buffer GraphQL: lecture réelle des créneaux, création idempotente, priorité des tops.
Ne supprime que NOS publications anecdote et uniquement si un top occupe la journée.
"""
from __future__ import annotations
import datetime as dt,os,time
from urllib.parse import quote,urlparse
import requests
from PIL import Image

ENDPOINT='https://api.buffer.com'
ORG_QUERY='query Organizations { account { organizations { id } } }'
DAY_QUERY='''query Posts($organizationId: OrganizationId!, $channelId: ChannelId!, $slotStart: DateTime!, $slotEnd: DateTime!) {
  posts(first: 40, input: {organizationId: $organizationId, filter: { status: [scheduled], channelIds: [$channelId], dueAt: {start: $slotStart, end: $slotEnd}}}) {
    pageInfo { hasNextPage }
    edges { node { id text dueAt status channelId } }
  }
}'''
CREATE='''mutation CreatePost($input: CreatePostInput!) {createPost(input:$input) {
 __typename ... on PostActionSuccess { post { id dueAt status } } ... on MutationError {message}
}}'''
DELETE='''mutation DeletePost($input: DeletePostInput!) {deletePost(input:$input) {
 __typename ... on DeletePostSuccess {id} ... on VoidMutationError {message}
}}'''

class BufferError(RuntimeError):pass

def utc(t):return t.astimezone(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def parse(s):return dt.datetime.fromisoformat(str(s).replace('Z','+00:00')).astimezone(dt.timezone.utc)

def graphql(query,variables=None,*,post=requests.post,api_key=None):
    api_key=api_key or os.getenv('BUFFER_API_KEY','')
    if not api_key:raise BufferError('BUFFER_API_KEY absent')
    response=post(ENDPOINT,json={'query':query,'variables':variables or {}},
                  headers={'Content-Type':'application/json','Authorization':'Bearer '+api_key},timeout=35)
    response.raise_for_status();data=response.json()
    if not isinstance(data,dict) or data.get('errors'):
        raise BufferError('GraphQL erreur: '+str(data.get('errors','réponse illisible'))[:400].replace(api_key,'[CLE]'))
    if not isinstance(data.get('data'),dict):raise BufferError('GraphQL sans data')
    return data['data']

class Buffer:
    def __init__(self,*,api_key=None,channel_id=None,organization_id=None,post=requests.post,get=requests.get):
        self.api_key=api_key or os.getenv('BUFFER_API_KEY','')
        self.channel_id=channel_id or os.getenv('BUFFER_CHANNEL_ID','')
        self.organization_id=organization_id or os.getenv('BUFFER_ORGANIZATION_ID','')
        self.post=post;self.get=get
        if not self.channel_id:raise BufferError('BUFFER_CHANNEL_ID absent')
    def call(self,query,variables=None):return graphql(query,variables,post=self.post,api_key=self.api_key)
    def organization(self):
        if self.organization_id:return self.organization_id
        orgs=((self.call(ORG_QUERY).get('account') or {}).get('organizations') or [])
        ids=[str(x['id']) for x in orgs if isinstance(x,dict) and x.get('id')]
        if len(ids)!=1:raise BufferError('Choisir BUFFER_ORGANIZATION_ID (organisation ambiguë)')
        self.organization_id=ids[0];return ids[0]
    def day(self,day):
        """Un jour entier Europe/Paris, pas une proximité de 90 secondes."""
        from zoneinfo import ZoneInfo
        p=ZoneInfo('Europe/Paris')
        start=dt.datetime.combine(day,dt.time.min,tzinfo=p)
        end=dt.datetime.combine(day+dt.timedelta(days=1),dt.time.min,tzinfo=p)
        ans=self.call(DAY_QUERY,{'organizationId':self.organization(),'channelId':self.channel_id,
                                  'slotStart':utc(start),'slotEnd':utc(end)}).get('posts')
        if not isinstance(ans,dict) or not isinstance(ans.get('edges'),list) or (ans.get('pageInfo') or {}).get('hasNextPage') is not False:
            raise BufferError('Page de la Queue Buffer incomplète: aucun envoi')
        out=[]
        for edge in ans['edges']:
            node=(edge or {}).get('node') or {}
            if not all(node.get(k) for k in ('id','dueAt','text','channelId','status')):
                raise BufferError('Une publication Buffer est illisible')
            if node['channelId']==self.channel_id and node['status']=='scheduled':out.append(node)
        return out
    def verify_images(self,base_url,names,folder):
        p=urlparse(base_url)
        if p.scheme!='https' or p.hostname!='raw.githubusercontent.com' or not base_url.endswith('/'):
            raise BufferError('Images GitHub publiques HTTPS requises')
        if len(names)!=5:raise BufferError('Carrousel anecdote: cinq images obligatoires')
        assets=[]
        for name in names:
            with Image.open(folder/name) as img:
                if img.size!=(1080,1350) or img.format!='PNG':raise BufferError('Image incorrecte: '+name)
            url=base_url+quote(name);ok=False
            for k in range(6):
                try:
                    r=self.get(url,timeout=15,stream=True)
                    try:
                        r.raise_for_status();ok=r.headers.get('Content-Type','').lower().startswith('image/')
                    finally:r.close()
                except requests.RequestException:pass
                if ok:break
                if k<5:time.sleep(8)
            if not ok:raise BufferError('Média inaccessible: '+url)
            assets.append({'image':{'url':url}})
        return assets
    def create(self,caption,due_at,assets):
        if not caption.startswith('📚 ANECDOTE BD') or len(caption)>2200:raise BufferError('Légende illisible')
        inp={'text':caption,'channelId':self.channel_id,'schedulingType':'automatic',
             'mode':'customScheduled','needsApproval':False,'dueAt':due_at,
             'assets':assets,'metadata':{'instagram':{'type':'post','shouldShareToFeed':True}}}
        ans=(self.call(CREATE,{'input':inp}).get('createPost') or {})
        if ans.get('message'):raise BufferError('Buffer refuse la publication: '+str(ans['message'])[:250])
        post=ans.get('post') or {}
        if not post.get('id') or post.get('status')!='scheduled' or (post.get('dueAt') and parse(post['dueAt'])!=parse(due_at)):
            raise BufferError('Publication non confirmée: vérifier Buffer avant de relancer')
        return post
    def delete_own(self,post_id):
        ans=self.call(DELETE,{'input':{'id':post_id}}).get('deletePost') or {}
        if ans.get('__typename')!='DeletePostSuccess' or ans.get('id')!=post_id:
            raise BufferError('Suppression non confirmée; contrôler Buffer: '+str(ans)[:120])
        return ans

def is_top(post):
    import re
    t=post.get('text','').strip()
    return bool(re.match(r'^(?:📚\s*)?TOP\s*(?:5|7)\s*(?:BD|MANGA|COMICS)\b',t,re.I))

def is_anecdote(post):return str(post.get('text','')).startswith('📚 ANECDOTE BD')
