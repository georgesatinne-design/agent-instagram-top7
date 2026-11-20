"""Moteur déterministe (sans génération d'images IA). Toutes les mesures sont fixes."""
from __future__ import annotations
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from sources.couvertures import cover_path

BASE=Path(__file__).resolve().parent
CHARTE=BASE/'templates/charte.json'

def verifier(data):
    if data.get('categorie') not in ('BD','MANGA','COMICS'):
        raise ValueError('Catégorie non reconnue')
    for key in ('perimetre','source','url_source','titres'):
        if not data.get(key): raise ValueError('Champ obligatoire absent : '+key)
    if not str(data['url_source']).startswith('https://'):
        raise ValueError('URL source doit être en HTTPS')
    if 'fin_ventes' in data:
        if not data.get('debut_ventes'):raise ValueError('Début des ventes manquant')
        a=dt.date.fromisoformat(data['debut_ventes']);b=dt.date.fromisoformat(data['fin_ventes'])
        if a>b or (b-a).days>14:raise ValueError('Période de ventes invalide')
    elif not data.get('date_palmares') and not data.get('periode_label'):
        raise ValueError('Période du classement absente; pas de date inventée')
    books=data['titres'];n=len(books)
    if not 1<=n<=10:raise ValueError('1 à 10 positions vérifiées requises')
    if [b.get('rang') for b in books]!=list(range(1,n+1)):
        raise ValueError('Rangs absents, dupliqués ou non consécutifs')
    if len({b.get('titre','').casefold().strip() for b in books})!=n:
        raise ValueError('Albums non uniques')
    if any(len(b.get('titre',''))<3 for b in books):
        raise ValueError('Titre invalide')
    return n

def police(size,bold=False):
    names=('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf') if bold else ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf')
    for name in names:
        if Path(name).exists():return ImageFont.truetype(name,size)
    raise RuntimeError('Police DejaVu Sans requise (gratuite)')

def text(draw,pos,value,size,color,bold=False,anchor=None):
    draw.text(pos,str(value),fill=color,font=police(size,bold),anchor=anchor)

def ajuster(draw,value,maxwidth,maxlines=3,startsize=45,minsize=21):
    value=str(value).strip()
    for size in range(startsize,minsize-1,-1):
        words=value.split(); lines=[];current=''
        for w in words:
            attempt=(current+' '+w).strip()
            if draw.textbbox((0,0),attempt,font=police(size,True))[2]<=maxwidth:
                current=attempt
            else:
                if current:lines.append(current)
                current=w
        if current:lines.append(current)
        if len(lines)<=maxlines and all(draw.textbbox((0,0),x,font=police(size,True))[2]<=maxwidth for x in lines):
            return lines,size
    raise ValueError('Titre impossible à disposer selon la charte : '+value)

def period(data):
    if data.get('debut_ventes') and data.get('fin_ventes'):
        a=dt.date.fromisoformat(data['debut_ventes']);b=dt.date.fromisoformat(data['fin_ventes'])
        return f"VENTES DU {a.strftime('%d/%m')} AU {b.strftime('%d/%m/%Y')}"
    if data.get('date_palmares'):
        return 'PALMARÈS DU '+data['date_palmares']
    return data['periode_label'].upper()

def render(data,destination,*,charte_path=CHARTE,cover_directory=None):
    n=verifier(data)
    chartbytes=Path(charte_path).read_bytes();charte=json.loads(chartbytes)
    if charte.get('format_px')!=[1080,1350]:raise ValueError('Format charte non supporté')
    palette=charte['couleurs'];accent=charte['categorie_couleur'][data['categorie']]
    directory=Path(destination);directory.mkdir(parents=True,exist_ok=True)
    cover_directory=Path(cover_directory or BASE/'assets/couvertures')
    pages=2+math.ceil(n/2)
    if n==10 and pages!=charte['images_par_carrousel']:
        raise ValueError('Une charte Top 10 doit produire exactement 7 diapositives')
    paths=[]; missing=[]
    def frame(i):
        im=Image.new('RGB',(1080,1350),palette['fond']);d=ImageDraw.Draw(im)
        d.rounded_rectangle((72,48,316,100),radius=18,fill=accent)
        text(d,(94,61),'TOP FRANCE',26,palette['fond'],True)
        text(d,(1007,59),f'{i:02d} / {pages:02d}',23,palette['secondaire'],True,anchor='ra')
        d.line((72,1240,1008,1240),fill='#4E5970',width=2)
        text(d,(72,1261),f"{data['categorie']}  •  FRANCE",22,palette['secondaire'],True)
        text(d,(1008,1261),'BROUILLON À VALIDER',18,palette['secondaire'],True,anchor='ra')
        return im,d
    def save(im,name):
        p=directory/name;im.save(p,optimize=True);paths.append(p)
    # Couverture d'ouverture
    im,d=frame(1)
    d.rounded_rectangle((72,210,1008,1110),radius=36,fill=palette['carte'])
    text(d,(113,291),'CLASSEMENT DES VENTES',31,accent,True)
    text(d,(107,410),f'TOP {n}',119,palette['texte'],True)
    text(d,(107,588),data['categorie'],106,accent,True)
    text(d,(111,794),'EN FRANCE',66,palette['texte'],True)
    period_lines,period_size=ajuster(d,period(data),832,2,34,22)
    for k,line in enumerate(period_lines):text(d,(112,951+k*47),line,period_size,palette['secondaire'],True)
    save(im,'01_ouverture.png')
    def book_card(im,d,book,y):
        d.rounded_rectangle((72,y,1008,y+404),radius=26,fill=palette['carte'])
        x0,y0,x1,y1=100,y+43,316,y+351
        d.rounded_rectangle((x0,y0,x1,y1),radius=16,fill=accent)
        cover=cover_path(cover_directory,book['titre'])
        if cover.exists():
            try:
                ci=Image.open(cover).convert('RGB')
                ci.thumbnail((202,293),Image.Resampling.LANCZOS)
                im.paste(ci,(x0+(216-ci.width)//2,y0+(308-ci.height)//2))
            except Exception:missing.append(book['titre'])
        else:
            missing.append(book['titre'])
            text(d,(x0+23,y0+47),f"{book['rang']:02d}",69,palette['fond'],True)
            text(d,(x0+18,y0+165),'COUVERTURE',16,palette['fond'],True)
            text(d,(x0+18,y0+188),'MANQUANTE',16,palette['fond'],True)
        text(d,(342,y+49),f"#{book['rang']:02d}",45,accent,True)
        lines,size=ajuster(d,book['titre'],629,3,43,20)
        for j,line in enumerate(lines):text(d,(342,y+120+j*(size+8)),line,size,palette['texte'],True)
        if book.get('detail'):
            lines,sz=ajuster(d,book['detail'],623,1,24,16)
            text(d,(342,y+285),lines[0],sz,palette['secondaire'])
        else:
            lines,sz=ajuster(d,book.get('editeur',''),623,1,25,16)
            text(d,(342,y+299),lines[0],sz,palette['secondaire'])
        move=book.get('mouvement') or 'POSITION VÉRIFIÉE'
        text(d,(342,y+356),move[:37],22,accent,True)
    for block in range(math.ceil(n/2)):
        im,d=frame(block+2)
        first=block*2; books=data['titres'][first:first+2]
        text(d,(72,151),'LE CLASSEMENT',34,accent,True)
        text(d,(72,213),f"PLACES {books[0]['rang']:02d}"+ (f" & {books[1]['rang']:02d}" if len(books)>1 else ''),49,palette['texte'],True)
        for j,book in enumerate(books):book_card(im,d,book,320+445*j)
        save(im,f'{block+2:02d}_rangs_{books[0]["rang"]:02d}'+(f'_{books[-1]["rang"]:02d}' if len(books)>1 else '')+'.png')
    # Podium
    im,d=frame(pages)
    text(d,(72,165),'LE PODIUM',77,palette['texte'],True)
    text(d,(72,279),'LES PREMIÈRES PLACES',30,accent,True)
    for i,book in enumerate(data['titres'][:3]):
        y=376+i*217;d.rounded_rectangle((72,y,1008,y+187),radius=24,fill=palette['carte'])
        text(d,(111,y+39),f'{i+1:02d}',72,accent,True)
        lines,size=ajuster(d,book['titre'],704,2,37,21)
        for j,line in enumerate(lines):text(d,(266,y+45+j*(size+10)),line,size,palette['texte'],True)
    d.rounded_rectangle((72,1080,1008,1205),radius=21,fill=accent)
    text(d,(98,1116),'TON NUMÉRO 1 ? COMMENTE !',32,palette['fond'],True)
    save(im,f'{pages:02d}_podium.png')
    overview=Image.new('RGB',(4*282+12,2*357+12),'#E5E8EE')
    for i,p in enumerate(paths):
        view=Image.open(p);view.thumbnail((270,338),Image.Resampling.LANCZOS)
        overview.paste(view,((i%4)*282+6,(i//4)*357+6))
    overview.save(directory/'apercu.png')
    caption=f"TOP {n} {data['categorie']} — {data['perimetre']} 🇫🇷\n{period(data)}\n\n"
    for book in data['titres']:
        caption+=f"{book['rang']}. {book['titre']} — {book.get('editeur','')}\n"
    caption+=f"\nSource : {data['source']}\n{data['url_source']}\n\nBrouillon soumis à validation avant publication."
    (directory/'legende_instagram.txt').write_text(caption,encoding='utf-8')
    (directory/'classement_source.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    report=['# Dossier à valider','',f"- Catégorie : {data['categorie']}",f'- Périmètre (important) : {data["perimetre"]}',f'- Source : {data["source"]}',f'- Lien : {data["url_source"]}',f'- Période : {period(data)}',f'- Albums vérifiés : {n}',f'- Couvertures effectivement présentes : {n-len(missing)}/{n}',f'- Charte fixe SHA256 : {hashlib.sha256(chartbytes).hexdigest()}', '', '## Contrôles avant validation', '- [ ] Dates et rangs vérifiés', '- [ ] Périmètre national / enseigne correctement signalé', '- [ ] Couvertures manquantes ou ambiguës acceptées', '- [ ] Graphisme conforme à la charte', '- [ ] Légende approuvée', '', '**AUCUNE PUBLICATION AUTOMATIQUE.**']
    if missing: report += ['', '### Couvertures absentes', *[f'- {name}' for name in missing]]
    (directory/'A_VALIDER.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    # page de revue HTML autoportée, utile sur PC/téléphone après extraction de l'artefact.
    items=''.join(f'<figure><img src="{html.escape(p.name)}" alt="Diapositive {i+1}"><figcaption>Image {i+1}/{len(paths)}</figcaption></figure>' for i,p in enumerate(paths))
    page=f'''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dossier à valider — {data['categorie']}</title><style>body{{font:16px system-ui;background:#111827;color:white;margin:0;padding:20px}}h1{{max-width:1100px;margin:20px auto}}p{{max-width:1100px;margin:15px auto;color:#cad5e3}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;max-width:1200px;margin:auto}}figure{{margin:0}}img{{width:100%;border-radius:12px}}figcaption{{color:#cbd5e1;font-size:14px}}a{{color:#f8c955}}</style><h1>À valider : {data['categorie']}</h1><p>{html.escape(data['perimetre'])} • {html.escape(period(data))} • <a href="{html.escape(data['url_source'])}">Source</a></p><main>{items}</main><p>Aucune publication n'a été réalisée. Lire A_VALIDER.md avant utilisation.</p></html>'''
    (directory/'REVUE.html').write_text(page,encoding='utf-8')
    return {'pages':len(paths),'images':paths,'covers_found':n-len(missing),'charte_hash':hashlib.sha256(chartbytes).hexdigest()}
