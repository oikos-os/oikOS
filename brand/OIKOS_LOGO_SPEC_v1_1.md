# oikOS Logo — Design Specification
## Version: 1.1 · Certified 2026-03-24

### Changelog
- **v1.1** (2026-03-24): Added font-size differential to wordmark. "oik" renders at 75% of "OS" font size (10.5px / 14px). Each wordmark line splits into two baseline-aligned `<pre>` blocks. Updated reference HTML. All other elements unchanged.
- **v1.0** (2026-03-24): Initial certified specification.

---

## OVERVIEW

The oikOS logo consists of three elements composed horizontally:
1. **House mark** — a pixel-grid icon (7 rows × 8 columns)
2. **Wordmark** — "oikOS" rendered in pyfiglet `ansi_shadow` font
3. **Tagline** — "The home for AI agents"

The product name is **oikOS**. Lowercase "oik", uppercase "OS". One word. Always. Think macOS, iOS — the prefix is subordinate, the suffix dominates.

---

## 1. COLOR PALETTE

```
Name        Hex        Role
─────────────────────────────────────────
peak        #FFE8B0    Maximum brightness (center glow)
glow        #FFC83C    Active highlights
bright      #FFB000    Primary / high importance
amber       #D4A017    Secondary text
warm        #B8860B    Transitional
mid         #8B6914    Tertiary / labels
dim         #6B5012    Structural / edges
faint       #453510    Background texture / deepest
background  #0A0A0A    Terminal background
```

---

## 2. HOUSE MARK

### Grid (7 rows × 8 columns, 1 = filled, 0 = empty)

```
Row 0:  [0, 0, 0, 1, 1, 0, 0, 0]    ··██····
Row 1:  [0, 0, 1, 1, 1, 1, 0, 0]    ··████··
Row 2:  [0, 1, 1, 1, 1, 1, 1, 0]    ·██████·
Row 3:  [1, 1, 1, 1, 1, 1, 1, 1]    ████████
Row 4:  [1, 1, 0, 1, 1, 0, 1, 1]    ██·██·██  ← "the eyes"
Row 5:  [1, 1, 0, 1, 1, 0, 1, 1]    ██·██·██  ← "the eyes"
Row 6:  [1, 1, 1, 1, 1, 1, 1, 1]    ████████
```

### House gradient (V2 center-bright, per row)

```
Row 0:  #453510  (faint)
Row 1:  #6B5012  (dim)
Row 2:  #8B6914  (mid)
Row 3:  #FFB000  (bright)
Row 4:  #FFE8B0  (peak)     ← center glow
Row 5:  #FFB000  (bright)
Row 6:  #D4A017  (amber)
```

### Rendering rule

The house mark MUST be rendered as **square pixel cells** with uniform 1px gaps.
- Each cell: 10×10px (standard) or 8×8px (small variant)
- Border-radius: 1px per cell
- Filled cells get the row's gradient color
- Empty cells are transparent
- **Do NOT use block characters (██)** — monospace characters are rectangular, not square, and produce an uneven, low-quality appearance

### Implementation (HTML/CSS)

```css
.house-grid {
  display: inline-grid;
  grid-template-columns: repeat(8, 10px);
  grid-template-rows: repeat(7, 10px);
  gap: 1px;
}
.house-grid .cell {
  width: 10px;
  height: 10px;
  border-radius: 1px;
}
```

### Implementation (Python / Rich terminal)

Use Rich's `Canvas` widget or a custom pixel renderer that outputs actual square cells.
Do NOT use `Text("██")` — the aspect ratio will be wrong.

---

## 3. WORDMARK

### Font

pyfiglet font: `ansi_shadow`

### Raw output (pyfiglet "oikOS")

```
 ██████╗ ██╗██╗  ██╗ ██████╗ ███████╗
██╔═══██╗██║██║ ██╔╝██╔═══██╗██╔════╝
██║   ██║██║█████╔╝ ██║   ██║███████╗
██║   ██║██║██╔═██╗ ██║   ██║╚════██║
╚██████╔╝██║██║  ██╗╚██████╔╝███████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
```

The wordmark is 6 lines tall. Each line has two color zones:
- **oik zone** (columns for o, i, k): dimmer
- **OS zone** (columns for O, S): brighter

### Font-size-as-casing rule (v1.1)

The `ansi_shadow` font renders all characters at the same block weight — there are no actual lowercase glyphs. Two signals communicate case:

1. **Brightness:** oik is always 2 brightness steps below OS on the same line (unchanged from v1.0).
2. **Size:** oik renders at **75% of OS font size** — specifically **10.5px for oik, 14px for OS** in HTML.

Each wordmark line is split into two `<pre>` blocks at the oik/OS boundary, set to their respective font sizes, and **baseline-aligned** (`align-items: baseline` on the flex row). This makes "oik" physically smaller while sharing a common bottom edge with "OS" on every line.

The combined effect: "oik" is both dimmer *and* smaller — it recedes visually the same way "mac" recedes in "macOS".

> **Ratio is locked at 75%.** Do not adjust without ARCHITECT approval.

### Color-as-casing rule

Since `ansi_shadow` renders all characters at the same block weight (no actual lowercase glyphs), brightness communicates case:

> **oik is always 2 brightness steps below OS on the same line.**

This makes "oik" recede and "OS" glow — same visual effect as reading "macOS" where "mac" is subordinate.

### Wordmark gradient (V2 center-bright, per line)

```
Line    oik color    oik hex    OS color    OS hex
──────────────────────────────────────────────────────
1       faint        #453510    mid         #D4A017
2       dim          #8B6914    bright      #FFB000
3       mid          #D4A017    peak        #FFE8B0    ← center glow
4       dim          #8B6914    bright      #FFB000
5       faint        #453510    mid         #D4A017
6       faint        #453510    dim         #8B6914
```

### Split point

The oik/OS boundary falls between the `k` and `O` characters in the pyfiglet output. In the raw output above, there is a single space between `██╗` (end of k) and `██████╗` (start of O) on line 1. The color changes at this boundary.

### Styled wordmark (exact, copy-paste)

Each line is shown as: `[oik_color @ 10.5px]oik_text[/][os_color @ 14px]os_text[/]`

```
Line 1: [#453510 @ 10.5px] ██████╗ ██╗██╗  ██╗[/] [#D4A017 @ 14px] ██████╗ ███████╗[/]
Line 2: [#8B6914 @ 10.5px]██╔═══██╗██║██║ ██╔╝[/][#FFB000 @ 14px]██╔═══██╗██╔════╝[/]
Line 3: [#D4A017 @ 10.5px]██║   ██║██║█████╔╝[/] [#FFE8B0 @ 14px]██║   ██║███████╗[/]
Line 4: [#8B6914 @ 10.5px]██║   ██║██║██╔═██╗[/] [#FFB000 @ 14px]██║   ██║╚════██║[/]
Line 5: [#453510 @ 10.5px]╚██████╔╝██║██║  ██╗[/][#D4A017 @ 14px]╚██████╔╝███████║[/]
Line 6: [#453510 @ 10.5px] ╚═════╝ ╚═╝╚═╝  ╚═╝[/][#8B6914 @ 14px] ╚═════╝ ╚══════╝[/]
```

Note: Line 1 and Line 3 have a space between the oik and OS zones. Lines 2, 4, 5 have no space (they abut). Line 6 has no space.

### Rendering implementation (HTML)

Each wordmark line is a flex row with two `<pre>` elements, baseline-aligned:

```html
<div style="display:flex;align-items:baseline;line-height:1.15">
  <pre style="margin:0;font-size:10.5px;color:{oik_color}">{oik_text}</pre>
  <pre style="margin:0;font-size:14px;color:{os_color}">{os_text}</pre>
</div>
```

### Rendering implementation (Python / Rich terminal)

Terminal renderers cannot mix font sizes on the same line. For terminal output, use color-as-casing only (brightness differential). The font-size differential is an HTML/GUI-only enhancement. Terminal rendering falls back to uniform character size with the v1.0 color gradient.

---

## 4. COMPOSITION

### Layout

```
[house mark]  [gap]  [wordmark]
                     [tagline below wordmark]
```

- House and wordmark are **bottom-aligned**
- The house is 7 rows tall; the wordmark is 6 lines tall
- The house's top row (roof peak) sits above the wordmark's first line
- Gap between house and wordmark: ~16px (HTML) or 2 characters (terminal)

### Tagline

- Text: `The home for AI agents`
- Color: #8B6914 (mid)
- Position: below the wordmark, left-aligned with wordmark's left edge
- Spacing: 1 blank line between wordmark bottom and tagline

### Boot info (optional, shown on TUI launch)

```
⌂ v{version} · {test_count} tests · {gauntlet_score} gauntlet
◈ {mode} → {model_name}
```

- Color: #453510 (faint)
- Position: below tagline, left-aligned with tagline

### Doctrine quote (optional)

- One of four rotating quotes:
  1. "Intelligence is cheap. Context is expensive. Build for context."
  2. "Fix the soul before building the hands."
  3. "The cloud is a loan. Local is sovereignty."
  4. "I don't want to remember more. I want to understand better."
- Color: #8B6914 (mid)
- Position: below boot info, with vertical breathing room

---

## 5. V2 CENTER-BRIGHT GRADIENT — FORMULA

The gradient is not top-to-bottom. It radiates from the center outward in both directions:

```
For N lines (0-indexed):
  center = (N - 1) / 2
  For each line i:
    distance = abs(i - center) / center    → normalized 0.0 (center) to 1.0 (edge)
    brightness = peak_brightness * (1 - distance)
```

The palette steps used (brightest to dimmest):
```
#FFE8B0 → #FFC83C → #FFB000 → #D4A017 → #B8860B → #8B6914 → #6B5012 → #453510
```

Map the calculated brightness to the nearest palette step. The center line(s) get peak/glow. Edges get faint/dim.

---

## 6. DESIGN PRINCIPLES

- **Background**: Always #0A0A0A (near-black). Never pure black.
- **Scanlines**: Optional. 8% opacity horizontal lines at 2px intervals using `rgba(255, 176, 0, 0.015)`.
- **Font for wordmark**: Monospace only. Preferred: Cascadia Code, Fira Code, JetBrains Mono, Consolas. The ansi_shadow output requires a monospace font to align.
- **House mark font**: NONE. The house is a pixel grid, not text. Always render as discrete colored cells.
- **Metaphor**: Cyberpunk suburban home. Warm, not aggressive. A place you live in, not a tool you wield.
- **The house has personality**: The two windows are "the eyes." It looks at you. It's small, simple, cute.

---

## 7. REFERENCE RENDERING (HTML)

Below is a minimal, self-contained HTML snippet that produces the exact logo:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {
    background: #0A0A0A;
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
    padding: 40px;
  }
  pre { margin: 0; line-height: 1.15; }
  .logo { display: flex; align-items: flex-end; gap: 16px; }
  .wm-line { display: flex; align-items: baseline; line-height: 1.15; }
  .wm-line .oik { font-size: 10.5px; }
  .wm-line .os  { font-size: 14px; }
  .house {
    display: inline-grid;
    grid-template-columns: repeat(8, 10px);
    grid-template-rows: repeat(7, 10px);
    gap: 1px;
    flex-shrink: 0;
  }
  .house .c { width: 10px; height: 10px; border-radius: 1px; }
  .tagline { color: #8B6914; font-size: 13px; margin-top: 12px; }
</style>
</head>
<body>
<div class="logo">
  <div class="house" id="h"></div>
  <div>
    <div class="wm-line"><pre class="oik" style="color:#453510"> ██████╗ ██╗██╗  ██╗</pre><pre class="os" style="color:#D4A017"> ██████╗ ███████╗</pre></div>
    <div class="wm-line"><pre class="oik" style="color:#8B6914">██╔═══██╗██║██║ ██╔╝</pre><pre class="os" style="color:#FFB000">██╔═══██╗██╔════╝</pre></div>
    <div class="wm-line"><pre class="oik" style="color:#D4A017">██║   ██║██║█████╔╝</pre><pre class="os" style="color:#FFE8B0"> ██║   ██║███████╗</pre></div>
    <div class="wm-line"><pre class="oik" style="color:#8B6914">██║   ██║██║██╔═██╗</pre><pre class="os" style="color:#FFB000"> ██║   ██║╚════██║</pre></div>
    <div class="wm-line"><pre class="oik" style="color:#453510">╚██████╔╝██║██║  ██╗</pre><pre class="os" style="color:#D4A017">╚██████╔╝███████║</pre></div>
    <div class="wm-line"><pre class="oik" style="color:#453510"> ╚═════╝ ╚═╝╚═╝  ╚═╝</pre><pre class="os" style="color:#8B6914"> ╚═════╝ ╚══════╝</pre></div>
    <div class="tagline">The home for AI agents</div>
  </div>
</div>
<script>
const G=[
  [0,0,0,1,1,0,0,0],[0,0,1,1,1,1,0,0],[0,1,1,1,1,1,1,0],
  [1,1,1,1,1,1,1,1],[1,1,0,1,1,0,1,1],[1,1,0,1,1,0,1,1],[1,1,1,1,1,1,1,1]
];
const C=['#453510','#6B5012','#8B6914','#FFB000','#FFE8B0','#FFB000','#D4A017'];
const h=document.getElementById('h');
G.forEach((r,ri)=>r.forEach(v=>{
  const d=document.createElement('div');
  d.className='c';
  d.style.backgroundColor=v?C[ri]:'transparent';
  h.appendChild(d);
}));
</script>
</body>
</html>
```

---

## 8. QUICK VISUAL REFERENCE

```
House mark (text approximation — for reference only, not for rendering):

   ██
  ████
 ██████
████████
██ ██ ██   ← the eyes
██ ██ ██
████████

Wordmark — two signals encode case:

 [oik — dim + SMALL ——————] [OS — bright + FULL SIZE ——]
 ██████╗ ██╗██╗  ██╗        ██████╗ ███████╗
██╔═══██╗██║██║ ██╔╝       ██╔═══██╗██╔════╝
██║   ██║██║█████╔╝        ██║   ██║███████╗
██║   ██║██║██╔═██╗        ██║   ██║╚════██║
╚██████╔╝██║██║  ██╗       ╚██████╔╝███████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝       ╚═════╝ ╚══════╝

Size rule:  oik = 10.5px,  OS = 14px  (75% ratio, baseline-aligned)
Color rule: oik = 2 brightness steps below OS per line

Gradient direction (V2 center-bright):

  Line 1:  ░░░░  dim edge
  Line 2:  ▒▒▒▒  building
  Line 3:  ████  HOT CENTER    ← peak glow
  Line 4:  ▒▒▒▒  building
  Line 5:  ░░░░  dim edge
  Line 6:  ░░░░  trailing shadow
```
