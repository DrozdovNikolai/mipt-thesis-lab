import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createReportPrintWindow,
  openPdfPrintDialog,
} from '@/features/training-session-detail/lib/reportPrinting'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
describe('PDF preparation and resource cleanup', () => {
  it('falls back after popup blocking and retains the Blob for the print grace period', () => {
    vi.useFakeTimers()
    vi.spyOn(window, 'open').mockReturnValue(null)
    const create = vi.fn(() => 'blob:synthetic-report'),
      revoke = vi.fn()
    vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
    const popup = createReportPrintWindow()
    expect(popup).toBeNull()
    openPdfPrintDialog(new Blob(['%PDF-test'], { type: 'application/pdf' }), 'report.pdf', popup)
    const iframe = document.querySelector('iframe')!
    expect(iframe.title).toBe('report.pdf')
    expect(iframe.getAttribute('src')).toBe('blob:synthetic-report')
    vi.advanceTimersByTime(59_999)
    expect(revoke).not.toHaveBeenCalled()
    expect(iframe.isConnected).toBe(true)
    vi.advanceTimersByTime(1)
    expect(revoke).toHaveBeenCalledWith('blob:synthetic-report')
    expect(iframe.isConnected).toBe(false)
  })
  it('respects a preparation window closed while the report was downloading', () => {
    const create = vi.fn()
    vi.stubGlobal('URL', { createObjectURL: create })
    openPdfPrintDialog(new Blob(['%PDF-test']), 'report.pdf', { closed: true } as Window)
    expect(create).not.toHaveBeenCalled()
    expect(document.querySelector('iframe')).toBeNull()
  })
})
