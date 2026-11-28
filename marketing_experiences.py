"""Expérience prospective à deux variantes, à coût nul et sans tag artificiel.
Comparer le même KPI (partages/portée) entre deux formulations, jamais les
commentaires avec les partages. Les anciennes légendes ne sont pas des essais.
"""
import datetime as dt,statistics,math
START=dt.date(2026,11,29)
VARIANTS={'A':'Tu connaissais déjà cette histoire du 9e art ?',
          'B':'À quel passionné du 9e art raconterais-tu cette histoire ?'}
MIN_PER_ARM=6
def assignment(day):
    if isinstance(day,str):day=dt.date.fromisoformat(day)
    if day<START:return None
    # Rotate within each weekday across weeks, independent of the subject.
    return 'A' if (day.isocalendar().week+day.weekday())%2==0 else 'B'
def experiment_caption(day,policy=None):
    if not day:return None
    arm=assignment(day)
    if not arm:return None
    winner=((policy or {}).get('experience_anecdotes') or {}).get('choix')
    return VARIANTS[winner if winner in VARIANTS else arm]
def variant(text):
    matches=[a for a,v in VARIANTS.items() if v in (text or '').splitlines() or v+' 👇' in (text or '').splitlines()]
    return matches[0] if len(matches)==1 else None
def evaluate(rows):
    # rows: (arm, share/reach), collected from actual sent mature posts.
    values={a:[] for a in VARIANTS}
    for arm,rate in rows:
        if arm in values and math.isfinite(rate) and rate>=0:values[arm].append(rate)
    n={a:len(v) for a,v in values.items()}
    result={'indicateur':'partages_par_compte_touche','effectifs':n,'choix':None,'etat':'COLLECTE','maturite_jours':[3,56],
            'limite':'Comparaison prospective non randomisée; effet causal non démontré.'}
    if min(n.values())<MIN_PER_ARM:return result
    med={a:statistics.median(v) for a,v in values.items()}
    result['medianes']=med;best=max(med,key=med.get);other='B' if best=='A' else 'A'
    if med[best]>=1.35*med[other] and med[best]-med[other]>=.005:
        # Exploratory signal, not a statistical significance claim.
        result.update(etat='SIGNAL_EXPLORATOIRE',choix=best)
    else:result['etat']='PAS_DE_SIGNAL_SUFFISANT'
    return result
