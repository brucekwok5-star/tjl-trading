---
name: markdown-to-pdf-reportlab
description: Convert markdown (.md) to a beautifully formatted PDF using ReportLab + macOS system Chinese fonts. No LaTeX, no root, no sudo. Supports CJK + English mixed text, tables, code blocks with monospace, headings, blockquotes, lists, page numbers.
---

# Markdown → PDF via ReportLab (CJK-safe, no LaTeX, no root)

When you need a polished PDF from a markdown file and macTeX/BasicTeX is unavailable (no sudo, disk space, or time), use ReportLab directly with macOS system fonts.

## When to use

- Need PDF output from .md file
- Document has mixed Chinese + English
- LaTeX/MacTeX not installed (brew install basictex needs sudo)
- Need to ship in 5 minutes, not 30 minutes

## When NOT to use

- Document needs real LaTeX-quality typography (use pandoc + xelatex + ctex)
- User has MacTeX already installed
- Document has heavy mathematical equations (use KaTeX/MathJax pipeline instead)

## Key technical insight

**`.ttc` font containers are unreliable in ReportLab for non-Latin glyphs.** A `.ttc` (TrueType Collection) holds multiple "faces" in one file; ReportLab's TTFont loader has bugs reading certain macOS .ttc faces for CJK ranges, producing **□ tofu boxes** in code blocks or tables.

**Fix: use `Arial Unicode.ttf` as the primary CJK font** (single TTF, broadest Unicode coverage of any pre-installed macOS font, including both Traditional and Simplified Chinese, Japanese kanji, Korean hangul).

Path: `/System/Library/Fonts/Supplemental/Arial Unicode.ttf`

For mono (ASCII only), `Menlo.ttc` works fine because the issue only affects CJK ranges.

## Implementation

The reference script lives at `/Users/jaydensmac/.openclaw/workspace/md_to_pdf.py` (~340 lines). Key features:

1. **CJK font fallback chain**: Arial Unicode (primary) → STHeiti → Hiragino Sans GB. First one to register wins.
2. **Style hierarchy**: Title / H1-H4 / BodyText / Blockquote / CodeInline / CodeBlock / Caption with colors, sizes, spacing.
3. **Markdown parser** (~150 lines): handles headings, paragraphs, ordered/unordered lists, blockquotes, tables (with zebra striping), code fences (```), inline code (`...`), bold (**), italic (*).
4. **Cover page**: title + author + subtitle, followed by PageBreak.
5. **Page footer**: centered page number `— N —` + top rule line.

## Usage

```bash
python3 md_to_pdf.py input.md output.pdf "Document Title"
```

## Pitfalls hit during development

1. **pip install weasyprint fails on macOS** — requires libgobject-2.0-0 native library, which needs brew + sudo. Don't use weasyprint unless you've already paid that cost.
2. **brew install basictex needs sudo** — sudo in non-PTY environment errors with "a terminal is required to read the password". Can't auto-install LaTeX in this context.
3. **TTF font glyph coverage** — Helvetica only covers Latin-1. STHeiti.ttc has CJK but ReportLab reads it wrong. Arial Unicode.ttf covers everything and just works.
4. **sed inline edits with `#` in replacement string** — sed's `|` separator swallows everything after the first `#`. Use Python `str.replace()` instead when the replacement contains comments.
5. **Preformatted (mono) font for code blocks with Chinese** — if you use `fontName=Menlo` for code blocks, any Chinese inside becomes tofu. Use `fontName=ArialUnicode` for code blocks (sacrifices ASCII monospacing, gains Chinese rendering).

## Dependencies

```bash
python3 -m pip install reportlab markdown
```

Both pure-Python, no native deps, installs in <5 seconds.

## Customization knobs

In `build_styles()`:
- `fontSize=10.5, leading=17` — body text density
- `spaceBefore=18, spaceAfter=10` — H1 spacing
- `fontSize=26` — cover title size
- Page margins: 22mm all around (modify `__init__` of `ThesisDoc`)

In `parse_table_block()`:
- Header color: `colors.HexColor("#e8eef7")` (light blue)
- Zebra stripe: `colors.HexColor("#f7f7f7")` (very light gray)

## Output expectations

- 18–22 page Chinese thesis PDF: ~480KB
- 22–25 page English thesis PDF: ~100KB
- Render time: <2 seconds for typical thesis-sized document