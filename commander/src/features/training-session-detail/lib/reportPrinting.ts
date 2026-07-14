export const createReportPrintWindow = () => {
  const printWindow = window.open('', '_blank')
  if (!printWindow) return null
  printWindow.document.title = 'Training report'
  printWindow.document.body.style.margin = '0'
  printWindow.document.body.style.fontFamily = 'system-ui, sans-serif'
  printWindow.document.body.innerHTML =
    '<div style="padding:24px;font-size:14px;color:#404040">Preparing training report...</div>'
  return printWindow
}

export const openPdfPrintDialog = (blob: Blob, filename: string, printWindow: Window | null) => {
  // Closing the preparation window is a cancellation, including during download.
  if (printWindow?.closed) return
  const objectUrl = URL.createObjectURL(blob)
  const scheduleRevoke = () => {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
  }

  const targetWindow = printWindow ?? window.open('', '_blank')
  if (targetWindow) {
    targetWindow.document.body.innerHTML = ''
    targetWindow.document.body.style.margin = '0'
    const frame = targetWindow.document.createElement('iframe')
    frame.title = filename
    frame.src = objectUrl
    frame.style.border = '0'
    frame.style.width = '100vw'
    frame.style.height = '100vh'
    frame.onload = () => {
      window.setTimeout(() => {
        if (targetWindow.closed) return
        targetWindow.focus()
        frame.contentWindow?.focus()
        frame.contentWindow?.print()
      }, 250)
    }
    targetWindow.document.body.appendChild(frame)
    scheduleRevoke()
    return
  }

  const frame = document.createElement('iframe')
  frame.title = filename
  frame.src = objectUrl
  frame.style.position = 'fixed'
  frame.style.right = '0'
  frame.style.bottom = '0'
  frame.style.width = '0'
  frame.style.height = '0'
  frame.style.border = '0'
  frame.onload = () => {
    window.setTimeout(() => {
      frame.contentWindow?.focus()
      frame.contentWindow?.print()
    }, 250)
  }
  document.body.appendChild(frame)
  window.setTimeout(() => {
    frame.remove()
    URL.revokeObjectURL(objectUrl)
  }, 60_000)
}
