"""Свой тайлер: режет world25.jpg в пирамиду 256-тайлов {z}/{x}/{y}.webp (без vips).
WebP q84 — резче и на ~20% легче JPEG q82."""
import math, os, sys
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
SRC=sys.argv[1] if len(sys.argv)>1 else 'worldgen/world25.jpg'
OUT=sys.argv[2] if len(sys.argv)>2 else 'worldgen/maptest/tiles'
TILE=256; SEA=(22,33,52)
img=Image.open(SRC).convert('RGB'); W,H=img.size
maxZoom=math.ceil(math.log2(max(W,H)/TILE))
print('мир',W,'x',H,' maxZoom',maxZoom)
total=0
for z in range(maxZoom,-1,-1):
    sc=2**(z-maxZoom); zw,zh=max(1,round(W*sc)),max(1,round(H*sc))
    zimg=img if z==maxZoom else img.resize((zw,zh),Image.LANCZOS)
    nx,ny=math.ceil(zw/TILE),math.ceil(zh/TILE)
    for tx in range(nx):
        d=f'{OUT}/{z}/{tx}'; os.makedirs(d,exist_ok=True)
        for ty in range(ny):
            t=zimg.crop((tx*TILE,ty*TILE,tx*TILE+TILE,ty*TILE+TILE))
            if t.size!=(TILE,TILE):
                bg=Image.new('RGB',(TILE,TILE),SEA); bg.paste(t,(0,0)); t=bg
            t.save(f'{d}/{ty}.webp','WEBP',quality=84,method=4); total+=1
    print(f'  z{z}: {nx}x{ny}')
print('тайлов', total, '| maxZoom', maxZoom, '| мир', W, 'x', H)
# meta.json рядом с тайлами (на будущее; страница сейчас знает размеры константами)
import json
meta = os.path.join(OUT, 'meta.json') if os.path.isdir(OUT) else None
if meta:
    json.dump({'maxZoom': maxZoom, 'W': W, 'H': H}, open(meta, 'w'))
