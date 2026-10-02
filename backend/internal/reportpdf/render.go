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
func (r *renderer) drawParagraph(p paragraph, x, y, width float64) {
	for _, line := range p.lines {
		r.text(line, x, y+p.style.size, width, p.style)
		y += p.style.leading
	}
}
func (r *renderer) newPage() {
	r.pdf.AddPage()
	r.page++
	r.y = pageTop
	r.text(fmt.Sprintf("Page %d", r.page), left, pageHeight-6*mm, contentWidth, textStyle{size: 7, align: gopdf.Right, color: [3]uint8{85, 85, 85}})
	if r.page > 1 {
		r.text("55NORD", left, 8*mm, 210, textStyle{size: 9, bold: true, color: [3]uint8{64, 64, 64}})
		r.text(clean(r.title)+" - continued", left, 8*mm, contentWidth, textStyle{size: 8, align: gopdf.Right, color: [3]uint8{64, 64, 64}})
	}
}
func (r *renderer) ensure(height float64) {
	if height > bottom-pageTop {
		r.err = fmt.Errorf("PDF table row exceeds printable page height")
		return
	}
	if r.y+height > bottom {
		r.newPage()
	}
}

func (r *renderer) spacer(height float64) {
	r.ensure(height)
	r.y += height
}
func (r *renderer) border(x, y, w, h float64, background *[3]uint8) {
	r.pdf.SetStrokeColor(64, 64, 64)
	r.pdf.SetLineWidth(.4)
	style := "D"
	if background != nil {
		r.pdf.SetFillColor(background[0], background[1], background[2])
		style = "DF"
	}
	r.pdf.RectFromUpperLeftWithStyle(x, y, w, h, style)
}
func rowHeight(cells []cellContent) float64 {
	h := 0.0
	for _, c := range cells {
		h = math.Max(h, c.height())
	}
	return h + 8
}
func (r *renderer) row(x float64, widths []float64, cells []cellContent, background *[3]uint8) {
	h := rowHeight(cells)
	r.ensure(h)
	for i, c := range cells {
		r.border(x, r.y, widths[i], h, background)
		y := r.y + 4
		if c.middle {
			y += (h - 8 - c.height()) / 2
		}
		for _, p := range c.paragraphs {
			r.drawParagraph(p, x+4, y, widths[i]-8)
			y += p.height()
		}
		x += widths[i]
	}
	r.y += h
}
func (r *renderer) content(value string, width float64, style textStyle) cellContent {
	return cellContent{paragraphs: []paragraph{r.para(value, width-8, style)}}
}
func (r *renderer) header(report Report) {
	titleWidth := 135*mm - 12
	title := r.para(report.Title, titleWidth, textStyle{size: 12, leading: 14, bold: true, align: gopdf.Right})
	const logoHeight = 26
	innerHeight := math.Max(logoHeight, title.height())
	height := innerHeight + 7
	r.ensure(height)
	x := left + 6
	y := r.y + 3 + (innerHeight-logoHeight)/2 + 24
	for i, value := range []string{"5", "5", "NORD"} {
		color := [3]uint8{64, 64, 64}
		if i == 0 {
			color = [3]uint8{247, 208, 70}
		} else if i == 1 {
			color = [3]uint8{223, 165, 57}
		}
		r.text(value, x, y, 55*mm, textStyle{size: 24, bold: true, color: color})
		w, err := r.pdf.MeasureTextWidth(value)
		if err != nil {
			r.err = err
		}
		x += w
	}
	r.drawParagraph(title, left+55*mm+6, r.y+3+(innerHeight-title.height())/2, titleWidth)
	r.pdf.SetStrokeColor(64, 64, 64)
	r.pdf.SetLineWidth(1)
	r.pdf.Line(left, r.y+height, right, r.y+height)
	r.y += height
}
func (r *renderer) field(label, value string, width float64) cellContent {
	return cellContent{paragraphs: []paragraph{
		r.para(label, width-8, textStyle{size: 7, leading: 8.5, bold: true, align: gopdf.Left}),
		r.para(value, width-8, bodyStyle),
	}}
}
func (r *renderer) personTable(report Report) {
	w := 38 * mm
	r.row(left, []float64{3 * w, 2 * w}, []cellContent{r.field("Trainee", report.Trainee.Name, 3*w), r.field("Instructor", report.Instructor.Name, 2*w)}, nil)
	date := "-"
	if report.CompletedAt != nil {
		date = report.CompletedAt.Format("02.01.2006")
	}
	fields := [2][5][2]string{
		{{"Date", date}, {"License", report.Trainee.License}, {"PF duration", duration(report.Durations.PFMs)}, {"Location", "-"}, {"Role source", strings.ReplaceAll(report.Durations.Source, "_", " ")}},
		{{"Rank", report.Trainee.Position}, {"Type rating", first(report.Trainee.AircraftType, report.AircraftCode)}, {"PM duration", duration(report.Durations.PMMs)}, {"FSTD ID", "-"}, {"Reserved", "-"}},
	}
	for _, fields := range fields {
		var cells []cellContent
		for _, field := range fields {
			cells = append(cells, r.field(field[0], field[1], w))
		}
		r.row(left, []float64{w, w, w, w, w}, cells, nil)
	}
}
func (r *renderer) section(value string, center bool) {
	align := gopdf.Left
	if center {
		align = gopdf.Center
	}
	p := r.para(value, contentWidth-12, textStyle{size: 10, leading: 12, bold: true, align: align})
	r.ensure(p.height())
	r.drawParagraph(p, left+6, r.y, contentWidth-12)
	r.y += p.height()
}
func (r *renderer) gradeTable(grades []Grade) {
	items := append([]Grade(nil), grades...)
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].OrderIndex != items[j].OrderIndex {
			return items[i].OrderIndex < items[j].OrderIndex
		}
		return items[i].ID < items[j].ID
	})
	firstWidth := 24 * mm
	if len(items) == 0 {
		h := 17.0
		r.ensure(h)
		x := left + (contentWidth-firstWidth)/2
		r.border(x, r.y, firstWidth, h, nil)
		p := r.para("Grading", firstWidth-8, headerStyle)
		r.drawParagraph(p, x+4, r.y+(h-p.height())/2, firstWidth-8)
		r.y += h
		return
	}
	w := (contentWidth - firstWidth) / float64(len(items))
	var headers, values []cellContent
	for _, item := range items {
		headers = append(headers, r.content(item.Code, w, headerStyle))
		style := textStyle{size: 8, leading: 10, bold: true, align: gopdf.Center}
		if red, green, blue, ok := parseHex(item.ColorHex); ok {
			style.color = [3]uint8{red, green, blue}
		}
		values = append(values, r.content(first(item.Label, "-"), w, style))
	}
	h1, h2 := rowHeight(headers), rowHeight(values)
	r.ensure(h1 + h2)
	r.border(left, r.y, firstWidth, h1+h2, nil)
	p := r.para("Grading", firstWidth-8, headerStyle)
	r.drawParagraph(p, left+4, r.y+(h1+h2-p.height())/2, firstWidth-8)
	widths := make([]float64, len(items))
	for i := range widths {
		widths[i] = w
	}
	r.row(left+firstWidth, widths, headers, nil)
	r.row(left+firstWidth, widths, values, nil)
}
func (r *renderer) swapTable(swap RoleChange) {
	r.section("Latest accepted crew swap", false)
	r.spacer(2 * mm)
	context := swap.ExerciseLabel
	if swap.Attempt != nil {
		context += fmt.Sprintf(" · Attempt %d", *swap.Attempt)
	}
	if swap.OffsetMs != nil {
		context += " · " + duration(*swap.OffsetMs)
	}
	widths := []float64{42 * mm, 40 * mm, 54 * mm, 54 * mm}
	var headers, values []cellContent
	for i, value := range []string{"Context", "Accepted", "Before latest swap", "Current assignment"} {
		headers = append(headers, r.content(value, widths[i], headerStyle))
	}
	for i, value := range []string{context, fmt.Sprintf("%s · revision %d", swap.AcceptedAt.Format("02.01.2006 15:04"), swap.Revision), swap.Before, swap.After} {
		values = append(values, r.content(value, widths[i], bodyStyle))
	}
	r.ensure(rowHeight(headers) + rowHeight(values))
	r.row(left, widths, headers, &[3]uint8{244, 244, 244})
	r.row(left, widths, values, nil)
}
