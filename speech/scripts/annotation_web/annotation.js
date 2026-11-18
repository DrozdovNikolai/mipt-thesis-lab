"use strict";
let packet,selected,revision,sourceStart=0;const $=id=>document.getElementById(id);
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":packet.csrf},body:JSON.stringify(body)});if(response.status===401){location.href="/";throw Error("Сессия истекла")}const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));return data}
function jsonField(id){const value=$(id).value.trim();return value?JSON.parse(value):null}
function fillJson(id,value){$(id).value=value===null||value===undefined?"":JSON.stringify(value,null,2)}
async function select(id){try{const data=await api("/api/item/"+id);selected=id;revision=data.revision;const s=data.sample;$("draft-button").hidden=!(data.machine_draft_available??(s.annotation_provenance.draft_available!==false));$("draft-button").disabled=false;$("draft-button").textContent=data.machine_draft_prefill?"Подставить машинный черновик":"Показать машинный черновик";$("script-button").hidden=s.annotation_provenance.draft_available===false;sourceStart=s.annotation_provenance.original_start_sec;$("editor").hidden=false;$("empty").hidden=true;$("title").textContent=s.annotation_provenance.source_sample_id;$("origin").textContent=`${s.split} · исходная запись ${sourceStart}–${s.annotation_provenance.original_end_sec} с · ревизия ${revision}`;$("audio").src="/api/audio/"+id;$("scope").value=s.scope;$("language").value=s.language;$("transcript").value=s.reference_text??"";$("salient").value=s.salient_for_review===null?"":String(s.salient_for_review);fillJson("entities",s.critical_entities);fillJson("temporal",s.events);fillJson("unintelligible",s.unintelligible);for(const input of $("labels").querySelectorAll("input"))input.checked=(s.labels??[]).includes(input.value);for(const name of ["scope","transcript","entities","events","temporal"])$("verify_"+name).checked=false;$("listened").checked=false;$("draft").hidden=true;$("draft").textContent="";$("script-hint").hidden=true;$("script-hint").textContent="";$("status").textContent="";if(data.publisher_proposal_available){const proposal=await api("/api/publisher-proposal/"+id,{});$("script-hint").hidden=false;$("script-hint").textContent="ИЗДАТЕЛЬСКИЙ ТЕКСТ, АВТОМАТИЧЕСКАЯ ПРИВЯЗКА — НЕ ЧЕЛОВЕЧЕСКИЙ ЭТАЛОН\nИсточник: "+proposal.source_file+"\n\n"+(proposal.text||"Надёжный отрывок не найден")+"\n\n"+(proposal.reasons.length?"Нужна проверка: "+proposal.reasons.join(", "):"Проверки автоматической привязки пройдены; текст и таймкоды ещё не сверены человеком.");if(s.reference_text===null&&proposal.eligible_for_exploratory_training){$("transcript").value=proposal.text;$("status").textContent="Подставлен готовый издательский текст. Подтверждения разметки остаются снятыми."}}document.querySelectorAll(".queue-item").forEach(b=>b.classList.toggle("active",b.dataset.id===id))}catch(e){$("status").textContent=e.message}}

const initialSplit = new URLSearchParams(location.search).get("split");
$("queue-split").value = ["train", "dev"].includes(initialSplit) ? initialSplit : "all";
function visibleItems() {
  const split = $("queue-split").value;
  const items = packet.items.filter(item => split === "all" || item.split === split);
  if (packet.prefer_english_drafts) items.sort((a, b) => Number(b.draft_language === "en") - Number(a.draft_language === "en"));
  return items;
}
function renderQueue() {
  const items = visibleItems();
  const verified = items.filter(item => item.transcript_status === "human_verified").length;
  $("queue-progress").textContent = `Расшифровки подтверждены: ${verified} из ${items.length}`;
  if (packet.prefer_english_drafts) $("queue-progress").textContent += ". Английские по оценке модели — первыми. Модель может ошибаться в языке.";
  $("queue").replaceChildren();for(const item of items){const b=document.createElement("button");b.type="button";b.className="queue-item";b.dataset.id=item.id;b.textContent=item.source;const small=document.createElement("small");small.textContent=`${item.split} · ${item.start_sec} с · ${item.transcript_status} · r${item.revision}`+(item.draft_language?` · язык по модели: ${item.draft_language}`:"");b.append(small);b.onclick=()=>select(item.id);$("queue").append(b)}
  document.querySelectorAll(".queue-item").forEach(b => b.classList.toggle("active", b.dataset.id === selected));
}
$("queue-split").onchange = () => {
  const url = new URL(location.href);
  url.searchParams.set("split", $("queue-split").value);
  history.replaceState(null, "", url);
  renderQueue();
};

async function load(){packet=await api("/api/packet");$("actor").textContent=packet.actor;renderQueue();$("labels").replaceChildren();for(const label of packet.labels){const element=document.createElement("label");element.className="check";const input=document.createElement("input");input.type="checkbox";input.value=label;element.append(input,document.createTextNode(label));$("labels").append(element)}}
$("audio").ontimeupdate=()=>{$("clock").textContent=`Фрагмент: ${$("audio").currentTime.toFixed(1)} с · оригинал: ${(sourceStart+$("audio").currentTime).toFixed(1)} с`};
$("draft-button").onclick = async () => {
  const id = selected;
  const previousText = $("transcript").value;
  $("draft-button").disabled = true;
  try {
    const data = await api("/api/draft/" + id, {});
    if (selected !== id) return;
    $("draft").hidden = false;
    $("draft").textContent = "МАШИННЫЙ ЧЕРНОВИК — сверьте каждое слово с аудио\n\n" + data.text;
    if (data.can_prefill && !previousText.trim() && !$("transcript").value.trim()) {
      $("transcript").value = data.text;
      $("verify_transcript").checked = false;
      $("status").textContent = "Черновик подставлен. Исправьте его по аудио и затем подтвердите проверку.";
    } else {
      $("status").textContent = "Черновик показан ниже. Поле расшифровки не изменено.";
    }
  } catch (error) {
    if (selected === id) $("status").textContent = error.message;
  } finally {
    if (selected === id) $("draft-button").disabled = false;
  }
};
$("editor").onsubmit=async e=>{e.preventDefault();try{const data={revision,scope:$("scope").value,language:$("language").value,transcript:$("transcript").value,entities:jsonField("entities"),temporal:jsonField("temporal"),unintelligible:jsonField("unintelligible")??[],labels:[...$("labels").querySelectorAll("input:checked")].map(i=>i.value),salient:$("salient").value===""?null:$("salient").value==="true",listened:$("listened").checked};for(const name of ["scope","transcript","entities","events","temporal"])data["verify_"+name]=$("verify_"+name).checked;if(!data.labels.length&&!data.verify_events)data.labels=null;if(!data.transcript.trim()&&!data.verify_transcript)data.transcript=null;const result=await api("/api/review/"+selected,data);revision=result.revision;$("status").textContent="Сохранена ревизия "+revision;const keep=selected;await load();await select(keep);$("status").textContent="Сохранена ревизия "+revision}catch(error){$("status").textContent=error.message}};
load().then(async () => {
  if (["train", "dev"].includes(initialSplit)) {
    const items = visibleItems();
    const first = items.find(item => item.transcript_status !== "human_verified") ?? items[0];
    if (first) await select(first.id);
  }
}).catch(error=>{$("empty").textContent=error.message});

$("script-button").onclick=async()=>{try{const data=await api("/api/script-hint/"+selected,{});$("script-hint").hidden=false;$("script-hint").textContent="КОНТЕКСТ СЦЕНАРИЯ — НЕ ЭТАЛОН РАСШИФРОВКИ.\nАлгоритм мог выбрать неверное место. Сверяйте каждое слово с аудио; не исправляйте числа по сценарию.\n\n"+data.candidates.map(c=>c.source_file+"\n"+c.context.map(b=>(b.page?"Страница "+b.page:"Абзац "+b.paragraph)+"\n"+b.text).join("\n")).join("\n\n")}catch(e){$("status").textContent=e.message}};
