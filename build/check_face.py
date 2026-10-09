"""Regressions for source-art face: exact neutral/hair, no iris at closure,
and source-mouth deformation rather than a newly painted lip line."""
import sys
from pathlib import Path
import numpy as np
import cv2
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parent))
from make_face import source,frame,prepared,xx,yy,remap,ROOT,W,H

atlas=np.array(Image.open(ROOT/'static/wallpaper-face.png'))
assert atlas.shape==(H*2,W*13,3)
assert np.array_equal(atlas[:H,:W],source)
assert np.array_equal(atlas[H:,:W],source)
support=np.maximum(prepared[0][2],prepared[1][2])>0
for i in range(13):
    blink=atlas[:H,W*i:W*(i+1)]
    wink=atlas[H:,W*i:W*(i+1)]
    assert np.array_equal(wink[:,:100],source[:,:100]),'Wink touched the other eye'
    assert np.array_equal(blink[~support],source[~support]),'Face edit escaped eye masks'
    assert np.array_equal(blink[:12],source[:12]),'Upper hair changed'
    assert np.array_equal(blink[120:],source[120:]),'Mouth/cheek changed in eye atlas'
closed=frame(1).astype(float)
for cx,cy in [(1760,264),(1850,295)]:
    inner=((xx-cx)**2+(yy-cy)**2)<7**2
    assert not np.any((closed[:,:,2]-closed[:,:,0]>15)&inner),'Blue iris survives full closure'
# Pixels at all four crop boundaries remain exact: no rectangular compositing seam.
assert np.array_equal(closed[[0,-1]],source[[0,-1]])
assert np.array_equal(closed[:,[0,-1]],source[:,[0,-1]])
# Same bounded inverse warp as scene.js. Check no move beyond lips, bounded
# displacement, and preserved soft pigment rather than a replacement stroke.
from make_face import smooth
lip_t=np.clip((xx-1763)/15,0,1)
lip_mask=(1-smooth(1780,1788,xx))*smooth(1758,1763,xx)*(1-smooth(6,24,np.abs(yy-315)))
lift=(2.8*lip_t-4.2*np.sin(lip_t*np.pi))*lip_mask
smiling=remap(source,xx,yy+lift)
assert lift.max()<=2.80001
assert lift.min()>-3.2
assert np.all(np.diff(yy+lift,axis=0)>.3),'Mouth warp folds skin onto itself'
assert np.allclose(smiling[lip_mask==0],source[lip_mask==0],atol=.001)
assert np.max(np.abs(smiling-source))>5
# Closed lash centroid must stay in the tilted original socket, not at y305.
right=(xx>1830)&(xx<1870)&(yy>278)&(yy<315)
pigment=np.maximum(0,source.astype(float).mean(axis=2)-closed.mean(axis=2))*right
assert 283<(pigment*yy).sum()/pigment.sum()<300
print('Face: neutral/opposite eye/seams exact, closed iris, socket position and non-folding source smile passed.')
# Offline closeups include the exact source-warp smile, separately labelled
# from WebView screenshots.
sheet=Image.new('RGB',(W*4*3,H*4))
for n,a in enumerate([0,.55,1]):
    im=frame(a,True)
    if a: im=np.rint(np.clip(remap(im,xx,yy+lift*.85),0,255)).astype('uint8')
    sheet.paste(Image.fromarray(im).resize((W*4,H*4)),(n*W*4,0))
sheet.save(ROOT/'Face-source-comparison.png')
