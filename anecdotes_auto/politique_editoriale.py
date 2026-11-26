"""Sujets explicitement rejetés par le propriétaire, sans suppression de l'historique.
Les anciennes publications ne peuvent plus réintégrer le stock ni le remplissage.
"""
# Les sujets de remplissage anciens (musées, biographies génériques, anniversaires)
# sont exclus. De nouveaux faits véritablement originaux sur ces univers peuvent
# être ajoutés sous un nouvel identifiant, après validation documentaire.
REJETES=frozenset({
 'topffer-geneve','topffer-professeur','topffer-theoricien','topffer-chronologie',
 'bruxelles-centre-doc','bruxelles-1989','bruxelles-1984','bruxelles-horta','bruxelles-textile','bruxelles-sauvetage','bruxelles-bobdemoor',
 'lucky-luke-80','lucky-luke-morris','lucky-luke-goscinny','lucky-luke-1946',
 'angouleme-festival-1974','angouleme-galerie-1983','angouleme-centre-1984','angouleme-industrie','angouleme-architectes','angouleme-collections','angouleme-deux-siecles','angouleme-2009',
 'festival-scolaire-1975','festival-fondateurs',
 'spirou-premier-numero','spirou-naissance','spirou-charleroi','spirou-robvel',
 'urban-superman-176','urban-superman-vo','urban-superman-equipe',
})
def accepte(fact):return fact.get('id') not in REJETES
