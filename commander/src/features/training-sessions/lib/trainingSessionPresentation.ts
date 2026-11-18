export const formatTrainingSessionTimestamp = (value: string | null) => {
  if (!value) return '—'

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export const getPersonLabel = (
  firstName: string | null,
  lastName: string | null,
  fallback: string,
) => {
  const fullName = [firstName?.trim(), lastName?.trim()].filter(Boolean).join(' ').trim()
  return fullName || fallback
}

export const getTrainingRoleLabel = (trainingRole: string | null | undefined) => {
  if (trainingRole === 'cm1') return 'CM 1'
  if (trainingRole === 'cm2') return 'CM 2'
  return '—'
}

export const getTrainingRoleBadgeLabel = (trainingRole: string | null | undefined) => {
  if (trainingRole === 'cm1') return 'Role: CM 1'
  if (trainingRole === 'cm2') return 'Role: CM 2'
  return null
}

export const formatDurationMinutes = (value: number | null) => {
  if (value === null || Number.isNaN(value)) return 'Duration not set'
  return `${value} min`
}

export const formatExerciseOffsetSeconds = (value: number) => {
  const minutes = Math.floor(value / 60)
  const seconds = value % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
