"""Studio BD / STOR Y V3 — collage photo authentique, typographie, mouvement.
AUCUNE création de photo par IA : seules les photos déjà approuvées sont utilisées.
Graphisme par Pillow : fonds, cercles, bandes, flèches et coupes de photos réelles.
"""
from __future__ import annotations
from pathlib import Path
import math,re,hashlib
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from .catalogue import ROOT_REPO
from .storytelling import story

W,H=1080,1350
NIGHT='#23122D'; PURPLE='#422052'; INK='#1B1121'; CREAM='#FFF8E8'; YELLOW='#FFDE2A'; CORAL='#F96B59'; MINT='#6FDEB7'
FONT_BOLD=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']
FONT_NORM=['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']

def font(n,bold=True):
    for p in (FONT_BOLD if bold else FONT_NORM):
        if Path(p).is_file():return ImageFont.truetype(p,n)
    return ImageFont.load_default()

def box_text(d, text, box, *, desired=70, smallest=29, max_lines=6, fill=INK, align='left', leading=1.22):
    x,y,w,h=box
    text=re.sub(r'\s+',' ',text or '').strip()
    if not text:raise ValueError('Texte vide')
    for size in range(desired,smallest-1,-2):
        f=font(size); lines=[]; words=text.split(); line=''
        for word in words:
            candidate=(line+' '+word).strip()
            if d.textbbox((0,0),candidate,font=f)[2]<=w:line=candidate
            else:
                if line:lines.append(line)
                line=word
        if line:lines.append(line)
        line_h=int(size*leading)
        if len(lines)<=max_lines and line_h*len(lines)<=h and all(d.textbbox((0,0),li,font=f)[2]<=w for li in lines):break
    else:raise ValueError('Texte ne tient pas sur la diapositive: '+text[:70])
    for i,line in enumerate(lines):
        if align=='center':d.text((x+w//2,y+i*line_h),line,font=f,anchor='mt',fill=fill)
        else:d.text((x,y+i*line_h),line,font=f,anchor='lt',fill=fill)
    return line_h*len(lines)

def photo_fit(src,w,h,centering=(.5,.5),zoom=1):
    im=src.convert('RGB')
    if zoom>1:
        cw=int(im.width/zoom);ch=int(im.height/zoom)
        le=int((im.width-cw)*centering[0]);top=int((im.height-ch)*centering[1])
        im=im.crop((le,top,le+cw,top+ch))
    return ImageOps.fit(im,(int(w),int(h)),Image.Resampling.LANCZOS,centering=centering)

def inset_photo(im,src,xywh,*,outline=CREAM,border=7,center=(.5,.5),zoom=1,rounding=22):
    x,y,w,h=xywh
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((x+15,y+18,x+w+15,y+h+18),radius=rounding,fill=NIGHT)
    p=photo_fit(src,w,h,center,zoom)
    mask=Image.new('L',(w,h)); ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=rounding,fill=255)
    im.paste(p,(x,y),mask)
    ImageDraw.Draw(im).rounded_rectangle((x,y,x+w,y+h),radius=rounding,outline=outline,width=border)

def polygon(im,points,color):ImageDraw.Draw(im).polygon(points,fill=color)

def label(im,text,x,y,*,bg=YELLOW,fg=NIGHT,size=27,padx=22,pady=13):
    d=ImageDraw.Draw(im);f=font(size)
    bb=d.textbbox((0,0),text,font=f);w=bb[2]+padx*2;h=bb[3]-bb[1]+pady*2
    d.rounded_rectangle((x,y,x+w,y+h),radius=12,fill=bg)
    d.text((x+padx,y+pady-2),text,font=f,fill=fg,anchor='lt')
    return (w,h)

def starburst(im,x,y,r,color):
    points=[]
    for i in range(24):
        theta=i*math.pi/12;rr=r if i%2==0 else r*.72
        points.append((int(x+rr*math.cos(theta)),int(y+rr*math.sin(theta))))
    polygon(im,points,color)

def scribble(im,x,y,color=YELLOW):
    d=ImageDraw.Draw(im)
    d.arc((x,y,x+185,y+78),10,170,fill=color,width=13)
    d.arc((x+15,y+13,x+207,y+93),10,155,fill=color,width=6)

def footer(im,n):
    d=ImageDraw.Draw(im)
    d.rectangle((0,H-80,W,H),fill=NIGHT)
    d.text((42,H-43),'LE SAVOIR EN BULLES',font=font(25),fill=CREAM,anchor='lm')
    d.text((1030,H-43),f'{n}/5',font=font(28),fill=YELLOW,anchor='rm')
    d.rectangle((0,H-8,int(W*n/5),H),fill=YELLOW)

def faint_halftone(im,area,color=YELLOW,spacing=28):
    x,y,w,h=area;d=ImageDraw.Draw(im)
    for yi in range(y,y+h,spacing):
        for xi in range(x+(yi//spacing%2)*11,x+w,spacing):d.ellipse((xi,yi,xi+3,yi+3),fill=color)

def gradient(im,box,start,finish,vertical=True):
    from PIL import ImageColor
    sx=ImageColor.getrgb(start);ex=ImageColor.getrgb(finish)
    x,y,w,h=box
    grad=Image.new('RGB',(w,h));d=ImageDraw.Draw(grad)
    total=h if vertical else w
    for a in range(total):
        t=a/max(1,total-1)
        c=tuple(round(s*(1-t)+e*t) for s,e in zip(sx,ex))
        if vertical:d.line((0,a,w,a),fill=c)
        else:d.line((a,0,a,h),fill=c)
    im.paste(grad,(x,y))

def finish(im,n):
    # One visual accent + small footer, not a repetitious top banner on every page.
    footer(im,n)
    return im

def load_photos(photos):
    opened=[]
    for p in photos:
        if isinstance(p,Image.Image):opened.append(p.convert('RGB').copy())
        else:
            with Image.open(p) as img:opened.append(img.convert('RGB').copy())
    return opened

def page(fact,number,photos=None):
    if photos is None:
        # Preview/test fallback ONLY, production render() requires genuine approved images.
        path=ROOT_REPO/'anecdotes_assets'/'fond_bd_original.jpeg'
        if not path.exists():raise ValueError('Aucune photo pour la maquette')
        photos=[path]
    if not photos or number not in range(1,6):raise ValueError('Photo authentique et page 1..5 requises')
    opened=load_photos(photos)
    a=opened[0];b=opened[-1];s=story(fact)
    variant=int(hashlib.sha256(fact['id'].encode()).hexdigest()[:4],16)%3
    accent=[CORAL,MINT,YELLOW][variant]
    im=Image.new('RGB',(W,H),CREAM)
    d=ImageDraw.Draw(im)
    if number==1:
        # Cinéma: la photo frappe d'abord, bande titre plus bas, grande question.
        if variant==1:
            # Full-bleed tall portrait, editorial magazine overlap at the bottom.
            im.paste(photo_fit(a,W,H,zoom=1.1),(0,0))
            gradient(im,(0,780,W,H-780),PURPLE,NIGHT)
        elif variant==2:
            # Narrower crop at the right, bold negative-space panel on the left.
            im.paste(photo_fit(a,W,H,centering=(.68,.5),zoom=1.18),(0,0))
            gradient(im,(0,825,W,525),NIGHT,PURPLE)
        else:
            im.paste(photo_fit(a,W,830,zoom=1.03),(0,0))
            gradient(im,(0,825,W,525),NIGHT,PURPLE)
        d=ImageDraw.Draw(im)
        d.rectangle((0,0,14,1260),fill=YELLOW)
        label(im,'ANECDOTE  /  9e ART',44,45,bg=YELLOW,fg=NIGHT,size=25)
        d.rounded_rectangle((66,700,1010,759),radius=9,fill=accent)
        d.text((91,728),'IL Y A UN DÉTAIL QUE J’ADORE…',font=font(25),fill=NIGHT,anchor='lm')
        box_text(d,s['hook'],(62,815,950,320),desired=83,smallest=43,max_lines=5,fill=CREAM)
        d.text((73,1180),'GLISSE POUR VOIR  →',font=font(29),fill=YELLOW)
        scribble(im,790,1160)
    elif number==2:
        # Brutal contrast: a large diagonally cropped photo, then one punchy fact.
        im.paste(photo_fit(a,W,820,centering=(.5,.45)),(0,0))
        polygon(im,[(0,685),(W,526),(W,1300),(0,1300)],NIGHT)
        d=ImageDraw.Draw(im)
        label(im,'OK, MAIS ÉCOUTE ÇA…',65,70,bg=YELLOW,size=28)
        d.text((42,621),'02',font=font(164),fill=accent)
        d.line((70,798,850,798),fill=YELLOW,width=8)
        box_text(d,s['revelation'],(70,840,940,310),desired=76,smallest=38,max_lines=5,fill=CREAM)
        d.text((70,1191),'ET L’HISTOIRE NE S’ARRÊTE PAS LÀ  →',font=font(22),fill=accent)
    elif number==3:
        # A magazine spread: different crops, overlapping panels, no repeated header.
        d.rectangle((0,0,W,H),fill=CREAM)
        if variant==1:
            inset_photo(im,b,(390,98,625,740),outline=NIGHT,border=7,center=(.53,.37),zoom=1.08)
            inset_photo(im,a,(48,310,410,662),outline=YELLOW,border=9,center=(.42,.52),zoom=1.20)
        else:
            inset_photo(im,b,(48,98,595,740),outline=NIGHT,border=7,center=(.48,.37),zoom=1.08)
            inset_photo(im,a,(615,310,414,662),outline=YELLOW,border=9,center=(.64,.52),zoom=1.20)
        d=ImageDraw.Draw(im)
        d.rounded_rectangle((36,35,640,126),radius=14,fill=NIGHT)
        d.text((61,80),'RETOUR EN ARRIÈRE',font=font(40),fill=YELLOW,anchor='lm')
        d.rectangle((36,922,1040,1225),fill=PURPLE)
        label(im,s['transition'].upper()[:45],68,886,bg=accent,fg=NIGHT,size=22)
        box_text(ImageDraw.Draw(im),s['contexte'],(69,975,940,192),desired=58,smallest=34,max_lines=4,fill=CREAM)
    elif number==4:
        # Close-up: one authentic photograph shown twice with a crop; no invented graphic.
        d.rectangle((0,0,W,H),fill=NIGHT)
        inset_photo(im,a,(0,0,W,750),outline=NIGHT,border=0,center=(.5,.46),zoom=1.17,rounding=0)
        inset_photo(im,b,(655,445,374,374),outline=YELLOW,border=13,center=(.65,.52),zoom=1.9,rounding=185)
        d=ImageDraw.Draw(im)
        starburst(im,150,725,135,accent)
        d.text((150,720),'OH !',font=font(54),fill=NIGHT,anchor='mm')
        d.rectangle((0,860,W,1270),fill=NIGHT)
        d.text((64,876),'LE DÉTAIL QUI RESTE',font=font(33),fill=YELLOW)
        box_text(d,s['detail'],(64,955,930,242),desired=76,smallest=40,max_lines=4,fill=CREAM)
        d.line((65,1224,440,1224),fill=accent,width=12)
    else:
        # Sincere human CTA; a question, not a corporate call-to-action.
        im.paste(photo_fit(b,W,H,zoom=1.08),(0,0))
        gradient(im,(0,660,W,690),PURPLE,NIGHT)
        d=ImageDraw.Draw(im)
        label(im,'MOI, ÇA M’A DONNÉ ENVIE D’EN SAVOIR PLUS',35,46,bg=YELLOW,size=21)
        d.rounded_rectangle((34,730,1048,1110),radius=28,fill=CREAM)
        box_text(d,s['question'],(73,774,935,260),desired=84,smallest=46,max_lines=4,fill=NIGHT)
        d.text((70,1138),'RACONTE-MOI EN COMMENTAIRE  ↓',font=font(31),fill=YELLOW)
        faint_halftone(im,(70,1185,880,60),color=accent,spacing=19)
    return finish(im,number)

def render(fact,folder,photos=None):
    if not photos:raise ValueError('REFUS PUBLICATION: une ou plusieurs photos réelles validées requises')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    out=[]
    for n in range(1,6):
        filename=f'{n:02d}_anecdote.png'
        page(fact,n,photos).save(folder/filename,format='PNG',optimize=True)
        out.append(filename)
    preview=Image.new('RGB',(5*220,302),'#f1eee8')
    for i,name in enumerate(out):
        with Image.open(folder/name) as img:
            preview.paste(img.resize((214,268),Image.Resampling.LANCZOS),(i*220+3,14))
    preview.save(folder/'apercu.png')
    return out

def caption(fact):
    s=story(fact)
    return ('📚 ANECDOTE BD — LE SAVAIS-TU ?\n\n'+
        s['hook'].capitalize().rstrip(' .')+'\n\n'+
        s['revelation']+'\n\n'+
        s['question']+' 👇\n\n#BandeDessinee #BD #9eArt #PassionBD')
