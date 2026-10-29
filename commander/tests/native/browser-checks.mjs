/* global WebSocket, fetch, Buffer, setTimeout, clearTimeout, console */
import assert from 'node:assert/strict'
import { spawn, execFile } from 'node:child_process'
import { mkdtemp, readFile, rm, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { promisify } from 'node:util'
import process from 'node:process'
import { chromium } from '@playwright/test'

// Direct CDP avoids Playwright's unconditional focus emulation. No visibility mock.
const origin = 'http://127.0.0.1:8088'
const fixture = JSON.parse(await readFile('tests/fixtures/backend-fixture.json', 'utf8'))
const directory = 'test-results/native-tabs'
await mkdir(directory, { recursive: true })
const profile = await mkdtemp(join(tmpdir(), 'commander-native-tabs-'))
const browser = spawn(
  chromium.executablePath(),
  [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--no-first-run',
    '--no-default-browser-check',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    '--window-size=1440,1000',
    'about:blank',
  ],
  { stdio: 'ignore' },
)
let socket
const pending = new Map()
const run = promisify(execFile)
async function poll(read, accept, description, timeout = 15000) {
  const started = Date.now()
  while (Date.now() - started < timeout) {
    const value = await read()
    if (accept(value)) return value
    await delay(100)
  }
  throw new Error(`Timed out: ${description}`)
}
try {
  const port = await poll(
    () => readFile(join(profile, 'DevToolsActivePort'), 'utf8').catch(() => ''),
    Boolean,
    'Chrome CDP startup',
  )
  const version = await (await fetch(`http://127.0.0.1:${port.split('\n')[0]}/json/version`)).json()
  socket = new WebSocket(version.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    socket.onopen = resolve
    socket.onerror = reject
  })
  let sequence = 0
  const requests = new Set()
  const apiErrors = []
  const apiMutations = []
  let openDialog = null
  let closedDialog = null
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data)
    if (message.method === 'Page.javascriptDialogOpening') openDialog = message.params
    if (message.method === 'Page.javascriptDialogClosed') {
      closedDialog = message.params
      openDialog = null
    }
    if (
      message.method === 'Network.requestWillBeSent' &&
      message.params.request.url.startsWith(`${origin}/api/`)
    ) {
      requests.add(message.params.requestId)
      if (!['GET', 'HEAD', 'OPTIONS'].includes(message.params.request.method))
        apiMutations.push({
          method: message.params.request.method,
          url: message.params.request.url,
        })
    }
    if (message.method === 'Network.loadingFinished' || message.method === 'Network.loadingFailed')
      requests.delete(message.params.requestId)
    if (
      message.method === 'Network.responseReceived' &&
      message.params.response.url.startsWith(`${origin}/api/`) &&
      message.params.response.status >= 400
    )
      apiErrors.push({ url: message.params.response.url, status: message.params.response.status })
    const operation = pending.get(message.id)
    if (!operation) return
    pending.delete(message.id)
    clearTimeout(operation.timeout)
    if (message.error) operation.reject(new Error(message.error.message))
    else operation.resolve(message.result)
  }
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = ++sequence
      const timeout = setTimeout(() => {
        pending.delete(id)
        reject(new Error(`CDP timeout: ${method}`))
      }, 15000)
      pending.set(id, { resolve, reject, timeout })
      socket.send(JSON.stringify({ id, method, params, sessionId }))
    })
  const first = (await send('Target.getTargets')).targetInfos.find((item) => item.type === 'page')
  const { sessionId } = await send('Target.attachToTarget', {
    targetId: first.targetId,
    flatten: true,
  })
  await send('Page.enable', {}, sessionId)
  await send('Network.enable', {}, sessionId)
  const evaluate = async (expression) => {
    const result = await send(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      sessionId,
    )
    assert.equal(result.exceptionDetails, undefined, 'Browser evaluation must succeed')
    return result.result.value
  }
  const login = await fetch(`${origin}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: 'admin', password: 'commander-integration-only' }),
  })
  assert.equal(login.status, 200, 'Isolated fixture API must be running')
  const tokens = await login.json()
  assert.equal(typeof tokens.accessToken, 'string')
  await send(
    'Page.addScriptToEvaluateOnNewDocument',
    {
      source: `
        localStorage.setItem('session-store', ${JSON.stringify(JSON.stringify({ version: 0, state: { tokens, user: null, privileges: [] } }))});
        window.nativeVisibilityEvents = [];
        window.nativeErrors = [];
        document.addEventListener('visibilitychange', () => window.nativeVisibilityEvents.push(document.visibilityState));
        window.addEventListener('error', event => window.nativeErrors.push(event.message));
        window.addEventListener('unhandledrejection', event => window.nativeErrors.push(String(event.reason)));
      `,
    },
    sessionId,
  )
  const { targetId: otherTab } = await send('Target.createTarget', {
    url: 'about:blank',
    newWindow: false,
  })
  const { windowId } = await send('Browser.getWindowForTarget', { targetId: first.targetId })
  assert.equal(
    (await send('Browser.getWindowForTarget', { targetId: otherTab })).windowId,
    windowId,
    'Both targets must be tabs in one native window',
  )
  const metrics = `Array.from(document.querySelectorAll('canvas'), canvas => {
    const box = canvas.getBoundingClientRect();
    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 0) painted++;
    return { label: canvas.getAttribute('aria-label'), width: canvas.width, height: canvas.height,
      cssWidth: box.width, cssHeight: box.height, dpr: devicePixelRatio, painted, pixels: canvas.toDataURL() };
  })`
  async function stableCanvas(count) {
    try {
      await poll(
        () => evaluate('document.querySelectorAll("canvas").length'),
        (v) => v === count,
        'chart count',
      )
    } catch (error) {
      throw new Error(
        `${error.message}: ${await evaluate('document.body.innerText.slice(0, 2000)')}`,
      )
    }
    await evaluate('document.fonts.ready.then(() => true)')
    let previous = '',
      stable = 0
    return poll(
      () => evaluate(metrics),
      (value) => {
        const serialized = JSON.stringify(value)
        stable = serialized === previous ? stable + 1 : 0
        previous = serialized
        return stable >= 3
      },
      'stable chart pixels',
    )
  }
  function verifyCharts(items, baseline = items) {
    for (const [index, item] of items.entries()) {
      assert(item.cssWidth > 0 && item.cssHeight > 0 && item.painted > 0, 'Chart must remain drawn')
      // Line/radar are supersampled; bars use native DPR. Preserve each original density.
      const chartRatio = baseline[index].width / baseline[index].cssWidth
      assert(chartRatio >= Math.min(3, item.dpr) - 0.01, 'Original canvas must not be undersampled')
      assert(
        Math.abs(item.width - item.cssWidth * chartRatio) <= 2,
        `${item.label}: canvas width ${item.width}, CSS width ${item.cssWidth}, expected ratio ${chartRatio}`,
      )
      assert(
        Math.abs(item.height - item.cssHeight * chartRatio) <= 2,
        `${item.label}: canvas height ${item.height}, CSS height ${item.cssHeight}, expected ratio ${chartRatio}`,
      )
    }
  }
  const results = []
  for (const [name, path, count] of [
    ['analytics', '/analytics', 4],
    ['profile', `/pilots/${fixture.firstPilotId}/training-data`, 2],
  ]) {
    await send('Target.activateTarget', { targetId: first.targetId })
    await send('Browser.setWindowBounds', { windowId, bounds: { width: 1440, height: 1000 } })
    await send('Page.navigate', { url: `${origin}${path}` }, sessionId)
    const before = await stableCanvas(count)
    verifyCharts(before)
    const oldWidth = await evaluate('innerWidth')
    await send('Target.activateTarget', { targetId: otherTab })
    await poll(
      () => evaluate('document.visibilityState'),
      (value) => value === 'hidden',
      'actual hidden tab',
    )
    await send('Browser.setWindowBounds', { windowId, bounds: { width: 900, height: 800 } })
    await delay(1200)
    assert.equal(await evaluate('document.visibilityState'), 'hidden')
    await send('Target.activateTarget', { targetId: first.targetId })
    await poll(
      () => evaluate('document.visibilityState'),
      (value) => value === 'visible',
      'visible tab return',
    )
    await poll(
      () => evaluate('innerWidth'),
      (value) => value < oldWidth,
      'native window resize',
    )
    const resized = await stableCanvas(count)
    verifyCharts(resized, before)
    await send('Browser.setWindowBounds', { windowId, bounds: { width: 1440, height: 1000 } })
    await poll(
      () => evaluate('innerWidth'),
      (value) => value === oldWidth,
      'original window size',
    )
    const after = await stableCanvas(count)
    verifyCharts(after, before)
    assert.deepEqual(
      after,
      before,
      'Charts must recover the same rendered pixels at the original size',
    )
    const visibilityEvents = await evaluate('window.nativeVisibilityEvents')
    assert.deepEqual(visibilityEvents.slice(-2), ['hidden', 'visible'])
    assert.deepEqual(await evaluate('window.nativeErrors'), [])
    for (const [index, item] of after.entries()) {
      await writeFile(
        `${directory}/${name}-${index}.png`,
        Buffer.from(item.pixels.split(',')[1], 'base64'),
      )
    }
    results.push({
      name,
      path,
      hiddenForAtLeastMs: 1200,
      visibilityEvents,
      originalWidth: oldWidth,
      before: before.map((item) =>
        Object.fromEntries(Object.entries(item).filter(([key]) => key !== 'pixels')),
      ),
      resized: resized.map((item) =>
        Object.fromEntries(Object.entries(item).filter(([key]) => key !== 'pixels')),
      ),
      restoredPixelsEqual: true,
      runtimeErrors: [],
    })
    console.log(`${name}: hidden → visible, native resize and exact restored canvas pixels passed`)
  }
  await writeFile(
    `${directory}/results.json`,
    JSON.stringify(
      {
        checkedAt: new Date().toISOString(),
        browser: version.Browser,
        origin,
        method:
          'Headed Chrome over direct CDP, no Playwright focus emulation, no visibility override. Native tabs in one window; real synthetic API. Resize while hidden, return, restore size, compare stable canvas pixels.',
        results,
      },
      null,
      2,
    ) + '\n',
  )
  if (process.argv.includes('--zoom')) {
    const xdotool = process.env.COMMANDER_XDOTOOL || 'xdotool'
    const windowIds = (
      await run(xdotool, ['search', '--onlyvisible', '--pid', String(browser.pid)])
    ).stdout
      .trim()
      .split('\n')
    assert.equal(windowIds.length, 1, 'Native keys must target only the owned browser window')
    const ownWindow = windowIds[0]
    const originalSize = await evaluate('({width:innerWidth,dpr:devicePixelRatio})')
    await run(xdotool, ['windowfocus', '--sync', ownWindow])
    await delay(200)
    for (let step = 0; step < 5; step++) {
      await run(xdotool, ['key', '--window', ownWindow, '--clearmodifiers', 'ctrl+plus'])
      await delay(200)
      console.log(
        'Native zoom step',
        step + 1,
        await evaluate('({width:innerWidth,dpr:devicePixelRatio,focus:document.hasFocus()})'),
      )
    }
    await poll(
      () => evaluate('devicePixelRatio'),
      (value) => value === originalSize.dpr * 2,
      'actual browser zoom 200%',
    )
    assert.equal(
      await evaluate('visualViewport.scale'),
      1,
      'This must be browser zoom, not pinch emulation',
    )
    await mkdir('test-results/native-zoom', { recursive: true })
    const zoomResults = []
    for (const [name, path] of [
      ['pilots', '/pilots'],
      ['profile', `/pilots/${fixture.firstPilotId}/profile`],
      ['training-data', `/pilots/${fixture.firstPilotId}/training-data`],
      ['training-sessions', '/training-sessions'],
      ['detail', `/training-sessions/${fixture.training_id}`],
      ['analytics', '/analytics'],
      ['settings', '/settings'],
      ['compatibility', '/compatibility'],
    ]) {
      await send('Page.navigate', { url: `${origin}${path}` }, sessionId)
      await poll(
        () =>
          evaluate(
            `location.pathname === ${JSON.stringify(path)} && Boolean(document.querySelector('main h1'))`,
          ),
        Boolean,
        `${name} main heading`,
      )
      let idle = 0
      await poll(
        () => requests.size,
        (value) => {
          idle = value === 0 ? idle + 1 : 0
          return idle >= 4
        },
        `${name} API idle`,
      )
      assert.deepEqual(apiErrors, [], 'Zoom pages must load real API data successfully')
      await evaluate('document.fonts.ready.then(() => true)')
      const controls = await evaluate(`(async () => {
        const failures = [], checked = [];
        const controls = Array.from(document.querySelectorAll('main button, main input, main select, main a[href]'));
        for (const node of controls) {
          if (node.disabled || !node.getClientRects().length || getComputedStyle(node).visibility === 'hidden') continue;
          node.scrollIntoView({block:'center', inline:'center'});
          node.focus({preventScroll:true});
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const box = node.getBoundingClientRect();
          const hit = document.elementFromPoint(box.left + box.width/2, box.top + box.height/2);
          const label = node.getAttribute('aria-label') || node.textContent.trim().slice(0,80) || node.name || node.type;
          checked.push(label);
          if (!(node === hit || node.contains(hit))) failures.push(label);
        }
        document.activeElement?.blur();
        for (const node of document.querySelectorAll('main, main *')) { if(node.scrollLeft)node.scrollLeft=0; if(node.scrollTop)node.scrollTop=0; }
        return {checked, failures, width:innerWidth, dpr:devicePixelRatio, scale:visualViewport.scale,
          documentOverflow:document.documentElement.scrollWidth > innerWidth + 1};
      })()`)
      assert.equal(controls.dpr, originalSize.dpr * 2)
      assert(Math.abs(controls.width * 2 - originalSize.width) <= 2)
      assert.equal(controls.scale, 1)
      assert.equal(controls.documentOverflow, false, `${name}: no document horizontal overflow`)
      assert(controls.checked.length > 0, `${name}: expected interactive controls`)
      assert.deepEqual(
        controls.failures,
        [],
        `${name}: controls must remain reachable and unobscured`,
      )
      assert.deepEqual(await evaluate('window.nativeErrors'), [])
      const screenshot = await send('Page.captureScreenshot', { format: 'png' }, sessionId)
      await writeFile(
        `test-results/native-zoom/${name}-controls.png`,
        Buffer.from(screenshot.data, 'base64'),
      )
      await evaluate(
        'scrollTo(0,0); new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))',
      )
      const topScreenshot = await send('Page.captureScreenshot', { format: 'png' }, sessionId)
      await writeFile(
        `test-results/native-zoom/${name}.png`,
        Buffer.from(topScreenshot.data, 'base64'),
      )
      zoomResults.push({ name, path, ...controls })
      console.log(
        `${name}: native 200% zoom, ${controls.checked.length} reachable controls, no overflow`,
      )
    }
    await writeFile(
      'test-results/native-zoom/results.json',
      JSON.stringify(
        {
          checkedAt: new Date().toISOString(),
          browser: version.Browser,
          origin,
          originalSize,
          method:
            'Headed Chrome; xdotool sends five Ctrl+Plus shortcuts exclusively to the owned browser PID/window. No emulated viewport, page scale, or CSS zoom. DPR 1 → 2, width 1440 → 720, visualViewport.scale remains 1. Each enabled visible main control is focused and scrolled into view; its center must pass browser hit testing. Real synthetic API.',
          results: zoomResults,
        },
        null,
        2,
      ) + '\n',
    )
  }
  if (process.argv.includes('--confirm')) {
    const name = `Native keyboard ${Date.now()}`
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${tokens.accessToken}`,
    }
    const response = await fetch(`${origin}/api/commander/flight-types`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ name }),
    })
    assert.equal(response.status, 201)
    const created = await response.json()
    assert(Number.isInteger(created.id))
    try {
      await send('Page.navigate', { url: `${origin}/settings` }, sessionId)
      await poll(
        () =>
          evaluate(
            `Array.from(document.querySelectorAll('button h4')).some(node => node.textContent === ${JSON.stringify(name)})`,
          ),
        Boolean,
        'disposable training type',
      )
      await evaluate(
        `Array.from(document.querySelectorAll('button h4')).find(node => node.textContent === ${JSON.stringify(name)}).closest('button').click()`,
      )
      await poll(
        () =>
          evaluate(
            `Array.from(document.querySelectorAll('input')).some(node => node.value === ${JSON.stringify(name)})`,
          ),
        Boolean,
        'selected disposable type',
      )
      const point = await evaluate(`(() => {
        const button = Array.from(document.querySelectorAll('main button')).find(node => node.textContent.trim() === 'Delete');
        button.scrollIntoView({block:'center'});
        const box = button.getBoundingClientRect();
        return {x:box.x+box.width/2,y:box.y+box.height/2};
      })()`)
      await send(
        'Input.dispatchMouseEvent',
        { type: 'mousePressed', ...point, button: 'left', clickCount: 1 },
        sessionId,
      )
      const mutationsBeforeCancel = apiMutations.length
      const clicked = send(
        'Input.dispatchMouseEvent',
        { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 },
        sessionId,
      )
      const dialog = await poll(() => openDialog, Boolean, 'native confirm opens')
      assert.equal(dialog.type, 'confirm')
      assert.equal(dialog.hasBrowserHandler, true)
      assert.equal(dialog.message, `Delete training type "${name}"? This cannot be undone.`)
      const xdotool = process.env.COMMANDER_XDOTOOL || 'xdotool'
      const ownWindows = (
        await run(xdotool, ['search', '--onlyvisible', '--pid', String(browser.pid)])
      ).stdout
        .trim()
        .split('\n')
      assert.equal(ownWindows.length, 1)
      await run(xdotool, ['windowfocus', '--sync', ownWindows[0]])
      await delay(200)
      await run(xdotool, ['key', '--window', ownWindows[0], '--clearmodifiers', 'Escape'])
      await poll(() => closedDialog, Boolean, 'Escape closes native confirm')
      await clicked
      assert.equal(closedDialog.result, false)
      const focused = await evaluate(
        `({tag:document.activeElement.tagName,text:document.activeElement.textContent.trim()})`,
      )
      assert.deepEqual(focused, { tag: 'BUTTON', text: 'Delete' })
      assert.deepEqual(
        apiMutations.slice(mutationsBeforeCancel),
        [],
        'Cancel must not send a mutation',
      )
      const remaining = await (
        await fetch(`${origin}/api/commander/flight-types`, { headers })
      ).json()
      assert(
        remaining.some((item) => item.id === created.id),
        'Escape must not delete the training type',
      )
      await mkdir('test-results/native-confirm', { recursive: true })
      await writeFile(
        'test-results/native-confirm/results.json',
        JSON.stringify(
          {
            checkedAt: new Date().toISOString(),
            browser: version.Browser,
            origin,
            method:
              'Headed Chrome; trusted CDP mouse click opens actual window.confirm. xdotool Escape targets only the owned browser window. No Page.handleJavaScriptDialog or window.confirm stub. Isolated disposable flight type is removed in finally.',
            dialog: {
              type: dialog.type,
              message: dialog.message,
              hasBrowserHandler: dialog.hasBrowserHandler,
            },
            escapeResult: closedDialog.result,
            focusedAfterCancel: focused,
            recordPreservedAfterCancel: true,
            mutationsAfterCancel: apiMutations.slice(mutationsBeforeCancel),
          },
          null,
          2,
        ) + '\n',
      )
      console.log(
        'native confirm: correct message, Escape cancels, focus returns to Delete, record preserved',
      )
    } finally {
      const cleanup = await fetch(`${origin}/api/commander/flight-types/${created.id}`, {
        method: 'DELETE',
        headers,
      })
      assert.equal(cleanup.status, 204, 'Disposable type cleanup')
    }
  }
  await send('Browser.close')
} finally {
  socket?.close()
  for (const operation of pending.values()) clearTimeout(operation.timeout)
  if (browser.exitCode === null) {
    browser.kill('SIGTERM')
    await Promise.race([new Promise((resolve) => browser.once('exit', resolve)), delay(3000)])
  }
  await rm(profile, { recursive: true, force: true })
}
