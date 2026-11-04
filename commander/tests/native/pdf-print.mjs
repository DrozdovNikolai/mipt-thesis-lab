/* global WebSocket, fetch, Buffer, setTimeout, clearTimeout, console */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, readFile, rm, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from '@playwright/test'

// Direct CDP avoids Playwright's unconditional focus emulation. No visibility mock.
const origin = 'http://127.0.0.1:8088'
const fixture = JSON.parse(await readFile('tests/fixtures/backend-fixture.json', 'utf8'))
const directory = 'test-results/native-print'
await mkdir(directory, { recursive: true })
const profile = await mkdtemp(join(tmpdir(), 'commander-native-print-'))
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
  const reports = []
  const apiMutations = []
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data)
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
    if (
      message.method === 'Network.responseReceived' &&
      message.params.response.url.endsWith('/report.pdf')
    )
      reports.push({
        url: message.params.response.url,
        status: message.params.response.status,
        mimeType: message.params.response.mimeType,
      })
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
        window.nativeBlobEvents = [];
        const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
        URL.createObjectURL = blob => {const url = create(blob); window.nativeBlobEvents.push({type:'create',url,at:performance.now()}); return url;};
        URL.revokeObjectURL = url => {window.nativeBlobEvents.push({type:'revoke',url,at:performance.now()}); revoke(url);};
        document.addEventListener('visibilitychange', () => window.nativeVisibilityEvents.push(document.visibilityState));
        window.addEventListener('error', event => window.nativeErrors.push(event.message));
        window.addEventListener('unhandledrejection', event => window.nativeErrors.push(String(event.reason)));
      `,
    },
    sessionId,
  )

  async function evaluateIn(targetSession, expression) {
    const value = await send(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      targetSession,
    )
    assert.equal(value.exceptionDetails, undefined)
    return value.result.value
  }
  const printState = `(() => {
    let state, summary='', saveEnabled=false, cancelPoint=null;
    function visit(root){ for(const node of root.querySelectorAll('*')){
      if(node.tagName==='PRINT-PREVIEW-PREVIEW-AREA')state=node.previewState;
      if(node.tagName==='PRINT-PREVIEW-HEADER')summary=node.shadowRoot?.textContent.trim() || '';
      if(node.tagName==='CR-BUTTON' && ['Save','Print'].includes(node.textContent.trim()) && !node.disabled)saveEnabled=true;
      if(node.tagName==='CR-BUTTON' && node.textContent.trim()==='Cancel') {const box=node.getBoundingClientRect();cancelPoint={x:box.x+box.width/2,y:box.y+box.height/2};}
      if(node.shadowRoot)visit(node.shadowRoot);
    }}
    visit(document);return {state,saveEnabled,cancelPoint,summary:summary.slice(-1000)};
  })()`
  const results = []
  for (const mode of ['blocked-popup', 'allowed-popup']) {
    await send(
      'Page.navigate',
      { url: `${origin}/training-sessions/${fixture.training_id}` },
      sessionId,
    )
    await poll(
      () =>
        evaluate(
          "Array.from(document.querySelectorAll('button')).some(node=>node.textContent.trim()==='Export PDF'&&!node.disabled)",
        ),
      Boolean,
      'Export PDF ready',
    )
    const beforeTargets = new Set(
      (await send('Target.getTargets')).targetInfos.map((item) => item.targetId),
    )
    const beforeReports = reports.length
    if (mode === 'blocked-popup') {
      // A script click has no user activation; Chrome's real default blocker rejects window.open.
      // Neither window.open nor window.print is replaced.
      await evaluate(
        "Array.from(document.querySelectorAll('button')).find(node=>node.textContent.trim()==='Export PDF').click()",
      )
    } else {
      const point = await evaluate(
        "(() => {const node=Array.from(document.querySelectorAll('button')).find(node=>node.textContent.trim()==='Export PDF');node.scrollIntoView({block:'center'});const box=node.getBoundingClientRect();return {x:box.x+box.width/2,y:box.y+box.height/2};})()",
      )
      await send(
        'Input.dispatchMouseEvent',
        { type: 'mousePressed', ...point, button: 'left', clickCount: 1 },
        sessionId,
      )
      await send(
        'Input.dispatchMouseEvent',
        { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 },
        sessionId,
      )
    }
    const printTarget = await poll(
      async () =>
        (await send('Target.getTargets')).targetInfos.find(
          (item) => item.url === 'chrome://print/',
        ),
      Boolean,
      'actual print preview opens',
    )
    const { sessionId: printSession } = await send('Target.attachToTarget', {
      targetId: printTarget.targetId,
      flatten: true,
    })
    const ready = await poll(
      () => evaluateIn(printSession, printState),
      (value) => value.state === 'display-preview' && value.saveEnabled,
      'rendered PDF in actual print preview',
      45000,
    )
    const screenshot = await send('Page.captureScreenshot', { format: 'png' }, printSession)
    await writeFile(`${directory}/${mode}.png`, Buffer.from(screenshot.data, 'base64'))
    assert(ready.cancelPoint)
    await send(
      'Input.dispatchMouseEvent',
      { type: 'mousePressed', ...ready.cancelPoint, button: 'left', clickCount: 1 },
      printSession,
    )
    await send(
      'Input.dispatchMouseEvent',
      { type: 'mouseReleased', ...ready.cancelPoint, button: 'left', clickCount: 1 },
      printSession,
    ).catch((error) => {
      if (!/session|target|closed/i.test(error.message)) throw error
    })
    await poll(
      async () =>
        (await send('Target.getTargets')).targetInfos.some(
          (item) => item.targetId === printTarget.targetId,
        ),
      (value) => !value,
      'Cancel closes print preview',
    )
    const newPages = (await send('Target.getTargets')).targetInfos.filter(
      (item) => item.type === 'page' && !beforeTargets.has(item.targetId),
    )
    let pdfSession = sessionId,
      popupTarget = null
    if (mode === 'blocked-popup')
      assert.equal(newPages.length, 0, 'No popup page may exist when Chrome blocks it')
    else {
      assert.equal(newPages.length, 1, 'Trusted click must open one report popup')
      popupTarget = newPages[0].targetId
      pdfSession = (await send('Target.attachToTarget', { targetId: popupTarget, flatten: true }))
        .sessionId
    }
    const frame = await evaluateIn(
      pdfSession,
      '(() => {const frame=document.querySelector(\'iframe[src^="blob:"]\');return frame&&{url:frame.src,title:frame.title,width:frame.style.width};})()',
    )
    assert(frame)
    assert.equal(frame.title, `training-report-${fixture.training_id}-cm1.pdf`)
    assert.equal(frame.width, mode === 'blocked-popup' ? '0px' : '100vw')
    const pdf = await evaluate(
      `fetch(${JSON.stringify(frame.url)}).then(async response=>{const blob=await response.blob();return {size:blob.size,type:blob.type,magic:await blob.slice(0,5).text()}})`,
    )
    assert.equal(pdf.magic, '%PDF-')
    assert(pdf.size > 1000)
    assert.equal(reports.length, beforeReports + 1)
    assert.equal(reports.at(-1).status, 200)
    assert.equal(reports.at(-1).mimeType, 'application/pdf')
    assert.equal(
      await evaluate(
        "Array.from(document.querySelectorAll('button')).find(node=>node.textContent.trim()==='Export PDF').disabled",
      ),
      false,
    )
    if (popupTarget) await send('Target.closeTarget', { targetId: popupTarget })
    console.log(
      `${mode}: actual PDF preview rendered; Cancel closed it; waiting for real cleanup timer`,
    )
    const revoked = await poll(
      () =>
        evaluate(
          `window.nativeBlobEvents.find(item=>item.type==='revoke'&&item.url===${JSON.stringify(frame.url)})`,
        ),
      Boolean,
      'real Blob URL revocation',
      70000,
    )
    const created = await evaluate(
      `window.nativeBlobEvents.find(item=>item.type==='create'&&item.url===${JSON.stringify(frame.url)})`,
    )
    assert(revoked.at - created.at >= 59900, 'Grace period must not end early')
    assert.equal(
      await evaluate(`fetch(${JSON.stringify(frame.url)}).then(()=>true,()=>false)`),
      false,
    )
    assert.equal(await evaluate('document.querySelectorAll("iframe[src^=blob]").length'), 0)
    assert.deepEqual(await evaluate('window.nativeErrors'), [])
    results.push({
      mode,
      previewState: ready.state,
      saveEnabled: ready.saveEnabled,
      summary: ready.summary,
      report: reports.at(-1),
      pdf,
      iframeTitle: frame.title,
      iframeWidth: frame.width,
      popupCount: newPages.length,
      cancelClosesPreview: true,
      exportEnabledAfterPrint: true,
      cleanupDelayMs: Math.round(revoked.at - created.at),
      revokedUrlFailsFetch: true,
      remainingMainIframes: 0,
      runtimeErrors: [],
    })
    console.log(`${mode}: Blob revoked and iframe/window removed`)
  }
  assert.deepEqual(apiErrors, [])
  await writeFile(
    `${directory}/results.json`,
    JSON.stringify(
      {
        checkedAt: new Date().toISOString(),
        browser: version.Browser,
        origin,
        method:
          'Headed Chrome direct CDP, native popup blocking (script click without user activation) and permitted popup (trusted mouse click). Actual chrome://print/ must render PDF and enable Save. Cancel is clicked in the real UI. Real 60-second cleanup timer; URL methods only observed, original implementations called. No window.open/print stubs, Page.printToPDF, or fake timers. Virtual/physical printer job is not submitted.',
        results,
      },
      null,
      2,
    ) + '\n',
  )
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
