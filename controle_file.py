"""Contrôle final en lecture seule du canal Buffer."""
from calendrier_editorial import parse_due,validate_slot
from anecdotes_auto.buffer import Buffer,is_story

def final_guard(kind,due,*,api_key,channel_id,post,expected_id=None,buffer=None,now=None):
    exact=validate_slot(kind,due,now=now,check_margin=expected_id is None)
    target=parse_due(exact).date()
    buf=buffer if buffer is not None else Buffer(api_key=api_key,channel_id=channel_id,post=post)
    posts=buf.list_scheduled()
    if not isinstance(posts,list) or len(posts)>10:
        raise RuntimeError('File Buffer non vérifiable ou au-delà du plafond gratuit')
    same_day=[p for p in posts if not is_story(p) and parse_due(p['dueAt']).date()==target]
    if expected_id:
        if len(same_day)!=1 or same_day[0]['id']!=expected_id or parse_due(same_day[0]['dueAt'])!=parse_due(exact):
            raise RuntimeError('Créneau ou identité modifiés avant édition')
    elif same_day or len(posts)>=10:
        raise RuntimeError('Créneau occupé ou file pleine avant création')
    return True
