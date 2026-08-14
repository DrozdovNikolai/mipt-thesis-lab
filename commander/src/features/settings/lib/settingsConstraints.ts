export const FLIGHT_TYPE_NAME_MAX_LENGTH = 100

export const FLIGHT_TYPE_THRESHOLD_MAX_INTEGER_DIGITS = 6
export const FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS = 4
export const FLIGHT_TYPE_THRESHOLD_MAX_VALUE = '999999.9999'
export const FLIGHT_TYPE_THRESHOLD_INPUT_MAX_LENGTH =
  FLIGHT_TYPE_THRESHOLD_MAX_INTEGER_DIGITS + 1 + FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS

const THRESHOLD_VALID_PREFIX_PATTERN = /^\d*(?:\.\d*)?/
const THRESHOLD_VALIDATION_PATTERN = new RegExp(
  `^\\d{1,${FLIGHT_TYPE_THRESHOLD_MAX_INTEGER_DIGITS}}(?:\\.\\d{0,${FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS}})?$`,
)

export const clampFlightTypeNameInput = (value: string) =>
  value.slice(0, FLIGHT_TYPE_NAME_MAX_LENGTH)

export const sanitizeFlightTypeThresholdInput = (value: string) => {
  const candidate = value.trim().match(THRESHOLD_VALID_PREFIX_PATTERN)?.[0] ?? ''
  if (!candidate) return ''

  const hasDecimalSeparator = candidate.includes('.')
  const [rawIntegerPart = '', rawFractionalPart = ''] = candidate.split('.', 2)
  const integerPart = rawIntegerPart.slice(0, FLIGHT_TYPE_THRESHOLD_MAX_INTEGER_DIGITS)
  const fractionalPart = rawFractionalPart.slice(0, FLIGHT_TYPE_THRESHOLD_MAX_DECIMAL_DIGITS)

  if (hasDecimalSeparator && integerPart.length === 0) {
    return fractionalPart.length > 0 ? `0.${fractionalPart}` : '0.'
  }

  return hasDecimalSeparator ? `${integerPart}.${fractionalPart}` : integerPart
}

export const isFlightTypeThresholdInputValid = (value: string) => {
  const trimmed = value.trim()
  if (!trimmed) return true
  return THRESHOLD_VALIDATION_PATTERN.test(trimmed)
}
