"""Conservative inverse-field bounds: root/no folds/no distant pixel changes."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
mask=np.asarray(Image.open(ROOT/'static/tail-flow-mask.png'),dtype=np.float64)/255
y,x=np.mgrid[750:1170,1810:2275]
def smooth(q):
 q=np.clip(q,0,1);return q**3*(q*(q*6-15)+10)
q=smooth((x-1840)/350);f=smooth((x-2040)/100)
minimum=1.;maximum=0.
for body in np.linspace(-1,1,41):
 for fin in [-1,0,1]:
  dx=(body*3*q+fin*2*f)*mask;dy=(body*14*q+fin*7*f)*mask
  dxy,dxx=np.gradient(dx);dyy,dyx=np.gradient(dy)
  det=(1+dxx)*(1+dyy)-dxy*dyx
  minimum=min(minimum,float(det.min()));maximum=max(maximum,float(np.hypot(dx,dy).max()))
  assert np.max(np.abs(dx[:,x[0]<=1840]))==0
  assert np.max(np.abs(dy[:,x[0]<=1840]))==0
assert minimum>.5,minimum
result={'poses':123,'minimum_inverse_jacobian':minimum,'maximum_source_pixel_displacement':maximum,'root_displacement':0,'corridor':[1810,750,2275,1170],'passed':True}
(ROOT/'build/tail-action/geometry.json').write_text(json.dumps(result,indent=2),'utf8');print(result)
