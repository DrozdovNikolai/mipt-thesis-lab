"use strict";
let csrf = "", currentId = null, current = null;
const $ = id => document.getElementById(id);
const message = text => { $("message").textContent = text; };
async function api(path, options = {}) {
  options.headers = {...options.headers, "X-CSRF-Token": csrf};
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}
function element(tag, text, parent) { const e = document.createElement(tag); e.textContent = text; if(parent) parent.append(e); return e; }
function button(text, action, parent) { const b = element("button", text, parent); b.onclick = () => Promise.resolve(action()).catch(e => message(e.message)); return b; }
async function jobs() {
  const rows = await api("/v1/jobs"); $("jobs").replaceChildren();
  for (const j of rows) {
    const row = element("article", `${j.status} · ${j.stage} · ${Math.round(j.progress * 100)}% · ${j.job_id}`, $("jobs"));
    if (j.error) element("pre", JSON.stringify(j.error), row);
    if (j.status === "SUCCEEDED") button("Открыть", () => show(j.session_id), row);
    if (["RUNNING", "QUEUED"].includes(j.status)) button("Отменить", async () => {await api(`/v1/jobs/${j.job_id}/cancel`, {method:"POST"}); await jobs();}, row);
    if (j.status === "FAILED") button("Повторить", async () => {await api(`/v1/jobs/${j.job_id}/retry`, {method:"POST"}); await jobs();}, row);
  }
}
async function review(patch) {
  const author = prompt("Автор проверки"), reason = prompt("Причина / что проверено при прослушивании");
  if (!author || !reason) return;
  await api(`/v1/sessions/${currentId}/reviews`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...patch, expected_revision:current.revision, author, reason})});
  await show(currentId);
}
async function show(id) {
  currentId = id; current = await api(`/v1/sessions/${id}/result`); $("result").hidden = false;
  $("scope").textContent = `${current.deployment_candidate}; quality gate ${current.quality_gate_status}. Подтверждённая область: ${(current.validated_scope || []).join(", ") || "нет"}. Сигналы риска не являются вероятностью правильности.`;
  const audioUrl = `/v1/sessions/${id}/audio`; if (!$("audio").src.endsWith(audioUrl)) $("audio").src = audioUrl;
  $("exports").replaceChildren(); for (const format of ["json","csv","vtt","srt"]) {const a = element("a", format.toUpperCase(), $("exports")); a.href = `/v1/sessions/${id}/export?format=${format}`;}
  $("segments").replaceChildren();
  for (const s of current.segments) {
    const row = element("article", "", $("segments"));
    button(`${s.start_sec.toFixed(2)}–${s.end_sec.toFixed(2)} · Слушать`, () => {$("audio").currentTime=s.start_sec; return $("audio").play();}, row);
    element("p", `Говорящий: ${s.speaker_id || "неизвестен"}; роль: ${s.role}`, row);
    element("pre", `ASR: ${s.raw_asr_text}\nОтображение: ${s.display_text}\nПроверено: ${s.reviewed_text ?? "—"}`, row);
    element("p", `Риск: ${s.risk_reasons.join(", ")}`, row).className = "risk";
    const editor = document.createElement("textarea"); editor.value = s.reviewed_text ?? s.display_text; row.append(editor);
    button("Сохранить человеческую правку", () => review({segment_id:s.segment_id, reviewed_text:editor.value}), row);
    const role = document.createElement("select"); for(const name of ["unknown","captain","first_officer","instructor"]) {const o=element("option",name,role);o.value=name;} role.value=s.role;row.append(role);
    button("Назначить роль явно",()=>review({segment_id:s.segment_id,role:role.value}),row);
  }
  $("events").replaceChildren();
  for(const e of current.events) {
    if ($("review-only").checked && e.review_status !== "draft") continue;
    const row=element("article",`${e.start_sec.toFixed(2)}–${e.end_sec.toFixed(2)} · ${e.labels.join(", ")} · ${e.review_status}`, $("events"));
    element("blockquote",e.evidence_quote,row); if(e.reviewed_evidence_quote !== null && e.reviewed_evidence_quote !== undefined) element("p",`Проверенная цитата: ${e.reviewed_evidence_quote}`,row); element("pre",JSON.stringify(e.entities,null,2),row);
    const labels=document.createElement("input"); labels.value=e.labels.join(", ");row.append(labels);
    button("Изменить категории",()=>review({event_id:e.event_id,labels:labels.value.split(",").map(x=>x.trim())}),row);
    button("Значим для разбора",()=>review({event_id:e.event_id,salient_for_review:true}),row);
    button("Не значим",()=>review({event_id:e.event_id,salient_for_review:false}),row);
    button("Подтвердить",()=>review({event_id:e.event_id,review_status:"confirmed"}),row);
    button("Отклонить",()=>review({event_id:e.event_id,review_status:"rejected"}),row);
  }
}
$("upload").onsubmit = async event => {event.preventDefault();try {
  const data=new FormData(event.target), body=new FormData();body.append("audio",data.get("audio"));
  body.append("metadata",JSON.stringify({language:data.get("language"),channel_mode:data.get("channel_mode"),channel_mapping:JSON.parse(data.get("channel_mapping")||"{}"),diarization:data.get("diarization"),rights_confirmed:data.has("rights"),provenance:data.get("provenance")}));
  const result=await api("/v1/sessions",{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body});message(`Создано задание ${result.job_id}`);await jobs();
} catch(e){message(e.message);}};
$("review-only").onchange=()=>currentId&&show(currentId).catch(e=>message(e.message));
$("delete").onclick=async()=>{if(currentId&&confirm("Удалить исходную запись, результаты и правки?")){await api(`/v1/sessions/${currentId}`,{method:"DELETE"});$("result").hidden=true;currentId=null;await jobs();}};
$("logout").onclick=async()=>{await api("/logout",{method:"POST"});location.reload();};
(async()=>{csrf=(await api("/v1/csrf")).csrf;await jobs();setInterval(()=>jobs().catch(e=>message(e.message)),4000);})().catch(e=>message(e.message));
