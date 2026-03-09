import { expect, it } from 'vitest'
import { resolveMediaRequestPath } from '@/shared/lib/media/resolveMediaRequestPath'

it.each([
  ['/api/media/photo.png', '/media/photo.png'],
  [' /api/media/photo.png?v=2 ', '/media/photo.png?v=2'],
  ['https://previous-backend.example/api/media/photo.png', '/media/photo.png'],
  ['/media/photo.png', '/media/photo.png'],
  ['', ''],
  ['https://foreign.example/photo.png', 'https://foreign.example/photo.png'],
])('normalizes the API media path %s without duplicating /api', (input, expected) => {
  expect(resolveMediaRequestPath(input)).toBe(expected)
})
