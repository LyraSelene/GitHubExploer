"""Image regression checks for the specific cheek-line / wink-isolation bug."""
from pathlib import Path
import numpy as np
from PIL import Image
root=Path(__file__).resolve().parents[1]
original=np.array(Image.open(root/'static/wallpaper.webp').convert('RGB').crop((1710,225,1910,335)))
atlas=np.array(Image.open(root/'static/wallpaper-eyelids.png').convert('RGB'))
assert atlas.shape==(220,2600,3)
for i in range(13):
 blink=atlas[:110,i*200:(i+1)*200]
 wink=atlas[110:,i*200:(i+1)*200]
 assert np.array_equal(wink[:,:100],original[:,:100]),'Wink changes opposite eye'
 assert np.array_equal(blink[:14],original[:14]),'Eye edit changes upper hair'
 assert np.array_equal(blink[98:],original[98:]),'Eye edit changes cheek beyond eye region'
 if i==0:assert np.array_equal(blink,original) and np.array_equal(wink,original)
closed=atlas[:110,2400:2600]
# No painted line at the former outer endpoints, beyond traced lid ends.
assert np.all(closed[70:82,176:179].astype(int)>=original[70:82,176:179].astype(int)-2),'New dark line extends onto right-side hair'
patch=closed[39:49,77:79];skin=original[39:49,77:79].min(axis=2)>170
assert np.all(patch.min(axis=2)[skin]>150),'New dark line extends beyond left eye'
print('13 frames: neutral exact, wink opposite eye exact, hair/cheek bounds and old overlong eye-line regression passed.')
