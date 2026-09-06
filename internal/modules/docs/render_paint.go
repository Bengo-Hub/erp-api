package docs

import (
	"strings"

	"github.com/go-pdf/fpdf"
)

// Page geometry (A4 portrait, mm).
const (
	pageW    = 210.0
	pageH    = 297.0
	margin   = 13.0
	leftX    = margin
	rightX   = pageW - margin
	contentW = pageW - 2*margin
)

// painter wraps an fpdf document with the palette and the small set of drawing
// primitives used throughout the template.
type painter struct {
	pdf *fpdf.Fpdf
	tr  func(string) string
	pal palette
}

func newPainter(pdf *fpdf.Fpdf, pal palette) *painter {
	base := pdf.UnicodeTranslatorFromDescriptor("") // UTF-8 → cp1252 (core fonts are 256-glyph)
	// The translator maps UTF-8 → cp1252 single bytes (≤0xFF), which core fonts render — including
	// accented Latin-1 like "é" (Café) and punctuation like em-dash/×. We only sanitize INVALID UTF-8
	// in the input first: a stray byte would decode to U+FFFD which the translator can't map, and
	// passing malformed bytes to MultiCell/SplitText can panic. Translating already-valid UTF-8 never
	// yields a wide byte, so no post-processing is needed — a prior version here ranged over the
	// translator's output (a raw cp1252 byte string, not UTF-8) looking for runes above 0xFF, which
	// misdecoded every translated non-ASCII byte as U+FFFD and corrupted it to "?" (dashes, ×, é, …).
	tr := func(s string) string {
		return base(strings.ToValidUTF8(s, ""))
	}
	return &painter{pdf: pdf, tr: tr, pal: pal}
}

func (p *painter) setFill(c rgb) { p.pdf.SetFillColor(c.r, c.g, c.b) }
func (p *painter) setText(c rgb) { p.pdf.SetTextColor(c.r, c.g, c.b) }
func (p *painter) setDraw(c rgb) { p.pdf.SetDrawColor(c.r, c.g, c.b) }

// gradient fills a rounded rect with a horizontal linear gradient from c1 to c2.
func (p *painter) gradient(x, y, w, h, r float64, c1, c2 rgb) {
	p.pdf.ClipRoundedRect(x, y, w, h, r, false)
	p.pdf.LinearGradient(x, y, w, h, c1.r, c1.g, c1.b, c2.r, c2.g, c2.b, 0, 0, 1, 0)
	p.pdf.ClipEnd()
}

// box draws a white rounded rect with a hairline border.
func (p *painter) box(x, y, w, h float64) {
	p.setDraw(p.pal.line)
	p.setFill(p.pal.white)
	p.pdf.SetLineWidth(0.2)
	p.pdf.RoundedRect(x, y, w, h, 1.6, "1234", "D")
}

// text draws a string with its top at y (baseline computed for predictable placement).
func (p *painter) text(x, y float64, s, font string, sz float64, c rgb) {
	p.pdf.SetFont("Helvetica", font, sz)
	p.setText(c)
	p.pdf.Text(x, y+sz*0.3528*0.82, p.tr(s))
}

// textR draws a right-aligned string ending at rx.
func (p *painter) textR(rx, y float64, s, font string, sz float64, c rgb) {
	p.pdf.SetFont("Helvetica", font, sz)
	p.setText(c)
	t := p.tr(s)
	p.pdf.Text(rx-p.pdf.GetStringWidth(t), y+sz*0.3528*0.82, t)
}

// hline draws a horizontal hairline in the line color.
func (p *painter) hline(x1, y, x2 float64) {
	p.setDraw(p.pal.line)
	p.pdf.SetLineWidth(0.15)
	p.pdf.Line(x1, y, x2, y)
}

// kv prints a label + bold value pair (label muted, value navy), value offset by 24mm.
func (p *painter) kv(x, y float64, k, v string) {
	p.text(x, y, k, "", 9, p.pal.muted)
	p.text(x+24, y, v, "B", 9, p.pal.navy)
}

// multiCell wraps text at the given x/width using the given font/size/color.
func (p *painter) multiCell(x, y, w, lineH float64, s, font string, sz float64, c rgb) float64 {
	p.pdf.SetFont("Helvetica", font, sz)
	p.setText(c)
	p.pdf.SetXY(x, y)
	p.pdf.MultiCell(w, lineH, p.tr(s), "", "L", false)
	return p.pdf.GetY()
}

// splitText wraps fpdf's SplitText for text already run through p.tr. Unlike MultiCell/Cell/
// GetStringWidth, SplitText always UTF-8-decodes its input regardless of the active font's
// encoding, so a translated core-font byte above 0x7F (e.g. cp1252 0x95 for "•") is invalid
// UTF-8 on its own and decodes to U+FFFD, which then panics indexing the 256-entry width
// table. Re-encoding each byte as its own UTF-8 rune recovers the exact code points SplitText
// expects, without changing what MultiCell/Cell render (they still receive p.tr's raw bytes).
func (p *painter) splitText(s string, w float64) []string {
	bs := []byte(s)
	rs := make([]rune, len(bs))
	for i, b := range bs {
		rs[i] = rune(b)
	}
	return p.pdf.SplitText(string(rs), w)
}
