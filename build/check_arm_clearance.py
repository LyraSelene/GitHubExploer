"""Check the rendered alpha against conservative source-pixel obstacles.

Uses the rig parameters exported from actions.js by Node; draws the same
inverse warp as scene.js. This is geometry QA, not a performance benchmark.
"""
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
config = json.loads((root / 'build/arm-geometry.json').read_text())
sprite = np.array(Image.open(root / 'static/forearm-layer.png').convert('RGBA'))
base = np.array(Image.open(root / 'static/wallpaper-rig-base.png').convert('RGB'))
original = np.array(Image.open(root / 'static/wallpaper.webp').convert('RGB'))
h, w = base.shape[:2]
# Expanded left/top outline of the actual fin; include the tail below it.
fin = [(2004,774),(2020,795),(2058,827),(2098,852),(2110,875),
       (2150,865),(2205,884),(2260,884),(2265,900),(2240,930),
       (2200,952),(2112,970),(2080,1000),(2048,1035),(1990,1080),
       (1860,1120),(1840,1070),(1950,1015),(2010,945),(2000,920),
       (1984,877),(1985,828)]
obstacle = Image.new('L', (w,h));d=ImageDraw.Draw(obstacle)
d.polygon(fin, fill=255)
# Dress edge deliberately expanded into the water to leave a safety gap.
d.polygon([(0,765),(1715,765),(1740,900),(1790,1020),(1790,h),(0,h)],fill=255)
blocked = np.array(obstacle)>0
yy,xx=np.mgrid[:h,:w].astype(np.float32)
px,py=config['rig']['pivot'];j0,j1=config['rig']['joint']
dx,dy=xx-px,yy-py
q=np.clip((np.hypot(dx,dy)-j0)/(j1-j0),0,1);joint=q*q*(3-2*q)
distance=cv2.distanceTransform((~blocked).astype(np.uint8),cv2.DIST_L2,5)
minimum=1000.;frames=[]
for i,pose in enumerate(config['poses']):
    angle=pose['arm']
    a=angle*joint
    sx=px+np.cos(a)*dx-np.sin(a)*dy;sy=py+np.sin(a)*dx+np.cos(a)*dy
    wx,wy=config['rig']['wrist'];w0,w1=config['rig']['wristBlend']
    q=np.clip((sy-w0)/(w1-w0),0,1);wa=pose['wrist']*q*q*(3-2*q)
    ddx,ddy=sx-wx,sy-wy
    sx=wx+np.cos(wa)*ddx-np.sin(wa)*ddy;sy=wy+np.sin(wa)*ddx+np.cos(wa)*ddy
    moved=cv2.remap(sprite,sx,sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    opacity=moved[:,:,3:4]/255.
    composed=np.clip(base*(1-opacity)+moved[:,:,:3]*opacity,0,255).astype(np.uint8)
    # A sleeve anchor must remain painted continuously, at every extreme.
    assert np.max(np.abs(composed[680:690,1760:1790].astype(int)-original[680:690,1760:1790].astype(int)))<=1,'Sleeve anchor gap or movement'
    occupied=moved[:,:,3]>10
    assert not np.any(occupied&blocked),f'Arm intersects obstacle at angle {angle}'
    minimum=min(minimum,float(distance[occupied].min()))
    if i in [0,30,60,90,122]:
        f=Image.fromarray(composed).crop((1670,630,2120,1000)).resize((540,444))
        ImageDraw.Draw(f).text((8,8),f'angle {angle:.3f} rad',fill='black');frames.append(f)
assert minimum>=8,f'Insufficient clearance: {minimum}'
sheet=Image.new('RGB',(540*len(frames),444))
for i,f in enumerate(frames):sheet.paste(f,(i*540,0))
sheet.save(root/'build/arm-safe-extremes.jpg')
print(f'{len(config["poses"])} arm/wrist poses at 100% strength: no obstacle overlap; minimum conservative clearance {minimum:.1f} source pixels.')
