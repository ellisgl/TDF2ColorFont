import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
font_path, char, out = sys.argv[1], sys.argv[2], sys.argv[3]
f = TTFont(font_path)
gs = f.getGlyphSet()
g = f.getBestCmap()[ord(char)]
pal = f['CPAL'].palettes[0]
layers = f['COLR'].ColorLayers[g]
bp = BoundsPen(gs)
for L in layers: gs[L.name].draw(bp)
xmin, ymin, xmax, ymax = bp.bounds
w, h = xmax - xmin, ymax - ymin
size = max(w, h); pad = size * 0.06; S = size + 2 * pad
ox = xmin - pad - (size - w) / 2
oy = ymax + pad + (size - h) / 2   # flip y: font units are y-up
paths = []
for L in layers:
    pen = SVGPathPen(gs, ntos=lambda v: ('%.1f' % v).rstrip('0').rstrip('.'))
    gs[L.name].draw(pen)
    c = pal[L.colorID]
    op = '' if c.alpha == 255 else f' fill-opacity="{c.alpha/255:.2f}"'
    paths.append(f'<path fill="#{c.red:02x}{c.green:02x}{c.blue:02x}"{op} d="{pen.getCommands()}"/>')
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S:.0f} {S:.0f}">'
       f'<rect width="{S:.0f}" height="{S:.0f}" fill="#000"/>'
       f'<g transform="matrix(1 0 0 -1 {-ox:.1f} {oy:.1f})">' + ''.join(paths) + '</g></svg>\n')
open(out, 'w').write(svg)
print(len(layers), 'layers,', len(svg), 'bytes')
