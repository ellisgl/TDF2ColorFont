#!/usr/bin/env python3
"""
tdf2colorfont - convert TheDraw .TDF fonts into OpenType color fonts.

Each TDF glyph is a grid of CP437 cells (char + DOS attribute). Every cell is
rasterised with the IBM VGA 8x16 ROM font and emitted as merged vector
rectangles, so output is pixel-exact to how TheDraw/ANSI viewers show it.

One output font per font in the .tdf bundle, containing:
  * SVG  table  - OpenType-SVG color glyphs   (Firefox, Safari, Adobe apps)
  * COLR/CPAL v0 - layered color glyphs       (Chrome, Edge, Windows, Android, Firefox, Safari)
  * glyf        - monochrome silhouette fallback (everything else)

Requires: fonttools, numpy   (brotli optional, for .woff2)

Format notes: roysac.com TDF spec (via wiki.fsxnet.nz), tdfiglet, retrofont.
VGA bitmap: IBM VGA 8x16 ROM font (as distributed in Linux lib/fonts/font_8x16.c).
"""
from __future__ import annotations

import argparse
import base64
import html
import os
import re
import struct
import sys
from dataclasses import dataclass, field

import numpy as np
from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.timeTools import timestampNow
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables.S_V_G_ import SVGDocument

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
MAGIC = b"\x13TheDraw FONTS file\x1a"
SIG = b"\x55\xaa\x00\xff"
HDR_LEN = 213                      # sig(4) namelen(1) name(12) rsv(4) type(1) spacing(1) blocksize(2) offsets(188)
CHARSET = [chr(c) for c in range(33, 127)]
TYPE_NAMES = {0: "outline", 1: "block", 2: "color"}

CELL_W, CELL_H = 8, 16

VGA_PALETTE = [
    (0x00, 0x00, 0x00), (0x00, 0x00, 0xAA), (0x00, 0xAA, 0x00), (0x00, 0xAA, 0xAA),
    (0xAA, 0x00, 0x00), (0xAA, 0x00, 0xAA), (0xAA, 0x55, 0x00), (0xAA, 0xAA, 0xAA),
    (0x55, 0x55, 0x55), (0x55, 0x55, 0xFF), (0x55, 0xFF, 0x55), (0x55, 0xFF, 0xFF),
    (0xFF, 0x55, 0x55), (0xFF, 0x55, 0xFF), (0xFF, 0xFF, 0x55), (0xFF, 0xFF, 0xFF),
]

# Outline fonts: placeholder letters 'A'..'Q' -> box-drawing char, 19 styles (TheDraw's outline styles).
OUTLINE_STYLES = [
    "──││┌┐┌┐└┘└┘┤├   ", "═─││╒╕┌┐╘╛└┘╡├   ", "─═││┌┐╒╕└┘╘╛┤╞   ", "══││╒╕╒╕╘╛╘╛╡╞   ",
    "──║│╓┐┌╖└╜╙┘╢├   ", "═─║│╔╕┌╖╘╝╙┘╣├   ", "─═║│╓┐╒╗└╜╚╛╢╞   ", "══║│╔╕╒╗╘╝╚╛╣╞   ",
    "──│║┌╖╓┐╙┘└╜┤╟   ", "═─│║╒╗╓┐╚╛└╜╡╟   ", "─═│║┌╖╔╕╙┘╘╝┤╠   ", "══│║╒╗╔╕╚╛╘╝╡╠   ",
    "──║║╓╖╓╖╙╜╙╜╢╟   ", "═─║║╔╗╓╖╚╝╙╜╣╟   ", "─═║║╓╖╔╗╙╜╚╝╢╠   ", "══║║╔╗╔╗╚╝╚╝╣╠   ",
    "▄▄██▄▄▄▄██████   ", "▀▀██████▀▀▀▀██   ", "▀▄▐▌▐▌▄▄▀▀▐▌██   ",
]

SHADE_ALPHA = {0xB0: 0.25, 0xB1: 0.50, 0xB2: 0.75}   # ░ ▒ ▓

VGA_8X16_B64 = """
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
AGDgYmZsGDBg3IYMGD4AAABg4GJmbBgwZs6aPwYGAAAAABgYABgYGDw8PBgAAAAAAAAAAAA2bNhs
NgAAAAAAAAAAAAAA2Gw2bNgAAAAAAAARRBFEEUQRRBFEEUQRRBFEVapVqlWqVapVqlWqVapVqt13
3Xfdd9133Xfdd9133XcYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGPgYGBgYGBgYGBgYGBgY+Bj4GBgY
GBgYGBg2NjY2NjY29jY2NjY2NjY2AAAAAAAAAP42NjY2NjY2NgAAAAAA+Bj4GBgYGBgYGBg2NjY2
NvYG9jY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NgAAAAAA/gb2NjY2NjY2NjY2NjY2NvYG/gAAAAAA
AAAANjY2NjY2Nv4AAAAAAAAAABgYGBgY+Bj4AAAAAAAAAAAAAAAAAAAA+BgYGBgYGBgYGBgYGBgY
GB8AAAAAAAAAABgYGBgYGBj/AAAAAAAAAAAAAAAAAAAA/xgYGBgYGBgYGBgYGBgYGB8YGBgYGBgY
GAAAAAAAAAD/AAAAAAAAAAAYGBgYGBgY/xgYGBgYGBgYGBgYGBgfGB8YGBgYGBgYGDY2NjY2NjY3
NjY2NjY2NjY2NjY2NjcwPwAAAAAAAAAAAAAAAAA/MDc2NjY2NjY2NjY2NjY29wD/AAAAAAAAAAAA
AAAAAP8A9zY2NjY2NjY2NjY2NjY3MDc2NjY2NjY2NgAAAAAA/wD/AAAAAAAAAAA2NjY2NvcA9zY2
NjY2NjY2GBgYGBj/AP8AAAAAAAAAADY2NjY2Njb/AAAAAAAAAAAAAAAAAP8A/xgYGBgYGBgYAAAA
AAAAAP82NjY2NjY2NjY2NjY2NjY/AAAAAAAAAAAYGBgYGB8YHwAAAAAAAAAAAAAAAAAfGB8YGBgY
GBgYGAAAAAAAAAA/NjY2NjY2NjY2NjY2NjY2/zY2NjY2NjY2GBgYGBj/GP8YGBgYGBgYGBgYGBgY
GBj4AAAAAAAAAAAAAAAAAAAAHxgYGBgYGBgY/////////////////////wAAAAAAAAD/////////
///w8PDw8PDw8PDw8PDw8PDwDw8PDw8PDw8PDw8PDw8PD/////////8AAAAAAAAAAAAAAAAAAHbc
2NjY3HYAAAAAAAB4zMzM2MzGxsbMAAAAAAAA/sbGwMDAwMDAwAAAAAAAAAAAAP5sbGxsbGwAAAAA
AAD+xmAwGBgwYMb+AAAAAAAAAAAAftjY2NjYcAAAAAAAAAAAAGZmZmZmZnxgYMAAAAAAAHbcGBgY
GBgYAAAAAAAAfhg8ZmZmZjwYfgAAAAAAADhsxsb+xsbGbDgAAAAAAAA4bMbGxmxsbGzuAAAAAAAA
HjAYDD5mZmZmPAAAAAAAAAAAAH7b29t+AAAAAAAAAAAAAwZ+29vzfmDAAAAAAAAAHDBgYHxgYGAw
HAAAAAAAAAB8xsbGxsbGxsYAAAAAAAAAAP4AAP4AAP4AAAAAAAAAAAAYGH4YGAAAfgAAAAAAAAAw
GAwGDBgwAH4AAAAAAAAADBgwYDAYDAB+AAAAAAAADhsbGBgYGBgYGBgYGBgYGBgYGBgYGBjY2Nhw
AAAAAAAAAAAYAH4AGAAAAAAAAAAAAAAAdtwAdtwAAAAAAAAAOGxsOAAAAAAAAAAAAAAAAAAAAAAA
ABgYAAAAAAAAAAAAAAAAAAAYAAAAAAAAAAAADwwMDAwM7GxsPBwAAAAAAGw2NjY2NgAAAAAAAAAA
AAA8ZgwYMn4AAAAAAAAAAAAAAAAAfn5+fn5+fgAAAAAAAAAAAAAAAAAAAAAAAAAAAA==
"""
VGA = np.unpackbits(np.frombuffer(base64.b64decode(VGA_8X16_B64), dtype=np.uint8)).reshape(256, 16, 8).astype(bool)


# --------------------------------------------------------------------------
# TDF parsing
# --------------------------------------------------------------------------
@dataclass
class TdfGlyph:
    char: str
    width: int                     # declared max width (cells)
    height: int                    # declared height (unreliable, informational)
    rows: list                     # list[list[tuple(code, attr) | None]]
    desc: set                      # row indexes marked with '&' (descender rows)


@dataclass
class TdfFont:
    index: int
    name: str
    ftype: int
    spacing: int
    glyphs: dict = field(default_factory=dict)   # char -> TdfGlyph
    warnings: list = field(default_factory=list)


def _decode_glyph(d: bytes, p: int, end: int, ftype: int, amp_is_marker: bool):
    """Return (width, height, rows, desc, ok)."""
    if p + 2 > end:
        return 0, 0, [], set(), False
    width, height = d[p], d[p + 1]
    p += 2
    rows, desc = [[]], set()
    ok = False
    while p < end:
        ch = d[p]
        p += 1
        if ch == 0x00:
            ok = True
            break
        if ch == 0x0D:
            rows.append([])
            continue
        if ch == 0x26 and (ftype != 2 or amp_is_marker):
            desc.add(len(rows) - 1)
            continue
        if ftype == 2:
            if p >= end:
                break
            attr = d[p]
            p += 1
            rows[-1].append((ch, attr))
        else:
            rows[-1].append((ch, None))
    while rows and not rows[-1]:
        rows.pop()
    if any(len(r) > max(width, 1) for r in rows):
        ok = False
    return width, height, rows, desc, ok


def parse_tdf(data: bytes) -> list[TdfFont]:
    if not data.startswith(MAGIC):
        raise ValueError("not a TheDraw FONTS file (bad magic)")
    fonts, pos, idx = [], len(MAGIC), 0
    while data[pos:pos + 4] == SIG and pos + HDR_LEN <= len(data):
        namelen = min(data[pos + 4], 12)
        name = data[pos + 5:pos + 5 + namelen].decode("cp437").strip("\x00 ") or f"font{idx}"
        ftype, spacing = data[pos + 21], data[pos + 22]
        blocksize = struct.unpack_from("<H", data, pos + 23)[0]
        offsets = struct.unpack_from("<94H", data, pos + 25)
        base = pos + HDR_LEN
        end = min(base + blocksize, len(data))
        font = TdfFont(idx, name, ftype, spacing)
        if ftype not in TYPE_NAMES:
            font.warnings.append(f"unknown font type {ftype}; skipped")
        else:
            for ch, off in zip(CHARSET, offsets):
                if off == 0xFFFF or base + off >= end:
                    continue
                # '&' in color fonts is either a descender marker (no attr byte) or a literal '&' cell.
                # Try marker first, fall back to literal if that parse is inconsistent.
                w, h, rows, desc, ok = _decode_glyph(data, base + off, end, ftype, True)
                if not ok and ftype == 2:
                    w2, h2, rows2, desc2, ok2 = _decode_glyph(data, base + off, end, ftype, False)
                    if ok2:
                        w, h, rows, desc, ok = w2, h2, rows2, desc2, ok2
                if not ok:
                    font.warnings.append(f"glyph {ch!r}: malformed data, best-effort decode")
                font.glyphs[ch] = TdfGlyph(ch, w, h, rows, desc)
        fonts.append(font)
        idx += 1
        nxt = base + blocksize
        k = data.find(SIG, max(nxt - 2, base), nxt + 4)
        if k < 0:
            break
        pos = k
    return fonts


# --------------------------------------------------------------------------
# Cell rendering -> per-color pixel masks
# --------------------------------------------------------------------------
@dataclass
class RenderOpts:
    outline_style: int = 0
    shade: str = "alpha"            # alpha | pattern
    ice: bool = False               # attr bit7 = bright background instead of blink
    opaque_black: bool = False      # draw background colour 0 instead of leaving it transparent
    fg: int | None = None           # force fg colour index for block/outline fonts
    bg: int | None = None           # force bg colour index for block/outline fonts


def _cell(code: int, attr, ftype: int, ro: RenderOpts):
    """Normalise a raw TDF cell -> (cp437 code | None, fg rgba | None, bg rgba | None)."""
    if ftype == 0:                                   # outline
        if 0x41 <= code <= 0x51:                     # 'A'..'Q'
            u = OUTLINE_STYLES[ro.outline_style][code - 0x41]
            code = None if u == " " else u.encode("cp437")[0]
        elif code in (0x40, 0x20, 0xFF, 0x52):      # '@' fill, space, hard blank, 'R'
            code = None
    elif ftype == 1:                                 # block
        if code in (0x20, 0xFF):
            code = None
    if ftype in (0, 1):
        fg = VGA_PALETTE[ro.fg] + (1.0,) if ro.fg is not None else "current"
        bg = VGA_PALETTE[ro.bg] + (1.0,) if ro.bg is not None else None
        if code is None and bg is None:
            return None
        return code, (fg if code is not None else None), bg
    # color font
    fgi = attr & 0x0F
    bgi = (attr >> 4) & (0x0F if ro.ice else 0x07)
    if code in (0x20, 0xFF, 0x00):
        code = None
    bg = None if (bgi == 0 and not ro.opaque_black) else VGA_PALETTE[bgi] + (1.0,)
    if code is None and bg is None:
        return None
    if code is not None and code in SHADE_ALPHA and ro.shade == "alpha":
        fg = VGA_PALETTE[fgi] + (SHADE_ALPHA[code],)
    else:
        fg = VGA_PALETTE[fgi] + (1.0,)
    return code, (fg if code is not None else None), bg


@dataclass
class RenderedGlyph:
    cols: int
    rows: int
    layers: list                 # [(rgba | "current", mask)] in paint order
    silhouette: np.ndarray


def render_glyph(g: TdfGlyph, ftype: int, ro: RenderOpts, nrows: int) -> RenderedGlyph:
    cols = max([g.width] + [len(r) for r in g.rows]) if g.rows else g.width
    cols = max(cols, 1)
    H, W = nrows * CELL_H, cols * CELL_W
    bg_layers: dict = {}
    fg_layers: dict = {}
    for ry, row in enumerate(g.rows[:nrows]):
        for cx, (code, attr) in enumerate(row):
            c = _cell(code, attr, ftype, ro)
            if c is None:
                continue
            code, fg, bg = c
            y0, x0 = ry * CELL_H, cx * CELL_W
            if bg is not None:
                m = bg_layers.setdefault(bg, np.zeros((H, W), bool))
                m[y0:y0 + CELL_H, x0:x0 + CELL_W] = True
            if code is not None and fg is not None:
                m = fg_layers.setdefault(fg, np.zeros((H, W), bool))
                if ro.shade == "alpha" and code in SHADE_ALPHA:
                    m[y0:y0 + CELL_H, x0:x0 + CELL_W] = True
                else:
                    m[y0:y0 + CELL_H, x0:x0 + CELL_W] |= VGA[code]
    layers = list(bg_layers.items()) + list(fg_layers.items())
    sil = np.zeros((H, W), bool)
    for _, m in layers:
        sil |= m
    return RenderedGlyph(cols, nrows, layers, sil)


def mask_rects(mask: np.ndarray):
    """Greedy merge of a boolean mask into disjoint rectangles (x0, y0, x1, y1), pixels, top-down."""
    H, W = mask.shape
    edges = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    ys, xs = np.nonzero(edges)
    runs_by_row = [[] for _ in range(H)]
    vals = edges[ys, xs].tolist()
    start = 0
    for y, x, v in zip(ys.tolist(), xs.tolist(), vals):   # row-major: +1 start, -1 end alternate
        if v == 1:
            start = x
        else:
            runs_by_row[y].append((start, x))
    rects, open_runs = [], {}
    for y in range(H + 1):
        cur = set(runs_by_row[y]) if y < H else set()
        for k in [k for k in open_runs if k not in cur]:
            rects.append((k[0], open_runs.pop(k), k[1], y))
        for k in cur:
            open_runs.setdefault(k, y)
    return rects


# --------------------------------------------------------------------------
# Font building
# --------------------------------------------------------------------------
@dataclass
class BuildOpts:
    unit: int = 8                   # font units per VGA pixel (x)
    aspect: float = 1.0             # pixel aspect (y/x); 1.35 ~ real VGA 640x400 on 4:3
    gap: int | None = None          # inter-letter gap in cells (default: TDF spacing byte)
    space: int | None = None        # space width in cells (default: ~half median glyph width)
    casefold: bool = True
    svg: bool = True
    colr: bool = True
    family: str | None = None


def _rgba_hex(c):
    r, g, b, a = c
    return f"#{r:02X}{g:02X}{b:02X}", a


def _ps_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "", s.replace(" ", "-"))[:60] or "TDFFont"


def build_font(tf: TdfFont, ro: RenderOpts, bo: BuildOpts):
    PX = bo.unit
    PY = max(1, round(bo.unit * bo.aspect))
    chars = [c for c in CHARSET if c in tf.glyphs]
    if not chars:
        raise ValueError("font has no glyphs")

    # Vertical metrics: TheDraw top-aligns glyphs; '&'-marked rows hang below the baseline.
    asc_rows = max(len([i for i in range(len(g.rows)) if i not in g.desc]) for g in tf.glyphs.values())
    asc_rows = max(asc_rows, 1)
    tot_rows = max(max(len(g.rows) for g in tf.glyphs.values()), asc_rows)
    desc_rows = tot_rows - asc_rows
    asc = asc_rows * CELL_H * PY
    desc = desc_rows * CELL_H * PY
    upm = asc + desc
    if not 16 <= upm <= 16384:
        raise ValueError(f"unitsPerEm {upm} out of range; lower --unit")

    gap = tf.spacing if bo.gap is None else bo.gap
    widths = sorted(max([g.width] + [len(r) for r in g.rows]) for g in tf.glyphs.values())
    space_cols = bo.space if bo.space is not None else max(1, round(widths[len(widths) // 2] / 2))

    def y_up(ypx):              # glyph-pixel row (top-down) -> font units (y-up, baseline 0)
        return (asc_rows * CELL_H - ypx) * PY

    def draw(rects):
        pen = TTGlyphPen(None)
        for x0, y0, x1, y1 in rects:
            X0, X1, YT, YB = x0 * PX, x1 * PX, y_up(y0), y_up(y1)
            pen.moveTo((X0, YT)); pen.lineTo((X1, YT)); pen.lineTo((X1, YB)); pen.lineTo((X0, YB)); pen.closePath()
        return pen.glyph()

    def gname(c):
        return f"uni{ord(c):04X}"

    order = [".notdef", "space"]
    glyf, hmtx, colr_layers, svg_docs = {}, {}, {}, {}
    palette, pal_index = [], {}
    any_color = False

    def pidx(rgba):
        if rgba == "current":
            return 0xFFFF
        if rgba not in pal_index:
            pal_index[rgba] = len(palette)
            palette.append(rgba)
        return pal_index[rgba]

    # .notdef: hollow box
    pen = TTGlyphPen(None)
    w, h = 4 * CELL_W * PX, asc
    t = PX
    for (a, b, c, d) in [(0, h, w, h - t), (0, t, w, 0), (0, h - t, t, t), (w - t, h - t, w, t)]:
        pen.moveTo((a, b)); pen.lineTo((c, b)); pen.lineTo((c, d)); pen.lineTo((a, d)); pen.closePath()
    glyf[".notdef"] = pen.glyph(); hmtx[".notdef"] = (w + gap * CELL_W * PX, 0)
    glyf["space"] = TTGlyphPen(None).glyph(); hmtx["space"] = ((space_cols + gap) * CELL_W * PX, 0)

    layer_glyphs = []
    for c in chars:
        rg = render_glyph(tf.glyphs[c], tf.ftype, ro, tot_rows)
        name = gname(c)
        order.append(name)
        sil_rects = mask_rects(rg.silhouette)
        glyf[name] = draw(sil_rects)
        adv = (rg.cols + gap) * CELL_W * PX
        hmtx[name] = (adv, min((r[0] for r in sil_rects), default=0) * PX)

        is_colored = any(col != "current" for col, _ in rg.layers) or len(rg.layers) > 1
        if not is_colored:
            continue
        any_color = True
        layers, svg_parts = [], []
        for li, (col, mask) in enumerate(rg.layers):
            rects = mask_rects(mask)
            if not rects:
                continue
            lname = f"{name}.L{li}"
            layer_glyphs.append(lname)
            glyf[lname] = draw(rects)
            hmtx[lname] = (adv, min(r[0] for r in rects) * PX)
            layers.append((lname, pidx(col)))
            d = "".join(
                f"M{x0 * PX} {-y_up(y0)}h{(x1 - x0) * PX}v{(y1 - y0) * PY}h{-(x1 - x0) * PX}z"
                for x0, y0, x1, y1 in rects)
            if col == "current":
                svg_parts.append(f'<path fill="currentColor" d="{d}"/>')
            else:
                hx, a = _rgba_hex((*col[:3], col[3]))
                op = "" if a >= 1 else f' fill-opacity="{a:g}"'
                svg_parts.append(f'<path fill="{hx}"{op} d="{d}"/>')
        colr_layers[name] = layers
        svg_docs[name] = "".join(svg_parts)

    order += layer_glyphs

    cmap = {32: "space"}
    for c in chars:
        cmap[ord(c)] = gname(c)
    if bo.casefold:
        for c in chars:
            o = c.swapcase()
            if o != c and len(o) == 1 and 33 <= ord(o) <= 126 and ord(o) not in cmap:
                cmap[ord(o)] = gname(c)

    family = bo.family or tf.name
    style = "Regular"
    ps = _ps_name(f"{family}-{style}")

    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupHorizontalHeader(ascent=asc, descent=-desc, lineGap=0)
    fb.setupNameTable({
        "familyName": family,
        "styleName": style,
        "uniqueFontIdentifier": f"tdf2colorfont:{ps}",
        "fullName": f"{family} {style}",
        "psName": ps,
        "version": "Version 1.000",
        "description": f"Converted from TheDraw {TYPE_NAMES[tf.ftype]} font '{tf.name}' by tdf2colorfont",
    })
    fb.setupOS2(sTypoAscender=asc, sTypoDescender=-desc, sTypoLineGap=0,
                usWinAscent=asc, usWinDescent=desc, achVendID="TDF ",
                fsSelection=0x40 | 0x80, sxHeight=asc, sCapHeight=asc, version=4)
    fb.setupPost(isFixedPitch=0)
    now = timestampNow()
    fb.setupHead(unitsPerEm=upm, created=now, modified=now)

    if any_color:
        if bo.colr:
            fb.font["COLR"] = buildCOLR(colr_layers, version=0)
            fb.font["CPAL"] = buildCPAL([[(r / 255, g / 255, b / 255, a) for r, g, b, a in palette] or [(0, 0, 0, 1)]])
        if bo.svg:
            gid = {n: i for i, n in enumerate(order)}
            svg = newTable("SVG ")
            svg.docList = []
            for name, body in svg_docs.items():
                i = gid[name]
                doc = f'<svg xmlns="http://www.w3.org/2000/svg"><g id="glyph{i}">{body}</g></svg>'
                svg.docList.append(SVGDocument(doc, i, i, False))
            svg.docList.sort(key=lambda x: x.startGlyphID)
            fb.font["SVG "] = svg
    return fb.font, {"upm": upm, "asc_rows": asc_rows, "desc_rows": desc_rows,
                     "glyphs": len(chars), "color": any_color, "family": family}


# --------------------------------------------------------------------------
# Specimen HTML
# --------------------------------------------------------------------------
def specimen_html(entries, sample=None):
    faces, blocks = [], []
    for i, (family, path, meta) in enumerate(entries):
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        fmt = "woff2" if path.endswith(".woff2") else "truetype"
        mime = "font/woff2" if fmt == "woff2" else "font/ttf"
        fam = f"tdf{i}"
        faces.append(f"@font-face{{font-family:'{fam}';src:url(data:{mime};base64,{b64}) format('{fmt}');}}")
        charset = "".join(CHARSET)
        blocks.append(
            f'<section><h2>{html.escape(family)} <small>{html.escape(os.path.basename(path))} · '
            f'{meta["glyphs"]} glyphs · {"color" if meta["color"] else "mono"}</small></h2>'
            f'<div class="s" style="font-family:\'{fam}\'">{html.escape(sample or family.upper())}</div>'
            f'<div class="c" style="font-family:\'{fam}\'">{html.escape(charset)}</div></section>')
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>TDF color fonts</title>
<style>{''.join(faces)}
body{{background:#000;color:#aaa;font:14px/1.4 system-ui,sans-serif;margin:24px}}
h2{{font-weight:500;color:#ddd;margin:28px 0 8px}} small{{color:#777;font-weight:400}}
.s{{font-size:96px;line-height:1;white-space:nowrap;overflow-x:auto}}
.c{{font-size:40px;line-height:1;word-break:break-all;margin-top:8px}}
</style></head><body>{''.join(blocks)}</body></html>"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _parse_color(s):
    if s is None:
        return None
    v = int(s, 0)
    if not 0 <= v <= 15:
        raise argparse.ArgumentTypeError("colour index must be 0-15")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert TheDraw .TDF fonts to OpenType color fonts (SVG + COLR/CPAL).")
    ap.add_argument("inputs", nargs="+", help=".tdf files")
    ap.add_argument("-o", "--outdir", default=".", help="output directory (default: .)")
    ap.add_argument("-l", "--list", action="store_true", help="list fonts in each file and exit")
    ap.add_argument("-i", "--index", default="all", help="font index within bundle, comma list, or 'all' (default)")
    ap.add_argument("-f", "--format", default="ttf", help="comma list of ttf,woff2 (default: ttf)")
    ap.add_argument("--outline-style", default="0", help="outline fonts: style 0-18 or 'all' (default 0)")
    ap.add_argument("--shade", choices=["alpha", "pattern"], default="alpha",
                    help="░▒▓ as solid fg at 25/50/75%% opacity (default) or exact VGA dither "
                         "(authentic, but fonts can grow 20-40x)")
    ap.add_argument("--ice", action="store_true", help="attr bit 7 = bright background (iCE colors) instead of blink")
    ap.add_argument("--opaque-black", action="store_true", help="draw black (0) backgrounds instead of transparent")
    ap.add_argument("--fg", type=_parse_color, help="block/outline fonts: foreground colour 0-15 (default: text colour)")
    ap.add_argument("--bg", type=_parse_color, help="block/outline fonts: background colour 0-15 (default: none)")
    ap.add_argument("--unit", type=int, default=8, help="font units per VGA pixel (default 8)")
    ap.add_argument("--aspect", type=float, default=1.0, help="pixel aspect y/x (1.35 = authentic VGA on 4:3)")
    ap.add_argument("--gap", type=int, help="letter gap in cells (default: font's spacing byte)")
    ap.add_argument("--space", type=int, help="space width in cells (default: half the median glyph width)")
    ap.add_argument("--no-casefold", action="store_true", help="don't map missing a-z/A-Z to the other case")
    ap.add_argument("--no-svg", action="store_true", help="omit OpenType-SVG table")
    ap.add_argument("--no-colr", action="store_true", help="omit COLR/CPAL tables")
    ap.add_argument("--family", help="override family name (single font only)")
    ap.add_argument("--specimen", action="store_true", help="write specimen.html with all generated fonts")
    ap.add_argument("--sample", default=None, help="specimen sample text (default: font name)")
    a = ap.parse_args(argv)

    formats = [f.strip().lower() for f in a.format.split(",") if f.strip()]
    for f in formats:
        if f not in ("ttf", "woff2"):
            ap.error(f"unknown format {f}")
    if "woff2" in formats:
        try:
            import brotli  # noqa: F401
        except ImportError:
            ap.error("woff2 needs the 'brotli' package (pip install brotli)")

    os.makedirs(a.outdir, exist_ok=True)
    specimen, rc = [], 0
    for path in a.inputs:
        try:
            with open(path, "rb") as fh:
                fonts = parse_tdf(fh.read())
        except (OSError, ValueError) as e:
            print(f"{path}: {e}", file=sys.stderr)
            rc = 1
            continue
        if a.list:
            for tf in fonts:
                print(f"{path}\t[{tf.index}]\t{tf.name}\t{TYPE_NAMES.get(tf.ftype, tf.ftype)}\t"
                      f"spacing={tf.spacing}\tglyphs={len(tf.glyphs)}")
            continue
        sel = fonts if a.index == "all" else [f for f in fonts if str(f.index) in a.index.split(",")]
        stem = os.path.splitext(os.path.basename(path))[0]
        for tf in sel:
            styles = [0]
            if tf.ftype == 0:
                styles = list(range(19)) if a.outline_style == "all" else [int(a.outline_style)]
            for st in styles:
                ro = RenderOpts(st, a.shade, a.ice, a.opaque_black, a.fg, a.bg)
                fam = a.family or tf.name
                if tf.ftype == 0 and len(styles) > 1:
                    fam = f"{fam} O{st}"
                bo = BuildOpts(a.unit, a.aspect, a.gap, a.space, not a.no_casefold,
                               not a.no_svg, not a.no_colr, fam)
                try:
                    font, meta = build_font(tf, ro, bo)
                except ValueError as e:
                    print(f"{path}[{tf.index}] {tf.name}: {e}", file=sys.stderr)
                    rc = 1
                    continue
                base = stem if len(fonts) == 1 else f"{stem}-{tf.index}-{_ps_name(tf.name)}"
                if tf.ftype == 0 and len(styles) > 1:
                    base += f"-o{st}"
                for w in tf.warnings:
                    print(f"{path}[{tf.index}] warning: {w}", file=sys.stderr)
                for fmt in formats:
                    out = os.path.join(a.outdir, f"{base}.{fmt}")
                    font.flavor = "woff2" if fmt == "woff2" else None
                    font.save(out)
                    print(f"{out}\t{meta['family']}\t{TYPE_NAMES[tf.ftype]}\tglyphs={meta['glyphs']}\t"
                          f"upm={meta['upm']}\t{'color' if meta['color'] else 'mono'}")
                    if fmt == formats[-1]:
                        specimen.append((meta["family"], out, meta))
    if a.specimen and specimen:
        out = os.path.join(a.outdir, "specimen.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(specimen_html(specimen, a.sample))
        print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
