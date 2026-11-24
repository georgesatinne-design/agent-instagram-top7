"""Cinq pages Instagram originales: trame BD utilisateur, violet / jaune.
Aucune image tierce ni illustration éditoriale sous licence n'est reprise.
"""
from __future__ import annotations
import hashlib,math,textwrap
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps,ImageEnhance
from .catalogue import ROOT_REPO,ROOT
W,H=1080,1350
PURPLE='#63366F';DARK='#44204E';YELLOW='#FFE82C';WHITE='#FFFFFF';PAPER='#FBF9FA';INK='#311637'

FONT_BOLD=[
 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
 '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
 '/usr/share/fonts/truetype/lato/Lato-Bold.ttf',
]
FONT_REG=[
 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
 '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
 '/usr/share/fonts/truetype/lato/Lato-Regular.ttf',
]

def font(sz,bold=True):
    for f in FONT_BOLD if bold else FONT_REG:
        if Path(f).is_file():return ImageFont.truetype(f,sz)
    return ImageFont.load_default()

def textbbox(draw,text,f):
    x0,y0,x1,y1=draw.textbbox((0,0),text,font=f)
    return x1-x0,y1-y0

def wrap(draw,text,f,width):
    words=text.split();lines=[];line=''
    for word in words:
        trial=(line+' '+word).strip()
        if textbbox(draw,trial,f)[0]<=width:line=trial
        else:
            if line:lines.append(line)
            line=word
    if line:lines.append(line)
    return lines

def fit_text(draw,text,max_width,max_height,start=72,min_size=27,max_lines=6):
    for s in range(start,min_size-1,-2):
        f=font(s,True);lines=wrap(draw,text,f,max_width);lh=int(s*1.27)
        if len(lines)<=max_lines and len(lines)*lh<=max_height:return lines,f,lh
    f=font(min_size,True);return wrap(draw,text,f,max_width),f,int(min_size*1.27)

def text_center(draw,lines,f,lh,cx,cy,fill):
    top=cy-len(lines)*lh/2
    for i,line in enumerate(lines):
        draw.text((cx,top+i*lh+lh/2),line,font=f,anchor='mm',fill=fill)

def base(seed=0):
    asset=ROOT_REPO/'anecdotes_assets'/'fond_bd_original.jpeg'
    if asset.is_file():
        with Image.open(asset) as i:
            bg=ImageOps.fit(i.convert('RGB'),(W,H),method=Image.Resampling.BICUBIC)
        bg=ImageEnhance.Contrast(bg).enhance(.8)
    else:bg=Image.new('RGB',(W,H),PAPER)
    tint=Image.new('RGBA',(W,H),'#ffffff')
    tint.putalpha(125)
    bg=Image.alpha_composite(bg.convert('RGBA'),tint)
    d=ImageDraw.Draw(bg)
    # A discreet halftone rhythm, with accent arcs but no third-party artwork.
    for n in range(0,160,13):
        x=(n*43+seed*13)%W;y=(n*67+seed*29)%H
        d.ellipse((x,y,x+3+(n%3),y+3+(n%3)),fill='#765581')
    return bg.convert('RGB')

def chrome(im,number,category):
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((16,45,1064,190),radius=12,fill=PURPLE)
    d.text((540,113),'LE SAVAIS-TU ?',font=font(67),fill=YELLOW,anchor='mm')
    d.rounded_rectangle((15,1268,1065,1341),radius=10,fill=PURPLE)
    d.text((33,1304),'ANECDOTE BD',font=font(31),fill=YELLOW,anchor='lm')
    d.text((1040,1304),f'{number}/5',font=font(28),fill=YELLOW,anchor='rm')
    d.rounded_rectangle((43,208,1037,1243),radius=27,fill=WHITE,outline=PURPLE,width=5)
    d.ellipse((55,230,180,355),fill=YELLOW,outline=PURPLE,width=4)
    d.text((117,291),str(number),font=font(70),fill=PURPLE,anchor='mm')
    d.rounded_rectangle((760,237,1012,299),radius=30,fill=PURPLE)
    cat=category.upper()[:17]
    f=font(18);lines=wrap(d,cat,f,232)
    text_center(d,lines,f,24,886,267,WHITE)
    return d

def page(fact,number):
    im=base(sum(map(ord,fact['id']))%99);d=chrome(im,number,fact['theme'])
    if number==1:
        d.rounded_rectangle((75,475,1007,988),radius=34,fill=PURPLE)
        d.text((540,513),'L’ANECDOTE DU JOUR',anchor='mm',font=font(34),fill=YELLOW)
        lines,f,lh=fit_text(d,fact['hook'],810,330,start=76,min_size=38,max_lines=6)
        text_center(d,lines,f,lh,540,737,WHITE)
        d.text((540,1093),'FAIS GLISSER POUR DÉCOUVRIR',font=font(26),fill=DARK,anchor='mm')
        d.line((320,1144,755,1144),fill=PURPLE,width=5)
        d.polygon([(782,1144),(743,1121),(743,1167)],fill=PURPLE)
    elif number in (2,3,4):
        tag={2:'LE FAIT',3:'LE CONTEXTE',4:'LE DÉTAIL'}[number]
        msg={2:fact['fait'],3:fact['contexte'],4:fact['detail']}[number]
        d.text((540,416),tag,font=font(58),fill=PURPLE,anchor='mm')
        d.rounded_rectangle((96,476,989,1010),radius=30,fill='#F3ECF5',outline=PURPLE,width=3)
        lines,f,lh=fit_text(d,msg,795,430,start=62,min_size=31,max_lines=8)
        text_center(d,lines,f,lh,542,740,DARK)
        d.ellipse((448,1100,633,1124),fill=YELLOW)
        d.text((540,1180),'LA BD A TANT D’HISTOIRES…',font=font(23),fill=PURPLE,anchor='mm')
    else:
        d.text((540,488),'À TOI DE JOUER !',font=font(59),fill=PURPLE,anchor='mm')
        d.rounded_rectangle((105,558,972,943),radius=38,fill=YELLOW,outline=PURPLE,width=4)
        question=fact.get('question') or 'Tu connaissais cette anecdote ?'
        lines,f,lh=fit_text(d,question,750,280,start=60,min_size=36,max_lines=6)
        text_center(d,lines,f,lh,540,753,DARK)
        d.text((540,1075),'RACONTE-NOUS EN COMMENTAIRE',font=font(31),fill=PURPLE,anchor='mm')
        d.text((540,1143),'ET SUIS-NOUS POUR LA PROCHAINE !',font=font(26),fill=PURPLE,anchor='mm')
    return im

def render(fact,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    files=[]
    for i in range(1,6):
        im=page(fact,i);p=f'{i:02d}_anecdote.png';im.save(folder/p,optimize=True);files.append(p)
    preview=Image.new('RGB',(5*235,310),'#eae8ec')
    for i,p in enumerate(files):
        with Image.open(folder/p) as img:
            img.thumbnail((226,284))
            preview.paste(img,(i*235+4,8))
    preview.save(folder/'apercu.png',optimize=True)
    return files

def caption(fact):
    output=('📚 ANECDOTE BD — LE SAVAIS-TU ?\n\n'
       +fact['fait']+'\n\n'+fact['contexte']+'\n\n'
       +(fact.get('question') or 'Tu connaissais cette anecdote ?')+' 👇\n\n'
       +'#BandeDessinee #BD #9eArt #LeSaviezVous')
    if len(output)>2200:raise ValueError('Légende trop longue')
    return output
