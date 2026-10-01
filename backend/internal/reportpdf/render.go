package reportpdf

import (
	"bytes"
	_ "embed"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/signintech/gopdf"
)

//go:embed fonts/DejaVuSans.ttf
var regularFont []byte

//go:embed fonts/DejaVuSans-Bold.ttf
var boldFont []byte

const (
	mm           = 72.0 / 25.4
	pageWidth    = 210 * mm
	pageHeight   = 297 * mm
	left         = 10 * mm
	right        = 200 * mm
	contentWidth = 190 * mm
	pageTop      = 12*mm + 6
	bottom       = pageHeight - 12*mm - 6
)

type renderer struct {
	pdf   gopdf.GoPdf
	y     float64
	page  int
	err   error
	title string
}

type textStyle struct {
	size, leading float64
	bold          bool
	align         int
	color         [3]uint8
}
type paragraph struct {
	lines []string
	style textStyle
}
type cellContent struct {
	paragraphs []paragraph
	middle     bool
	minimum    float64
}

var (
	bodyStyle    = textStyle{size: 8, leading: 9.5, align: gopdf.Left}
	headerStyle  = textStyle{size: 7.5, leading: 9, bold: true, align: gopdf.Center}
	commentStyle = textStyle{size: 8, leading: 10, align: gopdf.Left}
)

// Render lays out the assessment on A4 pages.
func Render(report Report) ([]byte, error) {
	r := &renderer{title: report.Title}
	r.pdf.Start(gopdf.Config{PageSize: gopdf.Rect{W: pageWidth, H: pageHeight}})
	if err := r.pdf.AddTTFFontByReader("regular", bytes.NewReader(regularFont)); err != nil {
		return nil, err
	}
	if err := r.pdf.AddTTFFontByReader("bold", bytes.NewReader(boldFont)); err != nil {
		return nil, err
	}
	r.pdf.SetInfo(gopdf.PdfInfo{Title: report.Title})
	r.newPage()
	r.header(report)
	r.spacer(5 * mm)
	r.personTable(report)
	r.spacer(5 * mm)
	if report.LatestSwap != nil {
		r.swapTable(*report.LatestSwap)
		r.spacer(5 * mm)
	}
	r.gradeTable(report.Grades)
	r.spacer(5 * mm)
	r.section("Comments", true)
	r.spacer(2 * mm)
	if len(report.Comments) == 0 {
		r.drawParagraph(r.para("No instructor comments", contentWidth-12, bodyStyle), left+6, r.y, contentWidth-12)
		r.y += 9.5
	} else {
		for _, comment := range report.Comments {
			r.comment(comment)
			r.spacer(2 * mm)
		}
	}
	r.spacer(4 * mm)
	if strings.TrimSpace(report.Summary) != "" {
		r.summary(report.Summary)
		r.spacer(4 * mm)
	}
	r.overall(report)
	if r.err != nil {
		return nil, r.err
	}
	return r.pdf.GetBytesPdfReturnErr()
}

func (r *renderer) font(bold bool, size float64) {
	if r.err != nil {
		return
	}
	family := "regular"
	if bold {
		family = "bold"
	}
	r.err = r.pdf.SetFont(family, "", size)
}
func (r *renderer) text(value string, x, y, width float64, style textStyle) {
	if r.err != nil {
		return
	}
	r.font(style.bold, style.size)
	r.pdf.SetTextColor(style.color[0], style.color[1], style.color[2])
	measured, err := r.pdf.MeasureTextWidth(value)
	if err != nil {
		r.err = err
		return
	}
	if style.align == gopdf.Center {
		x += (width - measured) / 2
	} else if style.align == gopdf.Right {
		x += width - measured
	}
	r.pdf.SetXY(x, y)
	r.err = r.pdf.Text(value)
	r.pdf.SetTextColor(0, 0, 0)
}
func (r *renderer) para(value string, width float64, style textStyle) paragraph {
	r.font(style.bold, style.size)
	result := paragraph{style: style}
	if r.err != nil {
		return result
	}
	if width <= 0 {
		r.err = fmt.Errorf("PDF cell content has no printable width")
		return result
	}
	for _, part := range strings.Split(clean(value), "\n") {
		part = strings.Join(strings.Fields(part), " ")
		if part == "" {
			result.lines = append(result.lines, "")
			continue
		}
		oversized := false
		for _, char := range part {
			charWidth, err := r.pdf.MeasureTextWidth(string(char))
			if err != nil {
				r.err = err
				return result
			}
			if charWidth > width {
				oversized = true
			}
		}
		var lines []string
		var err error
		if oversized {
			// ReportLab allows a single glyph to exceed a positive cell width.
			// gopdf repeatedly retries that glyph, so consume it explicitly.
			lines, err = r.wrapOversized(part, width)
		} else {
			lines, err = r.pdf.SplitTextWithWordWrap(part, width)
		}
		if err != nil {
			r.err = err
			return result
		}
		result.lines = append(result.lines, lines...)
	}
	return result
}

func (r *renderer) wrapOversized(value string, width float64) ([]string, error) {
	var result []string
	remaining := []rune(value)
	for len(remaining) > 0 {
		count, lastSpace := 0, -1
		for count < len(remaining) {
			measured, err := r.pdf.MeasureTextWidth(string(remaining[:count+1]))
			if err != nil {
				return nil, err
			}
			if measured > width {
				break
			}
			if remaining[count] == ' ' {
				lastSpace = count
			}
			count++
		}
		if count == 0 {
			count = 1
		} else if count < len(remaining) && lastSpace > 0 {
			count = lastSpace
		}
		result = append(result, strings.TrimSpace(string(remaining[:count])))
		remaining = []rune(strings.TrimLeft(string(remaining[count:]), " "))
	}
	return result, nil
}
func (p paragraph) height() float64 { return float64(len(p.lines)) * p.style.leading }
func (c cellContent) height() float64 {
	var h float64
	for _, p := range c.paragraphs {
		h += p.height()
	}
	return math.Max(h, c.minimum)
}
