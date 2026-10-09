"""Non-generative extraction and background repair for a small forearm rig."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
root=Path(__file__).resolve().parents[1]
im=Image.open(root/'static/wallpaper.webp').convert('RGB')
# Hand-traced outline in the 340 x 420 reference crop at (1660,560).
outline=[(91,113),(149,115),(157,137),(156,158),(173,188),(203,192),(215,215),(239,233),(244,239),(235,254),(237,262),(225,268),(237,286),(249,309),(255,330),(264,342),(260,346),(249,343),(237,324),(238,348),(246,365),(257,384),(251,392),(243,386),(234,370),(222,353),(232,373),(226,379),(215,369),(205,364),(199,366),(188,355),(182,361),(170,351),(169,331),(164,298),(159,280),(149,284),(133,292),(119,291),(111,284),(114,271),(107,267),(111,243),(105,225),(99,205),(87,179),(82,152)]
mask=Image.new('L',im.size);ImageDraw.Draw(mask).polygon([(x+1660,y+560) for x,y in outline],fill=255)
alpha=mask.filter(ImageFilter.GaussianBlur(.7))
arm=im.convert('RGBA');arm.putalpha(alpha);arm.save(root/'static/forearm-layer.png',optimize=True)
rgb=np.array(im);m=np.array(mask)
repair=cv2.dilate(m,np.ones((31,31),np.uint8))
yy0,xx0=np.mgrid[:m.shape[0],:m.shape[1]].astype(np.float32)
donor=cv2.remap(rgb,xx0-830,yy0-390,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
# Gradient-domain water fill avoids smearing white lace/skin into the hole.
ys,xs=np.where(repair>0);center=((int(xs.min())+int(xs.max()))//2,(int(ys.min())+int(ys.max()))//2)
clean=cv2.seamlessClone(donor,rgb,repair,center,cv2.NORMAL_CLONE)
# The repair includes the outline fringe: keeping the unextracted fringe
# leaves pieces of original lace/skin floating behind the moving arm.
# Keep this base for all angles; never crossfade back to the original image.
# The repair dilation must not erase the attached upper sleeve. Restore an
# anchor cap through the fixed part of the joint, fading before the cuff.
anchor=np.clip((720.-yy0)/30.,0,1)
anchor=anchor*anchor*(3-2*anchor)
base=np.clip(clean*(1-anchor[:,:,None])+rgb*anchor[:,:,None],0,255).astype(np.uint8)
Image.fromarray(base).save(root/'static/wallpaper-rig-base.png',optimize=True)
Image.fromarray(clean).crop((1630,640,2030,990)).save(root/'build/arm-background.jpg')
arm.crop((1630,640,2030,990)).save(root/'build/arm-cutout.png')
# Offline endpoint preview, using the same inverse warp as the renderer.
h,w=m.shape;yy,xx=np.mgrid[:h,:w].astype(np.float32);px,py=1778.,665.
distance=np.sqrt((xx-px)**2+(yy-py)**2);q=np.clip((distance-40)/65,0,1);weight=q*q*(3-2*q)
frames=[]
for angle in [0,.10,.23,-.16]:
    a=angle*weight;dx=xx-px;dy=yy-py
    sx=px+np.cos(a)*dx-np.sin(a)*dy;sy=py+np.sin(a)*dx+np.cos(a)*dy
    sprite=cv2.remap(np.array(arm),sx,sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    opacity=sprite[:,:,3:4]/255.
    frame=np.clip(base*(1-opacity)+sprite[:,:,:3]*opacity,0,255).astype(np.uint8)
    frames.append(Image.fromarray(frame).crop((1600,640,2050,990)))
sheet=Image.new('RGB',(900,700));
for i,f in enumerate(frames):sheet.paste(f,((i%2)*450,(i//2)*350))
sheet.save(root/'build/arm-pose-comparison.jpg')
