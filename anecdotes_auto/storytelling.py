"""Écriture éditoriale sans invention factuelle, sans IA générative.

Les accroches proposées pour quelques sujets sont entièrement vérifiables dans les
faits du catalogue. Pour les autres sujets, les formulations reprennent strictement
hook, fait, contexte et détail, sans ajouter de fait nouveau.
"""
from __future__ import annotations
import re

# Scripts approuvés et maintenables par le propriétaire de la page.
# Toute proposition doit être cohérente avec 'fait', 'contexte', 'detail' de l'entrée source.
SCRIPTS={
 'bruxelles-horta':{'hook':'CE MUSÉE CACHE UNE SURPRISE','question':'Tu aurais deviné qui a dessiné ce bâtiment ?', 'transition':'Et avant les bulles de BD…'},
 'bruxelles-textile':{'hook':'AVANT LA BD, IL Y AVAIT… DU TISSU !', 'question':'Tu connaissais l’ancienne vie de ce musée ?', 'transition':'Retour dans les anciennes boutiques…'},
 'bruxelles-1989':{'hook':'UNE DATE QUI CHANGE TOUT À BRUXELLES', 'question':'Tu as déjà visité ce musée ?', 'transition':'Un nouveau chapitre s’ouvre…'},
 'spirou-naissance':{'hook':'SPIROU N’A PAS TOUJOURS ÉTÉ UNE LÉGENDE', 'question':'C’est quoi ton album de Spirou préféré ?', 'transition':'Tout commence avec un journal…'},
 'spirou-premier-numero':{'hook':'SPIROU : TOUT A COMMENCÉ SUR PAPIER', 'question':'Tu as déjà feuilleté un vieux Spirou ?', 'transition':'Retour sur la toute première parution…'},
 'lucky-luke-1946':{'hook':'LE PREMIER LUCKY LUKE N’EST PAS CELUI QUE TU CROIS', 'question':'Tu as déjà lu Arizona 1880 ?', 'transition':'Retour à la première aventure…'},
 'lucky-luke-morris':{'hook':'MORRIS… CE N’ÉTAIT PAS SON VRAI NOM', 'question':'Tu le savais, toi ?', 'transition':'Derrière le pseudonyme…'},
 'lucky-luke-goscinny':{'hook':'DEUX GÉANTS SUR UN MÊME COW-BOY', 'question':'Quel est ton Lucky Luke préféré ?', 'transition':'Une collaboration devenue culte…'},
 'angouleme-industrie':{'hook':'UN MUSÉE BD DANS… UNE BRASSERIE ?', 'question':'Tu imaginais la BD dans une ancienne brasserie ?', 'transition':'Un lieu a changé de vocation…'},
 'angouleme-collections':{'hook':'25 000 PLANCHES. ET CE N’EST PAS UN RÊVE.', 'question':'Quelle planche rêverais-tu de voir en vrai ?', 'transition':'Ce patrimoine est bien réel…'},
 'topffer-geneve':{'hook':'UN DES PÈRES DE LA BD ÉTAIT SUISSE', 'question':'Tu avais déjà entendu parler de Töpffer ?', 'transition':'Direction Genève…'},
}


# Les micro-fiches purement commerciales ou répétitives ne sont PAS des anecdotes
# suffisamment fortes pour remplir le calendrier. Elles restent dans l’archive.
EXCLUS_EDITORIAUX={
 'urban-superman-176', 'urban-superman-vo', 'urban-superman-equipe',
 'topffer-chronologie', 'topffer-theoricien',
}

def editorial_eligible(fact):
    return (fact.get('id') not in EXCLUS_EDITORIAUX
            and fact.get('type_preuve') != 'METADONNEES_EDITEUR_OFFICIEL'
            and fact.get('theme') != 'EDITION')

SCRIPTS.update({
 'topffer-professeur':{'hook':'AVANT LES BD, TÖPFFER ENSEIGNAIT', 'question':'Tu imaginais un professeur parmi les pionniers de la BD ?'},
 'angouleme-festival-1974':{'hook':'ANGOULEME, 1974 : LE DÉBUT DE TOUT', 'question':'Tu as déjà vécu le Festival d’Angoulême ?'},
 'angouleme-galerie-1983':{'hook':'UNE GALERIE POUR ZIG ET PUCE ?', 'question':'Tu connais les albums de Saint-Ogan ?'},
 'angouleme-centre-1984':{'hook':'QUAND LA BD DEVIENT UN GRAND PROJET', 'question':'Tu savais que ce projet remonte à 1984 ?'},
 'angouleme-architectes':{'hook':'UN MUSÉE SE DESSINE EN 1985', 'question':'Tu as déjà visité le bâtiment d’Angoulême ?'},
 'angouleme-deux-siecles':{'hook':'DEUX SIÈCLES DE BD EN UN LIEU', 'question':'Quelle époque de la BD te passionne le plus ?'},
 'angouleme-2009':{'hook':'LE MUSÉE BD A CHANGÉ D’ADRESSE', 'question':'Tu l’as connu avant son déménagement ?'},
 'bruxelles-sauvetage':{'hook':'ET SI CE MUSÉE AVAIT DISPARU ?', 'question':'Tu connaissais cet épisode de son histoire ?'},
 'bruxelles-1984':{'hook':'BRUXELLES : LE MUSÉE EXISTAIT AVANT D’OUVRIR', 'question':'Tu savais que l’association date de 1984 ?'},
 'bruxelles-bobdemoor':{'hook':'UN DESSINATEUR À LA TÊTE DU MUSÉE', 'question':'Tu connaissais Bob de Moor ?'},
 'bruxelles-centre-doc':{'hook':'CE MUSÉE NE GARDE PAS QUE DES BD', 'question':'Tu savais qu’il avait aussi un centre de documentation ?'},
 'spirou-charleroi':{'hook':'SPIROU : DIRECTION CHARLEROI, 1938', 'question':'Tu savais que l’aventure était née à Charleroi ?'},
 'spirou-robvel':{'hook':'QUI A DESSINÉ LE TOUT PREMIER SPIROU ?', 'question':'Tu connaissais le nom de Rob-Vel ?'},
 'lucky-luke-80':{'hook':'80 ANS DE CHEVAUCHÉES POUR LUCKY LUKE', 'question':'Quel est ton souvenir préféré de Lucky Luke ?'},
 'festival-scolaire-1975':{'hook':'ANGOULEME : DES ENFANTS DESSINENT DEPUIS 1975', 'question':'Tu as déjà participé à un concours de BD ?'},
 'festival-fondateurs':{'hook':'LE PREMIER SALON BD D’ANGOULEME : 1974', 'question':'Tu as déjà visité Angoulême pendant le festival ?'},
})

def tidy(s, max_len=170):
    s=re.sub(r'\s+',' ',str(s or '')).strip()
    if not s or len(s)>max_len:raise ValueError('Texte éditorial absent ou trop long')
    return s

def story(fact):
    curated=SCRIPTS.get(fact['id'],{})
    hook=tidy(curated.get('hook') or fact['hook'],95)
    # Source facts are retained verbatim; no claims invented by the layout engine.
    return {
       'hook':hook,
       'revelation':tidy(fact['fait'],270),
       'transition':tidy(curated.get('transition') or fact.get('transition') or 'Remettons cette histoire dans son contexte…',95),
       'contexte':tidy(fact['contexte'],270),
       'detail':tidy(fact['detail'],270),
       'question':tidy(curated.get('question') or fact.get('question') or 'Tu le savais, toi ?',100),
    }
