from PIL import Image
import numpy as np
from pathlib import Path
root=Path(__file__).resolve().parents[1]
atlas=np.array(Image.open(root/'static/wallpaper-smile.png'))
source=np.array(Image.open(root/'static/wallpaper.webp').convert('RGB').crop((1735,295,1805,345)))
assert atlas.shape==(50,910,3)
assert np.array_equal(atlas[:,:70],source)
for i in range(13):
 f=atlas[:,70*i:70*(i+1)]
 assert np.array_equal(f[:12],source[:12])
 assert np.array_equal(f[30:],source[30:])
assert not np.array_equal(atlas[:,-70:],source)
print('Smile neutral exact, edits bounded around lips, no face-outline changes passed.')
