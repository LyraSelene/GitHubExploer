"""Precompute a narrow local deformation corridor; no invented body texture."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFilter
root=Path(__file__).resolve().parents[1]
# Source coordinates. Root stays under the dress; fin avoids the hair above it.
outline=[(1810,1050),(1890,1070),(1970,1066),(2020,1042),(2064,1008),(2090,978),(2098,950),
 (2082,918),(2055,885),(2030,856),(2013,812),(2013,790),(2022,787),(2035,807),
 (2060,832),(2088,849),(2103,879),(2108,918),(2140,901),(2190,900),(2235,915),(2258,913),
 (2244,941),(2210,958),(2170,969),(2130,970),(2108,981),(2088,1026),(2052,1078),
 (2020,1103),(1980,1125),(1920,1138),(1850,1129),(1810,1112)]
mask=Image.new('L',(2275,1279));ImageDraw.Draw(mask).polygon(outline,fill=255)
# Water inside this narrow margin follows the same inverse field: no hole or old tail.
mask=mask.filter(ImageFilter.MaxFilter(51)).filter(ImageFilter.GaussianBlur(22))
mask.crop((1810,750,2275,1170)).save(root/'static/tail-flow-mask.png',optimize=True)
preview=Image.open(root/'static/wallpaper-rig-base.png').convert('RGBA');overlay=Image.new('RGBA',preview.size,(0,160,255,0));overlay.putalpha(mask.point(lambda v:v//2));Image.alpha_composite(preview,overlay).crop((1700,700,2275,1170)).save(root/'build/tail-action/mask-preview.png')
