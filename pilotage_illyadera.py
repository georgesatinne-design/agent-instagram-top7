"""Supervision lecture seule : aucun rerun aveugle après une mutation."""
import os,datetime as dt
import requests
EXPECTED={'anecdotes_bd_auto.yml':36,'anecdotes_bd_phototheque.yml':40,'stories_illyadera.yml':30,
          'reels_illyadera.yml':48,'audit_buffer_lecture_seule.yml':18,'manga_top7_collecte.yml':96,
          'hebdomadaire.yml':96,'comics_top7_auto.yml':144,'actus_9e_art.yml':192}
def health():
    repo=os.environ.get('GITHUB_REPOSITORY');token=os.environ.get('GH_TOKEN')
    if not repo or not token:return {'etat':'ACCES_NON_CONFIGURE'}
    try:
        url='https://api.github.com/repos/'+repo+'/actions/runs'
        r=requests.get(url,params={'branch':'main','per_page':100},headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'},timeout=15)
        r.raise_for_status();runs=r.json()['workflow_runs']
        now=dt.datetime.now(dt.timezone.utc);report={}
        for file,limit in EXPECTED.items():
            candidates=[x for x in runs if x.get('path','').split('/')[-1].split('@')[0]==file and x.get('status')=='completed']
            if not candidates:report[file]={'etat':'AUCUNE_EXECUTION_VISIBLE'};continue
            last=max(candidates,key=lambda x:x['created_at'])
            age=(now-dt.datetime.fromisoformat(last['created_at'].replace('Z','+00:00'))).total_seconds()/3600
            state='OK' if last['conclusion']=='success' else 'A_CONTROLER'
            if age>limit:state='RETARD_A_CONTROLER'
            report[file]={'etat':state,'resultat':last['conclusion'],'age_heures':round(age,1),'run_id':last['id']}
        return {'etat':'LECTURE_DIRECTE','workflows':report,'politique':'Pas de relance après mutation incertaine sans réconciliation des reçus. Aucun secret ni log brut conservé.'}
    except (requests.RequestException,ValueError,KeyError,TypeError):return {'etat':'ACCES_NON_CONFIRME'}
