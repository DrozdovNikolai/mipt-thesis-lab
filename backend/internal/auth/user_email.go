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

func normalizeUserEmail(raw string) (string, string) {
	if utf8.RuneCountInString(raw) > 2048 {
		return "", "Length must not exceed 2048 characters"
	}
	value := userEmailPretty(raw)
	local, domain, quoted := "", "", false
	if strings.HasPrefix(value, "\"") {
		var decoded strings.Builder
		escaped := false
		for index, r := range value[1:] {
			if escaped {
				decoded.WriteRune(r)
				escaped = false
				continue
			}
			if r == '\\' {
				escaped = true
				continue
			}
			if r == '"' {
				end := 1 + index + 1
				if end < len(value) && value[end] == '@' {
					local, domain, quoted = decoded.String(), value[end+1:], true
				}
				break
			}
			decoded.WriteRune(r)
		}
	}
	if !quoted {
		if strings.Count(value, "@") != 1 {
			return "", "The email address is not valid. It must have exactly one @-sign."
		}
		local, domain, _ = strings.Cut(value, "@")
	}
	if local == "" {
		return "", "There must be something before the @-sign."
	}
	if length := utf8.RuneCountInString(local); length > 64 {
		return "", "The email address is too long before the @-sign " + userEmailLength(length-64, false) + "."
	}
	invalid := func(r rune) bool {
		return r < 128 && !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || strings.ContainsRune("._!#$%&'*+-/=?^`{|}~", r))
	}
	dotAtom := userEmailBadChars(local, invalid) == "" && userEmailDots(local, false) == ""
	if quoted {
		invalid = func(r rune) bool { return r < 32 || r == 127 }
	}
	if chars := userEmailBadChars(local, invalid); chars != "" {
		part := "before"
		if quoted {
			part = "in quotes before"
		}
		return "", "The email address contains invalid characters " + part + " the @-sign: " + chars + "."
	}
	if !quoted {
		if reason := userEmailDots(local, false); reason != "" {
			return "", reason
		}
	}
	asciiLocal := true
	for _, r := range local {
		if r >= 128 {
			asciiLocal = false
		}
	}
	local = norm.NFC.String(local)
	if reason := userEmailUnsafe(local, quoted && !dotAtom); reason != "" {
		return "", reason
	}
	if quoted {
		return "", "Quoting the part before the @-sign is not allowed here."
	}
	if asciiLocal && strings.Contains("|info|marketing|sales|support|abuse|noc|security|postmaster|hostmaster|usenet|news|webmaster|www|uucp|ftp|", "|"+strings.ToLower(local)+"|") {
		local = strings.ToLower(local)
	}
	if domain == "" {
		return "", "There must be something after the @-sign."
	}
	if strings.HasPrefix(domain, "[") && strings.HasSuffix(domain, "]") {
		return "", userEmailLiteral(domain[1 : len(domain)-1])
	}
	if chars := userEmailBadChars(domain, func(r rune) bool {
		return r < 128 && !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '.')
	}); chars != "" {
		return "", "The part after the @-sign contains invalid characters: " + chars + "."
	}
	if reason := userEmailUnsafe(domain, false); reason != "" {
		return "", reason
	}
	asciiDomain := true
	for _, r := range domain {
		if r >= 128 {
			asciiDomain = false
		}
	}
	if asciiDomain {
		domain = strings.ToLower(domain)
	} else {
		for index, r := range []rune(domain) {
			if userEmailRange(r, userEmailUnicode.MappingDisallowed) {
				return "", fmt.Sprintf("The part after the @-sign contains invalid characters (Codepoint U+%04X not allowed at position %d in %s).", r, index+1, userEmailQuote(domain))
			}
		}
		mapped, err := userEmailMapping.ToUnicode(domain)
		if err != nil {
			return "", "The part after the @-sign contains invalid characters (" + userEmailMappingError(domain, err) + ")."
		}
		domain = mapped
	}
	if reason := userEmailDots(domain, true); reason != "" {
		return "", reason
	}
	for _, label := range strings.Split(domain, ".") {
		if len(label) >= 4 && label[2:4] == "--" && label[:2] != "xn" {
			return "", "An email address cannot have two letters followed by two dashes immediately after the @-sign or after a period, except Punycode."
		}
	}
	encoded := domain
	encodeRequired := false
	for _, r := range domain {
		if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-' || r == '.') {
			encodeRequired = true
		}
	}
	if encodeRequired {
		for _, label := range strings.Split(domain, ".") {
			if reason := userEmailLabel(label); reason != "" {
				return "", "The part after the @-sign contains invalid characters (" + reason + ")."
			}
		}
		var err error
		encoded, err = userEmailIDNA.ToASCII(domain)
		if err != nil {
			return "", "The part after the @-sign contains invalid characters (" + err.Error() + ")."
		}
		for _, label := range strings.Split(encoded, ".") {
			if len(label) > 63 {
				return "", "The part after the @-sign contains invalid characters (Label too long)."
			}
		}
		if len(encoded) > 253 {
			return "", "The email address is too long after the @-sign."
		}
	}
	if len(encoded) > 255 {
		return "", "The email address is too long after the @-sign " + userEmailLength(len(encoded)-255, false) + "."
	}
	for _, label := range strings.Split(encoded, ".") {
		if len(label) > 63 {
			return "", "After the @-sign, periods cannot be separated by so many characters " + userEmailLength(len(label)-63, false) + "."
		}
	}
	if !strings.Contains(encoded, ".") {
		return "", "The part after the @-sign is not valid. It should have a period."
	}
	if last := encoded[len(encoded)-1]; !(last >= 'a' && last <= 'z' || last >= 'A' && last <= 'Z') {
		return "", "The part after the @-sign is not valid. It is not within a valid top-level domain."
	}
	for _, reserved := range []string{"arpa", "invalid", "local", "localhost", "onion", "test"} {
		if encoded == reserved || strings.HasSuffix(encoded, "."+reserved) {
			return "", "The part after the @-sign is a special-use or reserved name that cannot be used with email."
		}
	}
	normalDomain, reason := userEmailDecodeDomain(encoded)
	if reason != "" {
		return "", "The part after the @-sign is not valid IDNA (" + reason + ")."
	}
	normalized := local + "@" + normalDomain
	if asciiLocal && len(local+"@"+encoded) > 254 {
		reason := "(when converted to IDNA ASCII)"
		if normalized == local+"@"+encoded {
			reason = userEmailLength(len(normalized)-254, false)
		} else if n := utf8.RuneCountInString(normalized); n > 254 {
			reason = userEmailLength(n-254, true)
		}
		return "", "The email address is too long " + reason + "."
	}
	if len(normalized) > 254 {
		reason := "(when encoded in bytes)"
		if n := utf8.RuneCountInString(normalized); n > 254 {
			reason = userEmailLength(n-254, true)
		}
		return "", "The email address is too long " + reason + "."
	}
	return normalized, ""
}
