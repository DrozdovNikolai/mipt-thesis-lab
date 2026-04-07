package auth

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"net/netip"
	"sort"
	"strconv"
	"strings"
	"unicode"

	"golang.org/x/net/idna"
	"golang.org/x/text/unicode/bidi"
)

// Unicode 14 and IDNA Unicode 17 tables.
//
//go:embed user_email_unicode.json
var userEmailUnicodeJSON []byte

var userEmailUnicode = func() struct {
	PValid            [][2]rune `json:"PVALID"`
	ContextJ          [][2]rune `json:"CONTEXTJ"`
	ContextO          [][2]rune `json:"CONTEXTO"`
	Printable         [][2]rune `json:"PRINTABLE"`
	Unassigned        [][2]rune `json:"UNASSIGNED"`
	MappingDisallowed [][2]rune `json:"UTS46_DISALLOWED"`
	Digits            [][2]rune `json:"DIGITS"`
	DecimalZeroes     []rune    `json:"DECIMAL_ZEROES"`
} {
	var value struct {
		PValid            [][2]rune `json:"PVALID"`
		ContextJ          [][2]rune `json:"CONTEXTJ"`
		ContextO          [][2]rune `json:"CONTEXTO"`
		Printable         [][2]rune `json:"PRINTABLE"`
		Unassigned        [][2]rune `json:"UNASSIGNED"`
		MappingDisallowed [][2]rune `json:"UTS46_DISALLOWED"`
		Digits            [][2]rune `json:"DIGITS"`
		DecimalZeroes     []rune    `json:"DECIMAL_ZEROES"`
	}
	if err := json.Unmarshal(userEmailUnicodeJSON, &value); err != nil {
		panic(err)
	}
	return value
}()

func userEmailRange(r rune, ranges [][2]rune) bool {
	i := sort.Search(len(ranges), func(i int) bool { return ranges[i][1] > r })
	return i < len(ranges) && ranges[i][0] <= r
}

func userEmailQuote(value string) string {
	quote := '\''
	if strings.ContainsRune(value, '\'') && !strings.ContainsRune(value, '"') {
		quote = '"'
	}
	var out strings.Builder
	out.WriteRune(quote)
	for _, r := range value {
		switch {
		case r == quote || r == '\\':
			out.WriteRune('\\')
			out.WriteRune(r)
		case r == '\n':
			out.WriteString(`\n`)
		case r == '\r':
			out.WriteString(`\r`)
		case r == '\t':
			out.WriteString(`\t`)
		case !userEmailRange(r, userEmailUnicode.Printable):
			if r <= 255 {
				fmt.Fprintf(&out, `\x%02x`, r)
			} else if r <= 65535 {
				fmt.Fprintf(&out, `\u%04x`, r)
			} else {
				fmt.Fprintf(&out, `\U%08x`, r)
			}
		default:
			out.WriteRune(r)
		}
	}
	out.WriteRune(quote)
	return out.String()
}

func userEmailMappingError(domain string, err error) string {
	if tail, ok := strings.CutPrefix(err.Error(), "idna: disallowed rune U+"); ok {
		if number, e := strconv.ParseUint(tail, 16, 32); e == nil {
			for index, r := range []rune(domain) {
				if r == rune(number) {
					return fmt.Sprintf("Codepoint U+%04X not allowed at position %d in %s", r, index+1, userEmailQuote(domain))
				}
			}
		}
	}
	return err.Error()
}

func userEmailContextO(label []rune, index int) bool {
	r := label[index]
	switch r {
	case 0xb7:
		return index > 0 && index+1 < len(label) && label[index-1] == 'l' && label[index+1] == 'l'
	case 0x375:
		return index+1 < len(label) && unicode.Is(unicode.Greek, label[index+1])
	case 0x5f3, 0x5f4:
		return index > 0 && unicode.Is(unicode.Hebrew, label[index-1])
	case 0x30fb:
		for _, other := range label {
			if other != 0x30fb && (unicode.Is(unicode.Hiragana, other) || unicode.Is(unicode.Katakana, other) || unicode.Is(unicode.Han, other)) {
				return true
			}
		}
		return false
	}
	if r >= 0x660 && r <= 0x669 {
		for _, other := range label {
			if other >= 0x6f0 && other <= 0x6f9 {
				return false
			}
		}
		return true
	}
	if r >= 0x6f0 && r <= 0x6f9 {
		for _, other := range label {
			if other >= 0x660 && other <= 0x669 {
				return false
			}
		}
		return true
	}
	return false
}

func userEmailLabel(label string) string {
	chars := []rune(label)
	if len(chars) == 0 {
		return "Empty Label"
	}
	if len(chars) >= 4 && chars[2] == '-' && chars[3] == '-' {
		return "Label has disallowed hyphens in 3rd and 4th position"
	}
	if chars[0] == '-' || chars[len(chars)-1] == '-' {
		return "Label must not start or end with a hyphen"
	}
	if unicode.IsMark(chars[0]) {
		return "Label begins with an illegal combining character"
	}
	for index, r := range chars {
		if userEmailRange(r, userEmailUnicode.PValid) {
			continue
		}
		if userEmailRange(r, userEmailUnicode.ContextJ) {
			continue
		} // Go checks ContextJ with the Bidi rule below.
		if userEmailRange(r, userEmailUnicode.ContextO) {
			if userEmailContextO(chars, index) {
				continue
			}
			return fmt.Sprintf("Codepoint U+%04X not allowed at position %d in %s", r, index+1, userEmailQuote(label))
		}
		return fmt.Sprintf("Codepoint U+%04X at position %d of %s not allowed", r, index+1, userEmailQuote(label))
	}
	return userEmailBidi(label)
}

func userEmailDecodeDomain(value string) (string, string) {
	if len(value) > 253 {
		return "", "Domain too long"
	}
	decoded, err := idna.ToUnicode(value)
	if err != nil {
		return "", err.Error()
	}
	for _, label := range strings.Split(decoded, ".") {
		if reason := userEmailLabel(label); reason != "" {
			return "", reason
		}
	}
	decoded, err = userEmailIDNA.ToUnicode(value)
	if err != nil {
		return "", err.Error()
	}
	return decoded, ""
}

func userEmailBidi(label string) string {
	chars := []rune(label)
	classes := make([]bidi.Class, len(chars))
	containsRTL := false
	for i, r := range chars {
		if userEmailRange(r, userEmailUnicode.Unassigned) {
			return fmt.Sprintf("Unknown directionality in label %s at position %d", userEmailQuote(label), i+1)
		}
		property, _ := bidi.LookupRune(r)
		classes[i] = property.Class()
		if classes[i] == bidi.R || classes[i] == bidi.AL || classes[i] == bidi.AN {
			containsRTL = true
		}
	}
	if !containsRTL {
		return ""
	}
	rtl := classes[0] == bidi.R || classes[0] == bidi.AL
	if !rtl && classes[0] != bidi.L {
		return fmt.Sprintf("First codepoint in label %s must be directionality L, R or AL", userEmailQuote(label))
	}
	validEnding, hasNumber := false, false
	var number bidi.Class
	for i, class := range classes {
		neutral := class == bidi.ES || class == bidi.CS || class == bidi.ET || class == bidi.ON || class == bidi.BN || class == bidi.NSM
		valid := neutral || class == bidi.EN || rtl && (class == bidi.R || class == bidi.AL || class == bidi.AN) || !rtl && class == bidi.L
		if !valid {
			direction := "left-to-right"
			if rtl {
				direction = "right-to-left"
			}
			return fmt.Sprintf("Invalid direction for codepoint at position %d in a %s label", i+1, direction)
		}
		if class == bidi.EN || rtl && (class == bidi.R || class == bidi.AL || class == bidi.AN) || !rtl && class == bidi.L {
			validEnding = true
		} else if class != bidi.NSM {
			validEnding = false
		}
		if rtl && (class == bidi.EN || class == bidi.AN) {
			if hasNumber && number != class {
				return "Can not mix numeral types in a right-to-left label"
			}
			hasNumber, number = true, class
		}
	}
	if !validEnding {
		return "Label ends with illegal codepoint directionality"
	}
	return ""
}
