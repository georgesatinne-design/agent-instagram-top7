"""Direction artistique « Anecdotes BD / carnet de passionné », version SANS IA.

Toute photographie est issue d'un vrai fichier image vérifié, jamais synthétisée.
Pillow ne fait que cadrer, juxtaposer et ajouter typographie, aplats, trames,
flèches et formes géométriques. Ce n'est pas un moteur génératif.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, math, re
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter
from .catalogue import ROOT_REPO

W,H=1080,1350
VIOLET='#4B2058';NUIT='#220F30';VIOLET2='#643373';JAUNE='#FFE12D';CREME='#FFFAEC';ENCRE='#1F1027'
FONTS_BOLD=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']
FONTS_REG=['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']

def font(n,bold=True):
    for p in (FONTS_BOLD if bold else FONTS_REG):
        if Path(p).is_file():return ImageFont.truetype(p,n)
    return ImageFont.load_default()

def measure(d,s,f):
    a,b,c,e=d.textbbox((0,0),s,font=f);return c-a,e-b

def lines_for(d,s,f,limit):
    chunks=[];part=''
    for word in str(s).split():
        trial=(part+' '+word).strip()
        if measure(d,trial,f)[0]<=limit:part=trial
        else:
            if part:chunks.append(part)
            part=word
    if part:chunks.append(part)
    return chunks

def typography(d,s,width,height,*,start=74,minimum=30,maxlines=6):
    for size in range(start,minimum-1,-2):
        f=font(size);ll=lines_for(d,s,f,width);step=int(size*1.26)
        if len(ll)<=maxlines and len(ll)*step<=height:
            return ll,f,step
    raise ValueError('Texte trop long pour un carrousel lisible; rejet éditorial')

def multiline(d,s,area,*,start=72,minimum=31,maxlines=6,fill=CREME,align='left',stroke=0):
    x,y,w,h=area
    ll,f,step=typography(d,s,w,h,start=start,minimum=minimum,maxlines=maxlines)
    for idx,line in enumerate(ll):
        tx=x if align=='left' else x+w/2
        d.text((tx,y+idx*step),line,font=f,anchor='lt' if align=='left' else 'mt',fill=fill,
               stroke_width=stroke,stroke_fill=VIOLET if stroke else None)
    return len(ll)*step

def crop(photo,rect,zoom=1,anchor=(.5,.5)):
    x,y,w,h=map(int,rect)
    image=ImageOps.exif_transpose(photo).convert('RGB')
    if zoom>1:
        cw=max(1,int(image.width/zoom));ch=max(1,int(image.height/zoom))
        left=int(max(0,min(image.width-cw,(image.width-cw)*anchor[0])))
        top=int(max(0,min(image.height-ch,(image.height-ch)*anchor[1])))
        image=image.crop((left,top,left+cw,top+ch))
    return ImageOps.fit(image,(w,h),method=Image.Resampling.LANCZOS,centering=anchor)

def photo_panel(im,photo,box,outline=JAUNE,width=8,zoom=1,anchor=(.5,.5),shadow=12):
    x,y,w,h=box;d=ImageDraw.Draw(im)
    d.rounded_rectangle((x+shadow,y+shadow,x+w+shadow,y+h+shadow),radius=19,fill=NUIT)
    fitted=crop(photo,(x,y,w,h),zoom=zoom,anchor=anchor)
    mask=Image.new('L',(w,h));ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1),radius=17,fill=255)
    im.paste(fitted,(x,y),mask)
    d.rounded_rectangle((x,y,x+w,y+h),radius=19,outline=outline,width=width)

def dots(d,box,color=JAUNE,step=21,r=3):
    x,y,w,h=box
    for i in range(x,x+w,step):
        for j in range(y,y+h,step):
            d.ellipse((i,j,i+r,j+r),fill=color)

def torn(d,box,fill=JAUNE,seed=0):
    x,y,w,h=box;pts=[]
    for i in range(0,w+1,38):pts.append((x+i,y+(4 if (i//38+seed)%2 else 0)))
    for j in range(0,h+1,31):pts.append((x+w+(5 if (j//31)%2 else 0),y+j))
    for i in range(w,-1,-38):pts.append((x+i,y+h+(3 if (i//38)%2 else 0)))
    for j in range(h,-1,-31):pts.append((x+(4 if (j//31)%2 else 0),y+j))
    d.polygon(pts,fill=fill)

def arrow(d,x,y,fill=JAUNE):
    d.line([(x,y),(x+120,y)],fill=fill,width=11,joint='curve')
    d.polygon([(x+120,y),(x+90,y-23),(x+90,y+23)],fill=fill)

def rounded_overlay(im,box,color,alpha=225,radius=28):
    x,y,w,h=box;layer=Image.new('RGBA',(w,h),(0,0,0,0))
    ImageDraw.Draw(layer).rounded_rectangle((0,0,w-1,h-1),radius=radius,fill=ImageColor(color,alpha))
    im.paste(layer,(x,y),layer)

def ImageColor(hexcode,alpha):
    from PIL import ImageColor as IC
    return (*IC.getrgb(hexcode),alpha)

def cover(im):
    d=ImageDraw.Draw(im);d.rectangle((0,0,W,100),fill=VIOLET)
    d.text((38,45),'LE SAVAIS-TU ?',font=font(49),fill=JAUNE,anchor='lm')
    d.rounded_rectangle((780,21,1040,80),radius=23,fill=JAUNE)
    d.text((911,51),'ANECDOTE BD',font=font(24),fill=VIOLET,anchor='mm')
    d.rectangle((0,H-84,W,H),fill=VIOLET)
    d.text((32,H-44),'CARNET DE PASSIONNÉ',font=font(28),fill=JAUNE,anchor='lm')

def page(fact,number,photos=None):
    if photos is None:
        # Compatibilité des tests de taille. La production `render` exige des vraies photos.
        path=ROOT_REPO/'anecdotes_assets'/'fond_bd_original.jpeg'
        if not path.is_file():raise ValueError('Aucun visuel de prévisualisation')
        photos=[path,path]
    if len(photos)<2:raise ValueError('Au moins deux visuels réels obligatoires')
    opened=[]
    for p in photos:
        if isinstance(p,Image.Image):opened.append(p.copy().convert('RGB'))
        else:
            with Image.open(p) as i:opened.append(i.convert('RGB'))
    p=opened[(number-1)%len(opened)]
    q=opened[number%len(opened)]
    im=Image.new('RGB',(W,H),CREME);d=ImageDraw.Draw(im)
    # Les photos remplissent chacune une grande surface, avec une variation de cadrage.
    if number==1:
        im.paste(crop(p,(0,0,W,H-85),anchor=(.5,.45)),(0,0))
        shade=Image.new('RGBA',(W,620),ImageColor(NUIT,215));im.paste(shade,(0,100),shade)
        d=ImageDraw.Draw(im);cover(im);d=ImageDraw.Draw(im)
        torn(d,(38,166,245,58),fill=JAUNE,seed=1)
        d.text((57,196),'LA PETITE HISTOIRE',font=font(25),fill=VIOLET,anchor='lm')
        main=fact['hook'].strip().rstrip('!?… .')+' ?' if not fact['hook'].endswith(('?','!','…')) else fact['hook']
        multiline(d,main,(54,282,960,380),start=100,minimum=57,maxlines=5,fill=CREME)
        d.rounded_rectangle((45,998,720,1123),radius=23,fill=JAUNE)
        d.text((78,1056),'LA SUITE VA TE SURPRENDRE',font=font(34),fill=VIOLET,anchor='lm')
        arrow(d,865,1070,fill=JAUNE)
    elif number==2:
        d.rectangle((0,0,W,H),fill=CREME)
        photo_panel(im,p,(39,150,998,722),outline=VIOLET,width=7,anchor=(.5,.38))
        d=ImageDraw.Draw(im);d.rectangle((0,0,W,100),fill=VIOLET)
        d.text((40,52),'ET POURTANT…',font=font(53),fill=JAUNE,anchor='lm')
        torn(d,(55,720,420,68),fill=JAUNE,seed=2)
        d.text((78,755),'LE FAIT',font=font(42),fill=VIOLET,anchor='lm')
        d.rounded_rectangle((52,811,1025,1200),radius=25,fill=VIOLET)
        multiline(d,fact['fait'],(82,851,914,310),start=69,minimum=34,maxlines=6,fill=CREME)
        arrow(d,849,1262,fill=VIOLET)
    elif number==3:
        d.rectangle((0,0,W,H),fill=VIOLET)
        d.text((52,55),'RETOUR EN ARRIÈRE',font=font(57),fill=JAUNE,anchor='lt')
        photo_panel(im,q,(36,160,615,875),outline=CREME,width=7,zoom=1.08,anchor=(.4,.5))
        photo_panel(im,p,(580,570,460,610),outline=JAUNE,width=8,zoom=1.25,anchor=(.65,.5))
        d=ImageDraw.Draw(im);rounded_overlay(im,(374,245,636,400),VIOLET,243,radius=22);d=ImageDraw.Draw(im)
        d.rounded_rectangle((372,245,1010,645),radius=22,outline=JAUNE,width=5)
        multiline(d,fact['contexte'],(400,281,578,325),start=61,minimum=33,maxlines=7,fill=CREME)
        d.rounded_rectangle((70,1125,590,1224),radius=17,fill=JAUNE)
        d.text((98,1175),'CE N’EST PAS FINI…',font=font(31),fill=VIOLET,anchor='lm')
    elif number==4:
        im.paste(crop(p,(0,0,W,H),zoom=1.16,anchor=(.6,.45)),(0,0))
        cover(im);d=ImageDraw.Draw(im)
        d.rounded_rectangle((46,170,1034,690),radius=28,fill=NUIT,outline=JAUNE,width=7)
        torn(d,(67,191,330,72),fill=JAUNE,seed=3)
        d.text((92,225),'LE DÉTAIL QUI CHANGE TOUT',font=font(25),fill=VIOLET,anchor='lm')
        multiline(d,fact['detail'],(81,295,906,340),start=82,minimum=35,maxlines=6,fill=CREME)
        d.rounded_rectangle((310,1129,1030,1233),radius=19,fill=JAUNE)
        d.text((334,1180),'UNE HISTOIRE, DEUX ÉPOQUES…',font=font(29),fill=VIOLET,anchor='lm')
    else:
        im.paste(crop(p,(0,0,W,H),anchor=(.45,.43)),(0,0))
        d=ImageDraw.Draw(im);d.rectangle((0,0,W,100),fill=VIOLET)
        d.text((37,52),'ET TOI, TU SAVAIS ?',font=font(52),fill=JAUNE,anchor='lm')
        rounded_overlay(im,(54,235,966,445),NUIT,235,radius=30);d=ImageDraw.Draw(im)
        d.rounded_rectangle((54,235,1020,680),radius=30,outline=JAUNE,width=7)
        question=fact.get('question') or 'Tu connaissais cette histoire ?'
        multiline(d,question,(92,307,888,310),start=86,minimum=48,maxlines=5,fill=CREME)
        torn(d,(56,940,952,168),fill=JAUNE,seed=5)
        multiline(d,'VIENS EN PARLER EN COMMENTAIRE !',(87,995,890,78),start=44,minimum=35,maxlines=2,fill=VIOLET)
        d.rectangle((0,H-84,W,H),fill=VIOLET)
    d=ImageDraw.Draw(im)
    # Footer avec pagination discrète et une ligne de progression.
    d.rounded_rectangle((23,H-76,1057,H-13),radius=15,fill=VIOLET)
    d.text((46,H-44),'ANECDOTE BD',font=font(27),fill=JAUNE,anchor='lm')
    d.text((1036,H-44),f'{number}/5',font=font(30),fill=JAUNE,anchor='rm')
    d.rectangle((0,H-8,int(W*number/5),H),fill=JAUNE)
    for item in opened:item.close()
    return im

def render(fact,folder,photos=None):
    if photos is None or len(photos)<2:
        raise ValueError('REFUS PUBLICATION: au moins deux photos réelles approuvées requises')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    files=[]
    for number in range(1,6):
        image=page(fact,number,photos=photos)
        name=f'{number:02d}_anecdote.png';image.save(folder/name,optimize=True);files.append(name)
    overview=Image.new('RGB',(5*230,315),'#eeeeee')
    for j,name in enumerate(files):
        with Image.open(folder/name) as im:
            im.thumbnail((224,295));overview.paste(im,(j*230+3,8))
    overview.save(folder/'apercu.png',optimize=True)
    return files

def caption(fact):
    # Une voix humaine, chaleureuse et brève, sans écrire de nouveau fait invérifiable.
    text=('📚 ANECDOTE BD — LE SAVAIS-TU ?\n\n'
          +fact['hook'].strip()+'\n\n'+fact['fait'].strip()+'\n\n'
          +(fact.get('question') or 'Tu connaissais cette histoire ?')+' 👇\n\n'
          +'#BandeDessinee #BD #9eArt #PassionBD')
    if len(text)>2200:raise ValueError('Légende trop longue')
    return text
