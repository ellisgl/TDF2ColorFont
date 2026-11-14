# tdf2colorfont

Convert TheDraw `.TDF` fonts into OpenType color fonts.

Every TDF glyph is a grid of CP437 cells, each with a DOS text attribute. Each cell is drawn with the IBM VGA 8×16 ROM font. The pixels are merged into vector rectangles, so the result matches TheDraw and ANSI viewers pixel for pixel, at any size.

## Output

Each font in a `.tdf` bundle becomes one font file containing:

| Table | Purpose | Rendered by |
|---|---|---|
| `SVG ` | OpenType-SVG color glyphs | Firefox, Safari, Adobe apps |
| `COLR`/`CPAL` v0 | Layered color glyphs | Chrome, Edge, Windows, Android, Firefox, Safari |
| `glyf` | Monochrome silhouette fallback | Everything else |

Formats: `.ttf` and `.woff2`. You can also generate an HTML specimen page with every font embedded.

Block and outline fonts have no color data. By default they come out as plain monochrome fonts that use the current text color. Use `--fg`/`--bg` to give them fixed colors, which also produces color tables.

## Requirements

- Python 3.9+
- `fonttools`, `numpy`
- `brotli` (only for `.woff2`)

```sh
pip install fonttools numpy brotli
```

## Usage

```sh
# List fonts inside one or more bundles
./tdf2colorfont.py -l fonts/*.tdf

# Convert everything in a bundle to TTF
./tdf2colorfont.py -o out myfont.tdf

# Web fonts + preview page
./tdf2colorfont.py -o out -f ttf,woff2 --specimen myfont.tdf

# Only fonts 0 and 2 from a bundle
./tdf2colorfont.py -o out -i 0,2 bundle.tdf

# Outline font: all 19 TheDraw outline styles, red
./tdf2colorfont.py -o out --outline-style all --fg 12 outline.tdf

# Block font as yellow on blue
./tdf2colorfont.py -o out --fg 14 --bg 1 block.tdf

# Authentic VGA aspect and dithered shading
./tdf2colorfont.py -o out --aspect 1.35 --shade pattern color.tdf
```

Output names: a single-font bundle gives `<stem>.<ext>`. A multi-font bundle gives `<stem>-<index>-<FontName>.<ext>`. Building every outline style adds `-o<N>`.

## Options

| Option | Default | Description |
|---|---|---|
| `-o, --outdir DIR` | `.` | Output directory |
| `-l, --list` | | List fonts (index, name, type, spacing, glyph count) and exit |
| `-i, --index LIST` | `all` | Font index(es) within the bundle, comma-separated |
| `-f, --format LIST` | `ttf` | `ttf`, `woff2`, or both |
| `--outline-style N\|all` | `0` | Outline fonts: TheDraw outline style 0–18 |
| `--shade alpha\|pattern` | `alpha` | `░▒▓` as foreground at 25/50/75% opacity, or as the exact VGA dither |
| `--ice` | off | Attribute bit 7 means a bright background (iCE colors) instead of blink |
| `--opaque-black` | off | Draw black (color 0) backgrounds instead of leaving them transparent |
| `--fg N` | text color | Block/outline fonts: foreground color 0–15 |
| `--bg N` | none | Block/outline fonts: background color 0–15 |
| `--unit N` | `8` | Font units per VGA pixel (horizontal) |
| `--aspect F` | `1.0` | Pixel aspect y/x. `1.35` ≈ VGA 640×400 on a 4:3 display |
| `--gap N` | font's spacing byte | Gap between letters, in cells |
| `--space N` | ½ median glyph width | Width of the space character, in cells |
| `--no-casefold` | | Don't map missing `a–z`/`A–Z` glyphs to the other case |
| `--no-svg` | | Omit the OpenType-SVG table |
| `--no-colr` | | Omit the COLR/CPAL tables |
| `--family NAME` | TDF font name | Override the family name |
| `--specimen` | | Write `specimen.html` with all generated fonts embedded |
| `--sample TEXT` | font name | Specimen sample text |

Colors use the standard 16-color VGA palette (0 black, 1 blue, 2 green, 3 cyan, 4 red, 5 magenta, 6 brown, 7 light gray, 8–15 bright variants).

## Font metrics

- 1 cell = 8 × 16 VGA pixels = `8·unit` × `16·unit·aspect` font units.
- Glyphs are top-aligned, as in TheDraw.
- Rows marked with `&` (descender rows) hang below the baseline.
- `unitsPerEm` = ascent + descent. Set CSS `font-size` to the full glyph height in pixels and `line-height: 1` to stack lines with no gaps.
- Advance width = glyph width + letter gap (TDF spacing byte).
- With the defaults (`--unit 8`, `--aspect 1`), one VGA pixel = `font-size / (16 × rows)` CSS px. For crisp edges, pick a `font-size` that is a multiple of `16 × rows`.

## TDF format notes

```
0x00  0x13 "TheDraw FONTS file" 0x1A           file header (20 bytes)
      repeated per font:
+0    55 AA 00 FF                               font signature
+4    u8   name length (≤12)
+5    12   name, zero-padded
+17   4    reserved
+21   u8   type: 0 outline, 1 block, 2 color
+22   u8   letter spacing
+23   u16  glyph block size (LE)
+25   94×u16 offsets for '!'..'~' (0xFFFF = undefined)
+213  glyph block
```

Glyph record: `width`, `height`, then the cell stream until `0x00`. `0x0D` means a new row. Color fonts store `char, attr` pairs. In the attribute byte, the low nibble is the foreground, bits 4–6 the background and bit 7 blink/iCE. Outline fonts use the letters `A`–`Q` as placeholders for box-drawing characters, which are picked from one of 19 styles. `@` and `O` mean fill/hole and are rendered as blanks.

Parser behavior:

- **`&` in color fonts.** It can be a descender marker (no attribute byte follows) or a literal `&` cell. The parser tries the marker reading first and falls back to the literal reading if rows overflow the declared width or the record doesn't terminate.
- **Spaces and hard blanks (`0xFF`).** These are transparent unless they have a non-black background.
- **Control codes `0x01`–`0x1F`.** These render as their CP437 glyphs (☺, ♥, ►, …).
- **Bundle traversal.** The next font is located by searching for the signature near the end of the declared block, which tolerates files with or without a terminating null.

## Limitations

- Chrome ignores the `SVG ` table. It renders from COLR, which holds the same artwork.
- `--shade pattern` produces large uncompressed TTFs (up to ~40× bigger) because every dither pixel is its own contour. WOFF2 compresses this well.
- Blink is ignored.
- TheDraw's letter "smushing" is not emulated. Letters are simply placed side by side with the gap.

## Testing

Tested against the 1,071 `.tdf` files in [tdfiglet](https://github.com/tat3r/tdfiglet) (3,711 fonts: 3,541 color, 163 block, 7 outline). All converted without warnings. A random sample loaded and rendered correctly in Chrome via the `FontFace` API.

## Credits

- Format: Roy/SAC's [TDF specification](https://www.roysac.com/thedrawfonts-tdf.html) (mirrored on the [fsxNet wiki](https://wiki.fsxnet.nz/resources:misc:tdf))
- Reference implementations: [tdfiglet](https://github.com/tat3r/tdfiglet), [retrofont](https://github.com/mkrueger/retrofont) (outline style table)
- VGA bitmap: IBM VGA 8×16 ROM font, as distributed in the Linux kernel's `lib/fonts/font_8x16.c` (GPL-2.0). Keep this in mind if you redistribute.
