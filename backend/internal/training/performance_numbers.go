package training

import (
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"strings"
)

func performanceDigits(raw string) string {
	return strings.Map(func(r rune) rune {
		if digit, valid, _ := libraryDigits(string(r)); valid {
			return rune(digit[0])
		}
		return r
	}, raw)
}

var performanceIntegerSyntax = regexp.MustCompile(`^[+-]?[0-9]+(?:_[0-9]+)*$`)

func performanceInteger(raw string) (*big.Int, bool) {
	raw = performanceDigits(pythonTrim(raw))
	if !performanceIntegerSyntax.MatchString(raw) {
		return nil, false
	}
	raw = strings.ReplaceAll(raw, "_", "")
	if len(strings.TrimLeft(raw, "+-")) > 4300 {
		return nil, false
	}
	return new(big.Int).SetString(raw, 10)
}

type performanceDecimal struct {
	coefficient *big.Int
	exponent    int64
	negative    bool
	special     string
}

var performanceDecimalSyntax = regexp.MustCompile(`^([+-]?)([0-9]*)(?:\.([0-9]*))?(?:[eE]([+-]?[0-9]+))?$`)
var performanceNaNSyntax = regexp.MustCompile(`^(s?nan)([0-9]*)$`)

func parsePerformanceDecimal(raw string) (performanceDecimal, bool) {
	raw = strings.ReplaceAll(performanceDigits(pythonTrim(raw)), "_", "")
	d := performanceDecimal{negative: strings.HasPrefix(raw, "-")}
	lower := strings.ToLower(raw)
	if strings.HasPrefix(lower, "+") || strings.HasPrefix(lower, "-") {
		lower = lower[1:]
	}
	if lower == "inf" || lower == "infinity" {
		d.special = "Infinity"
		return d, true
	}
	if parts := performanceNaNSyntax.FindStringSubmatch(lower); parts != nil {
		d.special = "NaN"
		if parts[1] == "snan" {
			d.special = "sNaN"
		}
		payload := strings.TrimLeft(parts[2], "0")
		if len(payload) > 28 {
			payload = strings.TrimLeft(payload[len(payload)-28:], "0")
		}
		d.special += payload
		return d, true
	}
	parts := performanceDecimalSyntax.FindStringSubmatch(raw)
	if parts == nil || parts[2] == "" && parts[3] == "" {
		return d, false
	}
	if parts[4] != "" {
		var err error
		d.exponent, err = strconv.ParseInt(parts[4], 10, 64)
		if err != nil {
			return d, false
		}
	}
	if d.exponent < math.MinInt64+int64(len(parts[3])) {
		return d, false
	}
	d.exponent -= int64(len(parts[3]))
	d.coefficient, _ = new(big.Int).SetString(parts[2]+parts[3], 10)
	return d, true
}

func decimalTenPower(n int64) *big.Int { return new(big.Int).Exp(big.NewInt(10), big.NewInt(n), nil) }

// Match Decimal addition with Python's default 28-digit, half-even context and
// the wire format's final format(...,"f").rstrip("0").rstrip("."). The latter also
// strips zeroes from integers, so 100+0 is "1" but 100+0.0 is "100".
func formatGrossWeight(zfw, fuel string) (string, error) {
	a, ok := parsePerformanceDecimal(zfw)
	if !ok {
		return "", nil
	}
	b, ok := parsePerformanceDecimal(fuel)
	if !ok {
		return "", nil
	}
	for _, d := range []performanceDecimal{a, b} {
		if strings.HasPrefix(d.special, "sNaN") {
			return "", nil
		}
	}
	for _, d := range []performanceDecimal{a, b} {
		if strings.HasPrefix(d.special, "NaN") {
			formatted := strings.TrimRight(d.special, "0")
			if d.negative {
				return "-" + formatted, nil
			}
			return formatted, nil
		}
	}
	if a.special == "Infinity" || b.special == "Infinity" {
		if a.special == b.special && a.negative != b.negative {
			return "", nil
		}
		d := a
		if d.special == "" {
			d = b
		}
		if d.negative {
			return "-Infinity", nil
		}
		return "Infinity", nil
	}
	if a.coefficient.Sign() == 0 && b.coefficient.Sign() == 0 {
		prefix := ""
		if a.negative && b.negative {
			prefix = "-"
		}
		if min(a.exponent, b.exponent) < 0 {
			return prefix + "0", nil
		}
		return prefix, nil
	}
	hi := max(a.exponent, b.exponent)
	if a.coefficient.Sign() == 0 {
		hi = b.exponent
	}
	if b.coefficient.Sign() == 0 {
		hi = a.exponent
	}
	lo := min(a.exponent, b.exponent)
	// Very separated operands cannot cancel. Keeping their coefficients and a
	// guard wider than both coefficients plus precision preserves the sticky
	// remainder and every half-even decision without expanding huge exponents.
	guard := int64(len(a.coefficient.String()) + len(b.coefficient.String()) + 32)
	cut := int64(math.MinInt64)
	if hi >= math.MinInt64+guard {
		cut = hi - guard
	}
	exponent := max(lo, cut)
	sum := new(big.Int)
	for _, d := range []performanceDecimal{a, b} {
		if d.coefficient.Sign() == 0 {
			continue
		}
		n := new(big.Int).Set(d.coefficient)
		if d.exponent > exponent {
			n.Mul(n, decimalTenPower(d.exponent-exponent))
		}
		if d.negative {
			n.Neg(n)
		}
		sum.Add(sum, n)
	}
	negative := sum.Sign() < 0 || sum.Sign() == 0 && a.negative && b.negative
	sum.Abs(sum)
	if exponent < -2000000 {
		// Coefficients come from 50-character DB columns; this lies far below
		// the context's smallest subnormal, including any possible carry.
		sum.SetInt64(0)
		exponent = -1000026
	} else {
		digits := int64(len(sum.String()))
		if sum.Sign() != 0 && exponent > 999999-digits+1 {
			return "", fmt.Errorf("decimal gross weight overflow")
		}
		target := max(exponent+max(int64(0), digits-28), int64(-1000026))
		if shift := target - exponent; shift > 0 {
			if shift > digits+1 {
				sum.SetInt64(0)
			} else {
				divisor := decimalTenPower(shift)
				quotient, remainder := new(big.Int), new(big.Int)
				quotient.QuoRem(sum, divisor, remainder)
				comparison := remainder.Lsh(remainder, 1).Cmp(divisor)
				if comparison > 0 || comparison == 0 && quotient.Bit(0) == 1 {
					quotient.Add(quotient, big.NewInt(1))
				}
				sum = quotient
			}
			exponent = target
			if len(sum.String()) > 28 {
				sum.Quo(sum, big.NewInt(10))
				exponent++
			}
		}
	}
	if sum.Sign() != 0 && exponent > 999999-int64(len(sum.String()))+1 {
		return "", fmt.Errorf("decimal gross weight overflow")
	}
	prefix := ""
	if negative {
		prefix = "-"
	}
	if sum.Sign() == 0 {
		if exponent < 0 {
			return prefix + "0", nil
		}
		return prefix, nil
	}
	digits := sum.String()
	var result string
	if exponent >= 0 {
		result = digits + strings.Repeat("0", int(exponent))
	} else if places := int(-exponent); places >= len(digits) {
		result = "0." + strings.Repeat("0", places-len(digits)) + digits
	} else {
		result = digits[:len(digits)-places] + "." + digits[len(digits)-places:]
	}
	return strings.TrimRight(strings.TrimRight(prefix+result, "0"), "."), nil
}
