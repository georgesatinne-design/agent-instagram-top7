"""Charte Top 7 : fond ORIGINAL fourni par l'utilisateur, composition déterministe 8 pages.
Aucune image inventée, aucune donnée ni mouvement inventé.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sources.couvertures import cover_path
from studio import verifier

ROOT = Path(__file__).resolve().parent
BACKGROUND = ROOT/'assets'/'fond_bd_original.jpeg'  # Alias compatibilité tests BD.
DESIGN = ROOT/'templates'/'charte_top7.json'
W,H=1080,1350

def font(sz,bold=False):
    opts=('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/lato/Lato-Heavy.ttf') if bold else ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/lato/Lato-Regular.ttf')
    for p in opts:
        if Path(p).exists():return ImageFont.truetype(p,sz)
    raise RuntimeError('Police libre du système absente')

def label(lines, max_width, max_height, *, start=66, minimum=21, bold=True, draw=None):
    if draw is None: draw=ImageDraw.Draw(Image.new('RGB',(W,H)))
    text=' '.join(str(lines).split())
    for size in range(start,minimum-1,-1):
        f=font(size,bold)
        words=text.split(); rows=[]; line=''
        for word in words:
            trial=f'{line} {word}'.strip()
            if draw.textbbox((0,0),trial,font=f)[2]<=max_width:
                line=trial
            else:
                if line:rows.append(line)
                line=word
        if line:rows.append(line)
        if all(draw.textbbox((0,0),s,font=f)[2]<=max_width for s in rows) and len(rows)*(size+12)<=max_height:
            return rows,f,size+12
    raise ValueError('Titre trop long pour la charte : '+text)

def pill(img,bounds,fill,stroke=None,radius=18):
    d=ImageDraw.Draw(img)
    d.rounded_rectangle(bounds,radius=radius,fill=fill,outline=stroke,width=4 if stroke else 1)

def movement_state(book, source_confirmed):
    """Return (badge text, short text, semantic state), never infer from incomplete data."""
    if not source_confirmed:
        return ('ÉVOLUTION NON DISPONIBLE', '—', 'indisponible')
    value=(book.get('mouvement') or '').strip().upper()
    if not value or 'NON DOCUMENT' in value or 'INDISPONIBLE' in value:
        return ('ÉVOLUTION NON DISPONIBLE', '—', 'indisponible')
    if 'NOUVEAU' in value:
        return ('NOUVEAU', 'NOUVEAU', 'nouveau')
    if 'RETOUR' in value:
        return ('RETOUR', 'RETOUR', 'nouveau')
    if value in ('STABLE', '=', '= STABLE'):
        return ('= STABLE', '= ', 'stable')
    match=re.search(r'([+\-−])\s*(\d+)',value)
    if match:
        n=int(match.group(2))
        if n == 0:
            return ('= STABLE', '=', 'stable')
        direction='↑' if match.group(1)=='+' else '↓'
        state='progression' if direction=='↑' else 'recul'
        return (f'{direction} {n} PLACE'+('S' if n>1 else ''), f'{direction} {n}', state)
    return ('ÉVOLUTION NON DISPONIBLE', '—', 'indisponible')

def movement(book,source_confirmed):
    """Backwards compatible caption wording."""
    return movement_state(book,source_confirmed)[0]

def style_for_category(category, chart):
    styles=chart.get('categorie_styles') or {}
    if category not in styles:
        raise ValueError('Catégorie inconnue dans la charte : '+str(category))
    style=styles[category]
    required=('fond_original','violet','jaune','blanc','encre')
    if any(not style.get(key) for key in required):
        raise ValueError(f'Charte {category} non activée : fond et couleurs originales à fournir, aucune substitution autorisée')
    path=(ROOT/style['fond_original']).resolve()
    if not path.is_relative_to((ROOT/'assets').resolve()):
        raise ValueError('Le fond original doit être dans assets/')
    if not path.is_file():
        raise FileNotFoundError(f'Fond original {category} absent : {path}')
    if chart.get('format_px') != [1080,1350] or chart.get('ordre_pages') != [7,6,5,4,3,2,1,'recapitulatif']:
        raise ValueError('Charte Top 7 invalide : dimensions ou ordre')
    return style, path

def date_label(data):
    if data.get('debut_ventes') and data.get('fin_ventes'):
        a=dt.date.fromisoformat(data['debut_ventes']);b=dt.date.fromisoformat(data['fin_ventes'])
        return f'DU {a:%d/%m} AU {b:%d/%m/%Y}'
    return str(data.get('date_palmares') or data.get('periode_label') or '')

def base_image(background):
    path=Path(background)
    if not path.is_file(): raise FileNotFoundError('Fond original absent; génération refusée')
    b=Image.open(path).convert('RGB')
    return ImageOps.fit(b,(W,H),method=Image.Resampling.LANCZOS,centering=(0.5,0.5))

def draw_text_center(d,xy,value,sz,color,bold=True):
    d.text(xy,value,font=font(sz,bold),fill=color,anchor='mm',stroke_width=0)

def draw_top_rank_circle(draw,box,rank,fill_color,text_color):
    """Dessine un rond de classement avec 'TOP' + numéro."""
    x0,y0,x1,y1=box
    draw.ellipse(box,fill=fill_color)
    cx=(x0+x1)//2
    cy=(y0+y1)//2
    h=y1-y0
    if h>=300:
        draw_text_center(draw,(cx,cy-80),'TOP',58,text_color)
        draw_text_center(draw,(cx,cy+62),str(rank),190,text_color)
    else:
        draw_text_center(draw,(cx,cy-14),'TOP',17,text_color)
        draw_text_center(draw,(cx,cy+24),str(rank),40,text_color)


def paste_cover_fit(im, source, box, bg_color='#F6F6F6', allow_upscale=True):
    """Colle une couverture en l'agrandissant autant que possible dans le cadre."""
    x0,y0,x1,y1=box
    max_w=max(1,x1-x0)
    max_h=max(1,y1-y0)
    sw,sh=source.size
    if sw<=0 or sh<=0:
        return
    ratio=min(max_w/sw, max_h/sh)
    if not allow_upscale:
        ratio=min(1.0, ratio)
    new_size=(max(1,int(sw*ratio)), max(1,int(sh*ratio)))
    res=Image.Resampling.LANCZOS if ratio>=1 else Image.Resampling.LANCZOS
    fitted=source.resize(new_size, res)
    canvas=Image.new('RGB',(max_w,max_h),bg_color)
    px=(max_w-fitted.width)//2
    py=(max_h-fitted.height)//2
    canvas.paste(fitted,(px,py))
    im.paste(canvas,(x0,y0))

def render_top7(data,destination,cover_directory,*,use_watermark=False):
    verifier(data)
    count=len(data['titres'])
    if count<7:raise ValueError('Top 7 impossible : moins de sept rangs vérifiés')
    top=sorted(data['titres'],key=lambda t:t['rang'])[:7]
    if [x['rang'] for x in top]!=list(range(1,8)):raise ValueError('Le top ne commence pas à 1')
    target=Path(destination);target.mkdir(parents=True,exist_ok=True)
    chart=json.loads(DESIGN.read_text(encoding='utf-8'))
    style,background=style_for_category(data['categorie'],chart)
    purple=style['violet'];yellow=style['jaune'];ink=style['encre'];white=style['blanc'];rank_circle=style.get('rond') or yellow
    evolution_colors={**chart['evolution'], 'nouveau':purple}  # Nouveau suit la couleur de chaque univers ; ↑ vert et ↓ rouge restent fixes.
    bgbytes=background.read_bytes(); designbytes=DESIGN.read_bytes()
    fingerprint=hashlib.sha256(bgbytes+designbytes).hexdigest()
    missing=[]; slides=[];period=date_label(data)
    move_ok=bool(data.get('variations_verifiees'))
    def foot(im,index):
        d=ImageDraw.Draw(im)
        # Bandeau obligatoire et très lisible sur chacune des 8 pages :
        # titre explicite du palmarès et période précise des ventes.
        pill(im,(16,1261,1064,1343),purple,radius=10)
        d.text((34,1267),f'TOP DES VENTES • {data["categorie"]}',font=font(32,True),fill=yellow)
        d.text((35,1308),f'PÉRIODE DES VENTES : {period}',font=font(23,True),fill=yellow)
        d.text((1045,1280),f'{index}/8',font=font(26,True),fill=yellow,anchor='ra')
        if use_watermark:
            d.text((540,1249),'DÉMONSTRATION • PAS POUR PUBLICATION',font=font(20,True),fill=purple,anchor='mm')
    for idx,book in enumerate(reversed(top),start=1):
        rank=int(book['rang']);im=base_image(background);d=ImageDraw.Draw(im)
        # Titre dans le bandeau violet, blanc de fond conservé ailleurs.
        pill(im,(16,55,1064,178),purple,radius=6)
        title=(book.get('titre') or '').strip()
        title_lines,title_font,lineheight=label(title,980,102,start=63,minimum=30,draw=d)
        content_h=len(title_lines)*lineheight
        for j,line in enumerate(title_lines):
            draw_text_center(d,(540,115-content_h/2+j*lineheight+lineheight/2),line,title_font.size,yellow)
        # Éditeur affiché sur chaque page top, juste sous le titre.
        editor=(book.get('editeur') or '').strip()
        if editor:
            pill(im,(292,186,788,228),white,stroke=purple,radius=12)
            draw_text_center(d,(540,207),f'ÉDITEUR : {editor}',22,purple)
        # Bloc couverture agrandi : la couverture doit occuper presque tout le cadre blanc.
        cv=cover_path(cover_directory,title)
        x0,y0,x1,y1=155,245,931,1138
        pill(im,(x0-8,y0-8,x1+8,y1+8),'#FFFFFF',stroke=purple,radius=8)
        if cv.exists():
            try:
                source=Image.open(cv).convert('RGB')
                paste_cover_fit(im,source,(x0,y0,x1,y1),bg_color='#F2F2F2',allow_upscale=True)
            except Exception:
                missing.append(title)
                d=ImageDraw.Draw(im)
                d.multiline_text((542,650),'COUVERTURE\nÀ VÉRIFIER',font=font(45,True),fill=purple,anchor='mm',align='center',spacing=10)
        else:
            missing.append(title)
            d.multiline_text((542,650),'COUVERTURE\nNON DISPONIBLE',font=font(45,True),fill=purple,anchor='mm',align='center',spacing=10)
        # Rond jaune et rang violet, superposé au côté gauche.
        d=ImageDraw.Draw(im)
        draw_top_rank_circle(d,(48,510,448,910),rank,rank_circle,purple)
        # Évolution : couleur de l'indicateur (flèche ET nombre) selon la direction.
        move,compact,status=movement_state(book,move_ok)
        move_color=evolution_colors[status]
        pill(im,(540,1158,1064,1240),white,stroke=move_color,radius=19)
        move_size=32 if len(move)<20 else 24
        draw_text_center(ImageDraw.Draw(im),(802,1198),move,move_size,move_color)
        foot(im,idx)
        target_file=target/f'{idx:02d}_rang_{rank}.png'
        im.save(target_file,optimize=True)
        slides.append(target_file)
    # 8e page récapitulative TOP 1 vers TOP 7.
    im=base_image(background);d=ImageDraw.Draw(im)
    pill(im,(16,50,1064,192),purple,radius=8)
    draw_text_center(d,(540,122),'TOP 7 • RÉCAPITULATIF',60,yellow)
    pill(im,(42,211,1038,1214),purple,radius=24)
    for i,book in enumerate(top):
        y=238+i*135
        pill(im,(67,y,1013,y+115),white,radius=14)
        d=ImageDraw.Draw(im)
        draw_top_rank_circle(d,(84,y+12,175,y+103),book['rang'],rank_circle,purple)
        # Le récapitulatif affiche le nom + l'éditeur sur la même ligne visuelle.
        rows,f,lh=label(book['titre'],585,64,start=36,minimum=16,draw=d)
        top_text=y+40 -len(rows)*lh/2
        for j,line in enumerate(rows):
            d.text((203,top_text+j*lh),line,font=f,fill=ink)
        editor=(book.get('editeur') or '').strip()
        if editor:
            d.text((203,y+83),f'Éditeur : {editor}',font=font(18,True),fill=purple)
        mv,long_short,state=movement_state(book,move_ok)
        indicator_color=evolution_colors[state]
        indicator=(803,y+31,998,y+85)
        pill(im,indicator,white,stroke=indicator_color,radius=14)
        d=ImageDraw.Draw(im)
        badge_size=26 if len(long_short)<=6 else 19
        draw_text_center(d,(900,y+58),long_short,badge_size,indicator_color)
    foot(im,8)
    path=target/'08_recapitulatif.png';im.save(path,optimize=True);slides.append(path)
    caption=f'📚 TOP 7 {data["categorie"]} — Les meilleures ventes\n📅 Ventes {period}\n\n'
    for book in top:
        mv=movement(book,move_ok)
        publisher=(book.get('editeur') or '').strip()
        caption+=f'#{book["rang"]} {book["titre"]}'
        if publisher:
            caption+=f' — {publisher}'
        if mv!='ÉVOLUTION NON DISPONIBLE':
            caption+=f' ({mv})'
        caption+='\n'
    caption+='\nEt toi, lequel as-tu lu ? 👇\n\n'
    caption+=f'\n#BD #BandesDessinees #TopBD #Lecture #ClassementBD' if data['categorie']=='BD' else ('\n#Manga #ClassementManga #Lecture' if data['categorie']=='MANGA' else '\n#Comics #ClassementComics #Lecture')
    (target/'legende_instagram.txt').write_text(caption,encoding='utf-8')
    # Dossier de publication : aucune référence bibliographique ou URL n'est exposée.
    public_data={key:value for key,value in data.items() if key not in ('source','url_source','perimetre')}
    public_data['titres']=[
        {key:value for key,value in book.items() if 'url' not in key.lower() and 'source' not in key.lower()}
        for book in data['titres']
    ]
    (target/'classement_donnees.json').write_text(json.dumps(public_data,ensure_ascii=False,indent=2),encoding='utf-8')
    # Vue d'ensemble
    preview=Image.new('RGB',(4*282,2*364),'#e6e3ec')
    for i,p in enumerate(slides):
        snap=Image.open(p).convert('RGB');snap.thumbnail((270,338))
        preview.paste(snap,((i%4)*282+6,(i//4)*364+6))
    preview.save(target/'apercu.png')
    manifest={
        'category':data['categorie'], 'status':'DRAFT_ONLY', 'period':period,
        'pages':[p.name for p in slides], 'caption_file':'legende_instagram.txt',
        'intended_post_date':None,'source_validated':not use_watermark,
        'covers_complete':len(missing)==0,'missing_covers':missing,
        'visual_fingerprint':fingerprint,
        'indicateurs_evolution':{str(b['rang']):{'texte':movement_state(b,move_ok)[1], 'etat':movement_state(b,move_ok)[2], 'couleur':evolution_colors[movement_state(b,move_ok)[2]]} for b in top},
        'ready_to_stage':bool(not missing and not use_watermark)
    }
    (target/'post_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    import html
    items=''.join(f'<figure><img src="{html.escape(p.name)}" alt="Page {i+1}"><figcaption>Page {i+1} / 8</figcaption></figure>' for i,p in enumerate(slides))
    review=f'<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Top 7 {html.escape(data["categorie"])} à valider</title><style>body{{background:#eee8f3;color:#40224e;font:16px system-ui;margin:0;padding:18px}}h1,p{{max-width:1150px;margin:16px auto}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;max-width:1200px;margin:auto}}figure{{margin:0}}img{{width:100%;border-radius:8px;border:1px solid #a18ea8}}figcaption{{font-size:14px}}</style><h1>Top 7 {html.escape(data["categorie"])} — brouillon</h1><p>Période {html.escape(period)} • aucune publication ni programmation automatique</p><main>{items}</main></html>'
    (target/'REVUE.html').write_text(review,encoding='utf-8')
    (target/'A_VALIDER.md').write_text(
        f'# Publication {data["categorie"]} — à valider\n\n'
        f'- Pages : **8** (rangs 7 → 1 + récapitulatif)\n'
        f'- Période : {period}\n'
        f'- Couvertures manquantes : **{len(missing)}**\n'
        f'- Fond original + charte SHA256 : `{fingerprint}`\n'
        f'- Envoi possible à Buffer : **{manifest["ready_to_stage"]}**\n'
        '- L’agent ne programme et ne publie jamais le post automatiquement.\n'
        '- Le passage du brouillon à la programmation exige une action humaine dans Buffer.\n',encoding='utf-8')
    return {'pages':8,'images':[str(p) for p in slides], 'missing_covers':missing,'manifest':str(target/'post_manifest.json'),'visual_fingerprint':fingerprint}
