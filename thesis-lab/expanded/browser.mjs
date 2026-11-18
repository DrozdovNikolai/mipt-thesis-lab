import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, writeFile, appendFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const require=createRequire(resolve(root,'worktrees/candidate/firefly-commander/package.json'));
const { chromium }=require('@playwright/test');
const output=resolve(process.argv[2]||resolve(root,'results/expanded-browser-pilot'));
const repeats=Number(process.argv[3]||1);
const pilot=process.argv.includes('--pilot');
const stress=process.argv.includes('--stress-pilot');
const profiles=stress?[{id:'rtt250',rtt_ms:250,kib_s:64}]:pilot?[{id:'lan',rtt_ms:0,kib_s:0}]:[
  {id:'lan',rtt_ms:0,kib_s:0}, {id:'rtt80',rtt_ms:80,kib_s:512}, {id:'rtt250',rtt_ms:250,kib_s:64}
];
await mkdir(output,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function control(data) {
  const r=await fetch('http://127.0.0.1:14601/_control',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});
  assert.equal(r.status,200);return r.json();
}
async function start(profile,caseId,loginFixture) {
  const proc=spawn('/tmp/firefly-thesis-browser/chrome',[
    '--headless=new','--remote-debugging-port=14603',`--user-data-dir=${profile}`,
    '--no-first-run','--no-default-browser-check','--disable-background-networking','about:blank'
  ],{detached:true,stdio:'ignore'});
  for(let i=0;i<450;i++) {
    try {if((await fetch('http://127.0.0.1:14603/json/version')).ok)break;} catch {}
    await sleep(200);
  }
  const browser=await chromium.connectOverCDP('http://127.0.0.1:14603');
  const context=browser.contexts()[0];
  if(loginFixture) await context.addInitScript(value=>localStorage.setItem('firefly-thesis-fixture',JSON.stringify(value)),loginFixture);
  const page=await context.newPage();
  page.on('pageerror',error=>appendFile(resolve(output,'browser-errors.log'),`${caseId} ${error.stack}\n`));
  await page.goto(`http://127.0.0.1:14602/?case=${caseId}`,{timeout:120000});
  await page.waitForFunction(()=>typeof window.fireflyThesis==='function',{},{timeout:120000});
  return {proc,browser,page};
}
async function kill(instance) {
  try {process.kill(-instance.proc.pid,'SIGKILL');} catch(error) {if(error.code!=='ESRCH')throw error;}
  await instance.browser.close().catch(()=>{});
  await sleep(300);
}
async function closeCleanly(instance) {
  const session=await instance.browser.newBrowserCDPSession();
  await session.send('Browser.close').catch(()=>{});
  for(let i=0;i<100 && instance.proc.exitCode===null;i++) await sleep(100);
  assert.notEqual(instance.proc.exitCode,null,'Provisioning browser did not close');
}
async function command(page,request) {
  const result=await page.evaluate(async request=>JSON.parse(await window.fireflyThesis(JSON.stringify(request))),request);
  assert.equal(result.ok,true,JSON.stringify(result));return result.value;
}
let instance;
try {
  await writeFile(resolve(output,'config.json'),JSON.stringify({repeats,profiles,pilot,started_at:new Date().toISOString()},null,2));
  for(let rep=0;rep<repeats;rep++) for(const network of profiles) for(const fault of (stress?['lost_ack']:pilot?['offline']:['offline','lost_ack'])) {
    execFileSync('python3',['-m','expanded.telemetry',`browser-${rep}-${network.id}-${fault}`],{cwd:root,env:{...process.env,THESIS_OUTPUT:output},stdio:'inherit'});
    const id=`r${rep}-${network.id}-${fault}-${Date.now()}`;
    const profile=`/tmp/firefly-expanded-browser/${id}`;
    await mkdir(profile,{recursive:true});
    await control({offline:false,drop_next:false,gzip:true,rtt_ms:0,kib_s:0,label:`${id}-setup`,reset_events:true});
    instance=await start(profile,id);
    const initial=await command(instance.page,{op:'setup'});
    const loginFixture=await instance.page.evaluate(()=>JSON.parse(localStorage.getItem('firefly-thesis-fixture')));
    await command(instance.page,{op:'flush'});
    // Main matrix starts with an established device identity. Fresh-profile
    // immediate SIGKILL is a separately retained negative boundary pilot.
    await closeCleanly(instance); instance=undefined;
    instance=await start(profile,id,loginFixture);
    assert.equal((await command(instance.page,{op:'state'})).writer, initial.writer);
    await command(instance.page,{op:'resume'});
    await command(instance.page,{op:'flush'});
    await control({...network, id:undefined, offline:true,label:`${id}-offline`,reset_events:true});
    const text=`Наблюдение ${id}: независимое сохранение заключения инструктора; crew assignment remains traceable.`;
    const edited=await command(instance.page,{op:'edit',text,swaps:3});
    assert.equal(edited.sequence,3);assert(edited.pendingDraft||edited.runtimeOutbox>0);
    let loss=[];
    if(fault==='lost_ack') {
      await control({offline:false,drop_next:true});
      const until=Date.now()+45000;
      do {
        await command(instance.page,{op:'trySync'});
        loss=(await control({})).events.filter(e=>e.dropped==='after_backend_response');
        if(!loss.length) await sleep(250);
      } while (!loss.length && Date.now()<until);
      assert(loss.length>0,'Expected an actual lost response after backend commit');
      await control({offline:true});
    }
    await kill(instance);instance=undefined;
    const restartedAt=Date.now();instance=await start(profile,id,loginFixture);
    const restored=await command(instance.page,{op:'state'});
    await writeFile(resolve(output,`${id}-states.json`),JSON.stringify({initial,edited,restored},null,2));
    assert.equal(restored.writer,initial.writer);
    assert.equal(restored.sequence,3);
    assert.equal(restored.participants.find(x=>x.initialCrewSlot==='CM1').summary,text);
    await control({offline:false,drop_next:false,label:`${id}-recovery`});
    await command(instance.page,{op:'resume'});
    await command(instance.page,{op:'flush'});
    const recoveryMs=Date.now()-restartedAt;
    await control({drop_next:true,label:`${id}-submit`,reset_events:true});
    const finalized=await command(instance.page,{op:'finalize'});
    const traffic=(await control({})).events;
    const submits=traffic.filter(e=>e.method==='POST' && e.path.endsWith('/submit'));
    assert(submits.length>=2,'Expected submit retry');
    assert(submits.some(e=>e.dropped==='after_backend_response'),'Expected loss after submit commit');
    assert.equal(new Set(submits.map(e=>e.request_body_sha256)).size,1,'Frozen submit changed across retry');
    const fixture=await instance.page.evaluate(()=>JSON.parse(localStorage.getItem('firefly-thesis-fixture')));
    const r=await fetch(`http://127.0.0.1:14600/_expanded/h1/check/${initial.trainingId}`,{headers:{Authorization:`Bearer ${fixture.accessToken}`}});
    assert.equal(r.status,200);const db=await r.json();
    assert.equal(db.status,'COMPLETED');assert.equal(db.eventCount,4);
    assert.equal(db.assessments[0].summary,text);
    const receiptAccepted=finalized.receiptAccepted===true || (finalized.submitPending===null && finalized.sequence===null);
    assert(receiptAccepted,'Receipt was neither retained as accepted nor consumed by guarded runtime cleanup');
    const row={rep,network,fault,trainingId:initial.trainingId,correct:true,processKilled:true,
      establishedIdentity:true,writerStable:true,summaryPreserved:true,eventCount:db.eventCount,recoveryMs,
      submitAttempts:submits.length,identicalSubmit:true,receiptAccepted,
      afterCommitLosses:loss.length+submits.filter(e=>e.dropped).length};
    await appendFile(resolve(output,'browser.jsonl'),JSON.stringify(row)+'\n');
    console.log('BROWSER',rep,network.id,fault,'passed',recoveryMs);
    await instance.page.screenshot({path:resolve(output,`${id}.png`)});
    await kill(instance);instance=undefined;
  }
  await writeFile(resolve(output,'complete.json'),JSON.stringify({passed:true,time:new Date().toISOString()}));
} catch(error) {
  await writeFile(resolve(output,'failure.json'),JSON.stringify({error:error.message,stack:error.stack},null,2));
  throw error;
} finally {
  if(instance)await kill(instance);
  await control({offline:false,drop_next:false,rtt_ms:0,kib_s:0,label:'idle'}).catch(()=>{});
}
