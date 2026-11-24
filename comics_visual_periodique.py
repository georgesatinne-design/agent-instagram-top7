"""Rendu comics seul: six pages hebdo, huit pages mensuelles, charte rouge originale.
Ne modifie pas visual_top7.py (BD et MANGA continuent inchangés).
"""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image,ImageDraw
from visual_top7 import (font,label,pill,base_image,style_for_category,
  draw_text_center,draw_top_rank_circle,paste_cover_fit,movement_state)
from sources.couvertures import cover_path

ROOT=Path(__file__).resolve().parent
CHARTE=ROOT/'templates'/'charte_top7.json'
W,H=1080,1350

def ordered_names(n):return [f'{i:02d}_rang_{n-i+1}.png' for i in range(1,n+1)]+[f'{n+1:02d}_recapitulatif.png']

def render(data,folder,covers,*,watermark=False):
    n=5 if data['cadence']=='HEBDO' else 7
    top=sorted(data['titres'],key=lambda x:x['rang'])
    if len(top)!=n or [b['rang'] for b in top]!=list(range(1,n+1)):
        raise ValueError('Classement de rangs incomplet')
    chart=json.loads(CHARTE.read_text(encoding='utf8'))
    style,background=style_for_category('COMICS',chart)
    red=style['violet'];cream=style['jaune'];yellow=style['rond'];ink=style['encre'];white=style['blanc']
    evo={**chart['evolution'],'nouveau':red}
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    files=[];missing=[];date_line=data['periode_label'].upper();movements=bool(data.get('variations_verifiees'))
    def footer(im,idx):
        pill(im,(16,1261,1064,1343),red,radius=10)
        d=ImageDraw.Draw(im)
        d.text((34,1267),f'TOP {n} DES VENTES • COMICS',font=font(29,True),fill=cream)
        f=font(21 if len(date_line)<42 else 17,True)
        d.text((35,1308),date_line,font=f,fill=cream)
        d.text((1045,1280),f'{idx}/{n+1}',font=font(25,True),fill=cream,anchor='ra')
        if watermark:d.text((540,1248),'DÉMONSTRATION • PAS POUR PUBLICATION',font=font(18,True),fill=red,anchor='mm')
    for idx,b in enumerate(reversed(top),1):
        im=base_image(background);d=ImageDraw.Draw(im)
        pill(im,(16,55,1064,178),red,radius=6)
        rows,f,lh=label(b['titre'],970,108,start=64,minimum=26,draw=d)
        size=len(rows)*lh
        for j,r in enumerate(rows):draw_text_center(d,(540,115-size/2+j*lh+lh/2),r,f.size,cream)
        pill(im,(292,186,788,228),white,stroke=red,radius=12)
        publisher='ÉDITEUR : '+b['editeur']
        draw_text_center(d,(540,207),publisher,22 if len(publisher)<35 else 17,red)
        pill(im,(147,237,939,1146),white,stroke=red,radius=8)
        filename=cover_path(covers,b['titre'])
        if filename.exists():
            try:
                with Image.open(filename) as cover:paste_cover_fit(im,cover.convert('RGB'),(155,245,931,1138))
            except Exception:missing.append(b['titre'])
        else:missing.append(b['titre'])
        if b['titre'] in missing:
            d=ImageDraw.Draw(im);d.multiline_text((542,650),'COUVERTURE\nNON DISPONIBLE',font=font(44,True),fill=red,anchor='mm',align='center',spacing=7)
        d=ImageDraw.Draw(im);draw_top_rank_circle(d,(20,555,330,865),b['rang'],yellow,red)
        short,compact,state=movement_state(b,movements)
        color=evo[state]
        pill(im,(540,1158,1064,1240),white,stroke=color,radius=19)
        draw_text_center(ImageDraw.Draw(im),(802,1198),short,26 if len(short)>20 else 32,color)
        footer(im,idx)
        name=f'{idx:02d}_rang_{b["rang"]}.png';im.save(folder/name,optimize=True);files.append(name)
    # Page de synthèse: hauteur variable selon cinq ou sept entrées.
    im=base_image(background);d=ImageDraw.Draw(im)
    pill(im,(16,50,1064,192),red,radius=8)
    draw_text_center(d,(540,122),f'TOP {n} • RÉCAPITULATIF',60,cream)
    pill(im,(42,211,1038,1214),red,radius=24)
    step=135 if n==7 else 187
    first=238 if n==7 else 246
    rowheight=115 if n==7 else 161
    for i,b in enumerate(top):
        y=first+i*step
        pill(im,(67,y,1013,y+rowheight),white,radius=14)
        d=ImageDraw.Draw(im)
        circle=91 if n==7 else 114
        draw_top_rank_circle(d,(84,y+(rowheight-circle)//2,84+circle,y+(rowheight+circle)//2),b['rang'],yellow,red)
        max_h=64 if n==7 else 83
        rows,f,lh=label(b['titre'],580,max_h,start=36 if n==7 else 39,minimum=17,draw=d)
        center_y=y+rowheight/2-18
        for j,line in enumerate(rows):d.text((203,int(center_y-len(rows)*lh/2+j*lh)),line,font=f,fill=ink)
        d.text((203,y+rowheight-31),f'Éditeur : {b["editeur"]}',font=font(18,True),fill=red)
        short,compact,state=movement_state(b,movements)
        pill(im,(803,y+(rowheight-54)//2,998,y+(rowheight+54)//2),white,stroke=evo[state],radius=14)
        draw_text_center(ImageDraw.Draw(im),(900,y+rowheight//2),compact,24 if len(compact)<=7 else 16,evo[state])
    footer(im,n+1);last=f'{n+1:02d}_recapitulatif.png';im.save(folder/last,optimize=True);files.append(last)
    caption=f'📚 TOP {n} COMICS — Les meilleures ventes\n📅 {data["periode_label"]}\n\n'
    for b in top:
        m=movement_state(b,movements)[0]
        caption+=f'#{b["rang"]} {b["titre"]} — {b["editeur"]}'
        if m!='ÉVOLUTION NON DISPONIBLE':caption+=' ('+m+')'
        caption+='\n'
    caption+='\nEt toi, lequel as-tu lu ? 👇\n\n#Comics #ClassementComics #Lecture\n'
    (folder/'legende_instagram.txt').write_text(caption,encoding='utf8')
    preview=Image.new('RGB',(4*282,2*364),'#e6e3ec')
    for i,p in enumerate(files):
        with Image.open(folder/p) as x:
            x=x.copy();x.thumbnail((270,338))
            preview.paste(x,((i%4)*282+6,(i//4)*364+6))
    preview.save(folder/'apercu.png')
    return {'pages':len(files),'files':files,'missing':missing}
