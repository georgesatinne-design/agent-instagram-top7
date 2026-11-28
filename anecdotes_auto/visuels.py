"""Studio ANECDOTE DU 9e ART / V5 : chaque photographie représente une étape de l'anecdote.

Aucune génération IA, aucun clonage de photo d'une page à l'autre :
- les visuels figuratifs viennent exclusivement de photos_reelles.resolve() ;
- les pages sans photo sont des compositions typographiques vectorielles par Pillow ;
- une grande signature jaune ANECDOTE DU 9e ART identifie immédiatement le format ;
- les 5 pages suivent accroche -> révélation -> contexte -> détail -> question ;
- un audit machine lisible permet de contrôler la non-réutilisation.
"""
from __future__ import annotations
import hashlib, io, json, math, re
from pathlib import Path
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps
from .catalogue import ROOT_REPO
from .storytelling import story

W,H=1080,1350
NIGHT='#24152E'; PURPLE='#512464'; INK='#1B1422'; CREAM='#FFF8EE'
YELLOW='#FFE32C'; CORAL='#F16B59'; MINT='#67CDBD'; WHITE='#FFFFFF'
FONT_BOLD=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
           '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']
FONT_NORM=['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
           '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']
VERSION='BD_ANECDOTE_V5_IMAGES_SCENARISEES'


def font(size,bold=True):
    for file in (FONT_BOLD if bold else FONT_NORM):
        if Path(file).is_file():return ImageFont.truetype(file,size)
    return ImageFont.load_default()


def wrap_text(d,text,width,font_obj):
    lines=[];line=''
    for word in str(text).split():
        trial=(line+' '+word).strip()
        if d.textbbox((0,0),trial,font=font_obj)[2] <= width: line=trial
        else:
            if line:lines.append(line)
            line=word
    if line:lines.append(line)
    return lines


def text_fit(d,text,xywh,*,size=82,min_size=32,max_lines=6,color=INK,align='left',spacing=1.19):
    x,y,w,h=xywh
    text=re.sub(r'\s+',' ',str(text or '')).strip()
    if not text:raise ValueError('Texte vide')
    for n in range(size,min_size-1,-2):
        f=font(n);lines=wrap_text(d,text,w,f)
        line_h=round(n*spacing)
        if len(lines)<=max_lines and line_h*len(lines)<=h and all(d.textbbox((0,0),l,font=f)[2]<=w for l in lines):break
    else:raise ValueError('Le texte est trop long pour la page : '+text[:70])
    for i,l in enumerate(lines):
        if align=='center': d.text((x+w/2,y+i*line_h),l,font=f,fill=color,anchor='mt')
        else:d.text((x,y+i*line_h),l,font=f,fill=color,anchor='lt')
    return line_h*len(lines)


def _photo_hash(img):
    """Empreinte du contenu source (pas une empreinte des recadrages)."""
    im=ImageOps.exif_transpose(img).convert('RGB')
    # Une réexportation JPEG légèrement différente conserve ce hash de perception.
    small=im.resize((9,8),Image.Resampling.LANCZOS).convert('L')
    px=list(small.getdata());bits=0
    for row in range(8):
        for col in range(8):bits=(bits<<1)|int(px[row*9+col]>px[row*9+col+1])
    return bits


def _is_similar(a,b,threshold=3):
    return (a^b).bit_count()<=threshold


def load_photos(photos):
    """Élimine photos identiques ou quasi-identiques, même sous deux fichiers différents."""
    unique=[];signatures=[];keys=[]
    for item in (photos or []):
        if isinstance(item,Image.Image): im=ImageOps.exif_transpose(item).convert('RGB').copy()
        else:
            with Image.open(item) as original:
                im=ImageOps.exif_transpose(original).convert('RGB').copy()
        # Conserver la photo réelle comme seul élément figuratif ; rien de synthétique.
        digest=hashlib.sha256(im.tobytes()).hexdigest()
        phash=_photo_hash(im)
        if digest in keys or any(_is_similar(phash,existing) for existing in signatures):
            continue
        unique.append(im);signatures.append(phash);keys.append(digest)
    return unique,keys


def photo_allocation(n):
    """1 photo maximum par page, et jamais la même sur 2 pages.

    Deux photos -> pages 1 et 3, pas de réutilisation sur 2,4,5.
    Trois photos -> pages 1,3,4 ; quatre -> 1,3,4,5 ; cinq -> toutes.
    """
    if n<1:raise ValueError('REFUS PUBLICATION: photos réelles validées requises')
    slots=[1,3,4,5,2]
    return {slot:index for index,slot in enumerate(slots[:min(n,5)])}


def _crop(img,w,h,centering=(.5,.5)):
    return ImageOps.fit(img,(int(w),int(h)),Image.Resampling.LANCZOS,centering=centering)


def _rect(d,xy,fill,r=0,outline=None,width=1):
    if r:d.rounded_rectangle(xy,radius=r,fill=fill,outline=outline,width=width)
    else:d.rectangle(xy,fill=fill,outline=outline,width=width)


def _dots(img,rect,*,tone=PURPLE,step=27,radius=3):
    x,y,w,h=rect;d=ImageDraw.Draw(img)
    for row,yy in enumerate(range(y,y+h,step)):
        for xx in range(x+(row%2)*step//2,x+w,step):
            d.ellipse((xx,yy,xx+radius,yy+radius),fill=tone)


def _sticker(img,text,xy,*,fill=YELLOW,color=NIGHT,size=27,pad=18):
    x,y=xy;d=ImageDraw.Draw(img);f=font(size)
    bb=d.textbbox((0,0),text,font=f)
    w=bb[2]+2*pad;h=size+pad+16
    _rect(d,(x,y,x+w,y+h),fill,r=10)
    d.text((x+pad,y+12),text,font=f,fill=color)
    return (w,h)


def _starburst(img,cx,cy,r,*,fill=CORAL):
    d=ImageDraw.Draw(img)
    pts=[]
    for i in range(32):
        theta=i*math.pi/16
        rad=r if i%2==0 else r*.82
        pts.append((int(cx+rad*math.cos(theta)),int(cy+rad*math.sin(theta))))
    d.polygon(pts,fill=fill)


def _photo_panel(img,photo,box,*,rounded=0,outline=None,centering=(.5,.5)):
    x,y,w,h=box
    segment=_crop(photo,w,h,centering)
    if rounded:
        mask=Image.new('L',(w,h),0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=rounded,fill=255)
        img.paste(segment,(x,y),mask)
    else:img.paste(segment,(x,y))
    if outline:ImageDraw.Draw(img).rounded_rectangle((x,y,x+w,y+h),radius=rounded,outline=outline,width=8)


def _footer(img,n):
    d=ImageDraw.Draw(img)
    d.rectangle((0,1270,W,H),fill=NIGHT)
    d.text((40,1309),'ANECDOTE DU 9e ART',font=font(22),fill=YELLOW,anchor='lm')
    d.text((1034,1309),f'{n}/5',font=font(30),fill=CREAM,anchor='rm')
    # Indicateur de progression du récit : 5 segments courts et immédiatement lisibles.
    for i in range(5):
        x=660+i*62
        d.rounded_rectangle((x,1304,x+48,1315),radius=6,fill=YELLOW if i<n else '#7E6988')


def _mini_brand(img,n,title):
    d=ImageDraw.Draw(img)
    d.rectangle((0,0,W,101),fill=NIGHT)
    d.rectangle((0,0,14,101),fill=YELLOW)
    d.text((40,49),'ANECDOTE DU 9e ART',font=font(32),fill=YELLOW,anchor='lm')
    d.text((1033,49),title,font=font(25),fill=CREAM,anchor='rm')
    _footer(img,n)


def _gradient_overlay(img,x,y,w,h,top=(36,21,46,0),bottom=(36,21,46,255)):
    layer=Image.new('RGBA',(w,h))
    p=layer.load()
    for yy in range(h):
        t=yy/max(1,h-1)
        value=tuple(round(a*(1-t)+b*t) for a,b in zip(top,bottom))
        for xx in range(w):p[xx,yy]=value
    im=img.convert('RGBA');im.alpha_composite(layer,(x,y))
    return im.convert('RGB')


def page(fact,number,photos=None,*,allocation=None,scene_labels=None):
    """Rend une page sans jamais aller rechercher une photo déjà utilisée."""
    if number not in range(1,6):raise ValueError('Page 1 à 5 requise')
    if photos is None:
        # Exclusivement pour les maquettes/tests historiques : ne passe jamais par render().
        fallback=ROOT_REPO/'anecdotes_assets'/'fond_bd_original.jpeg'
        if not fallback.is_file():raise ValueError('Photo de maquette indisponible')
        photos=[fallback]
    prepared,keys=load_photos(photos)
    if not prepared:raise ValueError('REFUS PUBLICATION: photos réelles validées requises')
    allocations=allocation or photo_allocation(len(prepared))
    # La même photo n'a pas le droit d'être allouée deux fois, même si elle est recadrée.
    if len(set(allocations.values()))!=len(allocations):
        raise ValueError('PHOTO_REPETEE: source identique affectée à plusieurs slides')
    idx=allocations.get(number)
    ph=prepared[idx] if idx is not None else None
    s=story(fact)
    accent={'HISTOIRE':MINT,'PATRIMOINE':CORAL,'CLASSIQUE':'#F6A743','COMICS':'#D978AF'}.get(str(fact.get('theme','')).upper(),CORAL)
    im=Image.new('RGB',(W,H),CREAM);d=ImageDraw.Draw(im)

    if number==1:
        # IDENTITÉ VISUELLE IMMEDIATE : 16 % d'écran en jaune, grand nom de format.
        d.rectangle((0,0,W,197),fill=YELLOW)
        d.text((35,83),'ANECDOTE DU 9e ART',font=font(68),fill=NIGHT,anchor='lm')
        d.rectangle((0,190,W,220),fill=NIGHT)
        # Photo unique d'ouverture : jamais visible ailleurs dans ce carrousel.
        _photo_panel(im,ph,(0,220,1080,690))
        im=_gradient_overlay(im,0,660,W,260,top=(36,21,46,0),bottom=(36,21,46,190))
        d=ImageDraw.Draw(im)
        _starburst(im,943,810,106,fill=YELLOW)
        d.text((943,810),'?',font=font(142),fill=NIGHT,anchor='mm')
        d.polygon(((0,860),(1080,810),(1080,1269),(0,1269)),fill=NIGHT)
        _sticker(im,'LE SAVAIS-TU ?', (41,882),fill=CORAL,color=NIGHT,size=32)
        text_fit(ImageDraw.Draw(im),s['hook'],(48,975,990,229),size=75,min_size=38,max_lines=4,color=CREAM)
        d=ImageDraw.Draw(im)
        d.text((51,1227),'LA SUITE VA TE SURPRENDRE   →',font=font(23),fill=YELLOW)
    elif number==2:
        # RÉVÉLATION : rupture graphique nette ; photo supplémentaire seulement si unique.
        d.rectangle((0,0,W,H),fill=YELLOW)
        d.polygon(((660,101),(1080,101),(1080,820),(350,820)),fill=CORAL)
        _dots(im,(45,180,400,410),tone=PURPLE,step=25,radius=3)
        if ph is not None:
            _photo_panel(im,ph,(595,158,449,470),rounded=21,outline=NIGHT)
        else:
            # Composition vectorielle, aucune « illustration » figurative inventée.
            _starburst(im,835,355,174,fill=CREAM)
            d=ImageDraw.Draw(im)
            d.text((832,360),'!',font=font(240),fill=NIGHT,anchor='mm')
        d=ImageDraw.Draw(im)
        d.rounded_rectangle((52,609,1028,1210),radius=28,fill=NIGHT)
        _sticker(im,'LA RÉVÉLATION', (80,563),fill=CREAM,size=34)
        text_fit(ImageDraw.Draw(im),s['revelation'],(88,700,904,385),size=77,min_size=35,max_lines=6,color=CREAM)
        d=ImageDraw.Draw(im)
        d.text((91,1149),'MAIS POURQUOI ?   →',font=font(29),fill=MINT)
        _mini_brand(im,2,'LE FAIT')
    elif number==3:
        # CONTEXTE : une AUTRE photo réelle, sinon un encart éditorial graphique.
        d.rectangle((0,0,W,H),fill=CREAM)
        if ph is not None:
            _photo_panel(im,ph,(32,134,1016,660),rounded=25,outline=NIGHT)
            d=ImageDraw.Draw(im)
            _sticker(im,'LE CONTEXTE EN IMAGES', (53,729),fill=YELLOW,size=29)
        else:
            d.polygon(((0,128),(1080,128),(1080,812),(0,620)),fill=PURPLE)
            _dots(im,(40,175,940,570),tone=YELLOW,step=28,radius=3)
            d=ImageDraw.Draw(im)
            d.text((550,420),'03',font=font(280),fill=CREAM,anchor='mm')
        d=ImageDraw.Draw(im)
        d.rectangle((34,830,1046,1225),fill=PURPLE)
        text_fit(d,s['contexte'],(75,889,927,274),size=66,min_size=32,max_lines=6,color=CREAM)
        _mini_brand(im,3,'LE CONTEXTE')
    elif number==4:
        # DÉTAIL : une nouvelle photo si elle existe ; sinon une immense citation graphique.
        d.rectangle((0,0,W,H),fill=NIGHT)
        d.polygon(((0,111),(W,250),(W,750),(0,790)),fill=accent)
        if ph is not None:
            _photo_panel(im,ph,(42,140,995,565),rounded=25,outline=CREAM,centering=(.52,.47))
        else:
            _dots(im,(50,180,930,540),tone=YELLOW,step=32)
            _starburst(im,540,408,204,fill=YELLOW)
            d=ImageDraw.Draw(im)
            d.text((540,396),'!',font=font(245),fill=NIGHT,anchor='mm')
        d=ImageDraw.Draw(im)
        _sticker(im,'LE DÉTAIL À RETENIR', (52,718),fill=YELLOW,size=31)
        text_fit(ImageDraw.Draw(im),s['detail'],(60,820,940,330),size=73,min_size=35,max_lines=6,color=CREAM)
        d=ImageDraw.Draw(im)
        d.text((66,1188),'ET TOI, TU EN PENSES QUOI ?   →',font=font(23),fill=MINT)
        _mini_brand(im,4,'LE DÉTAIL')
    else:
        # FIN : une vraie question de passionné, jamais une énième photo recyclée.
        d.rectangle((0,0,W,H),fill=PURPLE)
        d.polygon(((0,156),(W,108),(W,370),(0,580)),fill=YELLOW)
        _dots(im,(20,620,1010,520),tone='#876091',step=30)
        if ph is not None:
            _photo_panel(im,ph,(550,172,479,394),rounded=23,outline=NIGHT)
        else:
            _starburst(im,820,390,144,fill=CORAL)
            d=ImageDraw.Draw(im)
            d.text((820,385),'?',font=font(190),fill=NIGHT,anchor='mm')
        d=ImageDraw.Draw(im)
        d.text((45,237),'ET TOI ?',font=font(115),fill=NIGHT)
        d.rounded_rectangle((48,642,1031,1072),radius=37,fill=CREAM)
        text_fit(ImageDraw.Draw(im),s['question'],(86,718,914,300),size=86,min_size=38,max_lines=5,color=NIGHT)
        d=ImageDraw.Draw(im)
        _sticker(im,'ON EN PARLE EN COMMENTAIRE  ↓',(53,1132),fill=YELLOW,size=28)
        _mini_brand(im,5,'À TON TOUR')
    # Un cartouche court EXPLIQUE l'image de cette page. Il n'affiche pas la
    # source (dans l'audit interne seulement), ne prétend pas dater une photo moderne.
    if ph is not None and scene_labels and number in scene_labels:
        role=str(scene_labels[number].get('role','')).upper().strip()[:29]
        if role:
            d=ImageDraw.Draw(im)
            lab_font=font(22)
            b=d.textbbox((0,0),role,font=lab_font)
            box_width=min(800,b[2]+43)
            yy={1:246,2:168,3:160,4:169,5:192}.get(number,165)
            _rect(d,(30,yy,30+box_width,yy+48),NIGHT,r=12)
            d.text((48,yy+9),role,font=lab_font,fill=YELLOW)
    if number==1:_footer(im,1)
    return im


def render(fact,folder,photos=None,*,audit_path=None,scenes=None):
    """Génère 5 pages : les scènes approuvées sont liées au texte de leur page.

    Sans `scenes`, conserve un mode de test pour les anciennes simulations locales.
    En production `run.stage_fact` fournit TOUJOURS les scènes de `resolve`.
    """
    photos_unique,hashes=load_photos(photos)
    if not photos_unique:raise ValueError('REFUS PUBLICATION: photos réelles validées requises')
    if scenes is not None:
        if len(scenes)!=len(photos or []):raise ValueError('Preuve de scène manquante')
        if len(photos_unique)!=len(photos or []):raise ValueError('PHOTO_REPETEE: sources de scènes identiques')
        allocations={int(s['page']):i for i,s in enumerate(scenes)}
        if any(p not in (1,2,3,4,5) for p in allocations) or len(allocations)!=len(scenes):
            raise ValueError('Répartition des pages incorrecte')
        scene_labels={int(s['page']):s for s in scenes}
    else:
        allocations=photo_allocation(len(photos_unique))
        scene_labels={}
    if len(set(allocations.values()))!=len(allocations):raise ValueError('PHOTO_REPETEE')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    names=[];audit=[]
    for index in range(1,6):
        filename=f'{index:02d}_anecdote.png'
        # Passer allocation + originaux dédupliqués. La page ne sélectionne jamais toute seule.
        page(fact,index,photos_unique,allocation=allocations,scene_labels=scene_labels).save(folder/filename,format='PNG',optimize=True)
        names.append(filename)
        photo_index=allocations.get(index)
        scene=scene_labels.get(index,{}) if photo_index is not None else {}
        audit.append({'page':index,'image_source_sha256':hashes[photo_index] if photo_index is not None else None,
                      'type_page':'photographie_reelle_unique' if photo_index is not None else 'composition_graphique_sans_photo',
                      'role_visuel':scene.get('role'),'pertinence_editoriale':scene.get('pertinence'),
                      'epoque_reelle':scene.get('epoque'),'titre_commons':scene.get('titre_commons'),
                      'licence':scene.get('licence'),'famille_source':scene.get('famille_source')})
    used=[a['image_source_sha256'] for a in audit if a['image_source_sha256']]
    if len(used)!=len(set(used)):raise ValueError('PHOTO_REPETEE: une photo réutilisée dans le carrousel')
    preview=Image.new('RGB',(5*220,302),'#f0ede8')
    for idx,name in enumerate(names):
        with Image.open(folder/name) as rendered:
            preview.paste(rendered.resize((214,268),Image.Resampling.LANCZOS),(idx*220+3,14))
    preview.save(folder/'apercu.png',format='PNG')
    if audit_path:
        destination=Path(audit_path)
        destination.parent.mkdir(parents=True,exist_ok=True)
        report={'version':VERSION,'fact_id':fact['id'],'pages':audit,
                'photos_recues':len(photos or []),'photos_dedoublonnees':len(photos_unique),
                'photos_utilisees':len(used),'photos_repetees':0,
                'identification_couverture':'ANECDOTE DU 9e ART grand bandeau jaune',
                'narration_verifiee':scenes is not None,
                'etapes_avec_photographie':[p['page'] for p in audit if p['image_source_sha256']],
                'principe':'Aucune image generative, aucune meme photographie sur deux pages.'}
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return names


def caption(fact):
    from marketing_illyadera import cta,tags
    s=story(fact)
    return ('📚 ANECDOTE DU 9e ART — LE SAVAIS-TU ?\n\n'+
            s['hook'].capitalize().rstrip(' .')+'\n\n'+
            s['revelation']+'\n\n'+
            cta('ANECDOTE',s['question'])+' 👇\n\n'+tags('ANECDOTE'))
