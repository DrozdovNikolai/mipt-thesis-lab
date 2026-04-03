package auth

import (
	"fmt"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"golang.org/x/net/idna"
	"golang.org/x/text/unicode/norm"
	"golang.org/x/text/unicode/runenames"
	"north55/backend/internal/platform"
)

var userEmailMapping = idna.New(idna.MapForLookup(), idna.Transitional(false), idna.StrictDomainName(false), idna.ValidateLabels(false), idna.CheckHyphens(false), idna.CheckJoiners(false), idna.VerifyDNSLength(false))

// Frozen idna checks directionality per label, including its own error text.
var userEmailIDNA = idna.New(idna.StrictDomainName(true), idna.ValidateLabels(true), idna.Transitional(false), idna.VerifyDNSLength(false))

func userPythonSpace(r rune) bool        { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }
func userPythonTrim(value string) string { return strings.TrimFunc(value, userPythonSpace) }

func userEmailField(create bool) platform.Field {
	return platform.Field{Name: "email", Kind: "string", Required: create, Nullable: !create, Before: func(value any, loc []any) (any, []any) {
		input, ok := value.(string)
		if !ok {
			return value, nil
		}
		normalized, reason := normalizeUserEmail(input)
		if reason != "" {
			detail := platform.Detail("value_error", "value is not a valid email address: "+reason, loc, value, map[string]any{"reason": reason})
			// EmailStr uses PydanticCustomError, which omits the documentation URL.
			delete(detail, "url")
			return nil, []any{detail}
		}
		return normalized, nil
	}}
}

func userEmailPretty(value string) string {
	value = userPythonTrim(value)
	if !strings.HasSuffix(value, ">") {
		return value
	}
	index := strings.LastIndexByte(value, '<')
	if index < 0 {
		return value
	}
	name := userPythonTrim(value[:index])
	valid := name == "" || len(name) >= 3 && name[0] == '"' && name[len(name)-1] == '"'
	if !valid {
		valid = true
		for _, r := range name {
			if !userPythonSpace(r) && !unicode.IsLetter(r) && !unicode.IsNumber(r) && !strings.ContainsRune("_!#$%&'*+-/=?^`{|}~", r) {
				valid = false
				break
			}
		}
	}
	inside := value[index+1 : len(value)-1]
	if !valid || inside == "" || strings.ContainsRune(inside, '\n') {
		return value
	}
	return userPythonTrim(inside)
}

func userEmailChar(r rune) string {
	if r == '\\' {
		return `"\"`
	}
	if !userEmailRange(r, userEmailUnicode.Unassigned) && (unicode.IsLetter(r) || unicode.IsNumber(r) || unicode.IsPunct(r) || unicode.IsSymbol(r)) {
		if r == '\'' {
			return `"'"`
		}
		return "'" + string(r) + "'"
	}
	if !unicode.IsControl(r) && !userEmailRange(r, userEmailUnicode.Unassigned) {
		if name := runenames.Name(r); name != "" && !strings.HasPrefix(name, "<") {
			return name
		}
	}
	if r < 0xffff {
		return fmt.Sprintf("U+%04X", r)
	}
	return fmt.Sprintf("U+%08X", r)
}

func userEmailBadChars(value string, invalid func(rune) bool) string {
	set := map[string]bool{}
	for _, r := range value {
		if invalid(r) {
			set[userEmailChar(r)] = true
		}
	}
	items := []string{}
	for item := range set {
		items = append(items, item)
	}
	sort.Strings(items)
	return strings.Join(items, ", ")
}

func userEmailUnsafe(value string, allowSpace bool) string {
	set := map[rune]bool{}
	for index, r := range []rune(value) {
		if !userEmailRange(r, userEmailUnicode.Unassigned) && (unicode.IsLetter(r) || unicode.IsNumber(r) || unicode.IsPunct(r) || unicode.IsSymbol(r)) {
			continue
		}
		if unicode.IsMark(r) && index > 0 && !userEmailRange(r, userEmailUnicode.Unassigned) {
			continue
		}
		if unicode.Is(unicode.Zs, r) && allowSpace {
			continue
		}
		set[r] = true
	}
	if len(set) == 0 {
		return ""
	}
	chars := []rune{}
	for r := range set {
		chars = append(chars, r)
	}
	sort.Slice(chars, func(i, j int) bool { return chars[i] < chars[j] })
	items := []string{}
	for _, r := range chars {
		items = append(items, userEmailChar(r))
	}
	return "The email address contains unsafe characters: " + strings.Join(items, ", ") + "."
}

func userEmailLength(excess int, atLeast bool) string {
	prefix, suffix := "", ""
	if atLeast {
		prefix = "at least "
	}
	if excess > 1 {
		suffix = "s"
	}
	return fmt.Sprintf("(%s%d character%s too many)", prefix, excess, suffix)
}

func userEmailDots(value string, domain bool) string {
	start, end := "An email address cannot start with a %s.", "An email address cannot have a %s immediately before the @-sign."
	if domain {
		start, end = "An email address cannot have a %s immediately after the @-sign.", "An email address cannot end with a %s."
	}
	if strings.HasSuffix(value, ".") {
		return fmt.Sprintf(end, "period")
	}
	if strings.HasPrefix(value, ".") {
		return fmt.Sprintf(start, "period")
	}
	if strings.Contains(value, "..") {
		return "An email address cannot have two periods in a row."
	}
	if domain {
		if strings.HasSuffix(value, "-") {
			return fmt.Sprintf(end, "hyphen")
		}
		if strings.HasPrefix(value, "-") {
			return fmt.Sprintf(start, "hyphen")
		}
		if strings.Contains(value, ".-") || strings.Contains(value, "-.") {
			return "An email address cannot have a period and a hyphen next to each other."
		}
	}
	return ""
}
