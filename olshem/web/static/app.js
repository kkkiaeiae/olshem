/* Өлшем — web client (vanilla JS, no build step). All UI text is Kazakh. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = () => $("#view");
let timers = [];
const every = (ms, fn) => { const t = setInterval(fn, ms); timers.push(t); return t; };
const clearTimers = () => { timers.forEach(clearInterval); timers = []; };

const store = {
  get role() { try { return localStorage.getItem("olshem-role") || ""; } catch { return ""; } },
  set role(v) { try { localStorage.setItem("olshem-role", v); } catch {} },
};

async function api(path, { method = "GET", json, form } = {}) {
  const headers = { "X-Role": store.role || "student" };
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let r;
  try { r = await fetch(path, { method, headers, body }); }
  catch { throw new Error("Серверге қосылу мүмкін болмады. Интернетті тексеріңіз."); }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Қате (${r.status})`);
  return data;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (err ? " err" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), err ? 6000 : 3000);
}

const TYPES = { "курстық": "Курстық жұмыс", "БӨЖ": "БӨЖ", "реферат": "Реферат", "эссе": "Эссе", "зертханалық": "Зертханалық жұмыс" };
const METRICS = {
  none: "ЖИ тексереді (мазмұн)",
  margin_left_cm: "Сол жақ өріс, см", margin_right_cm: "Оң жақ өріс, см", margin_top_cm: "Жоғарғы өріс, см", margin_bottom_cm: "Төменгі өріс, см",
  font_name: "Қаріп түрі", font_size_pt: "Қаріп өлшемі, pt", line_spacing: "Жоларалық интервал", first_line_indent_cm: "Абзац шегінісі, см",
  page_count: "Бет саны", page_number_position: "Бет нөмірінің орны", required_sections: "Міндетті бөлімдер",
  table_caption: "Кесте атауының үлгісі", references_min: "Дереккөздердің ең аз саны", references_order: "Әдебиеттер тізімінің реті",
};
const NUMERIC = ["margin_left_cm", "margin_right_cm", "margin_top_cm", "margin_bottom_cm", "font_size_pt", "line_spacing", "first_line_indent_cm", "page_count", "references_min"];
const SEVERITY = ["критикалық", "маңызды", "ұсыныс"];
const CATEGORY = ["рәсімдеу", "құрылым", "мазмұн", "әдебиет", "көлем"];
const fmtDate = (d) => d ? new Date(d).toLocaleDateString("kk-KZ", { day: "numeric", month: "long", year: "numeric" }) : "";
const fmtTime = (d) => d ? new Date(d).toLocaleString("kk-KZ", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";

function checklistChip(a) {
  if (a.checklist_status === "extracting") return `<span class="chip na"><span class="spinner" style="width:11px;height:11px;margin-right:4px"></span>ЖИ талаптарды оқып жатыр</span>`;
  if (a.checklist_status === "error") return `<span class="chip bad">Талаптарды өңдеу қатесі</span>`;
  return a.checklist_confirmed ? `<span class="chip ok">Тізім расталды</span>` : `<span class="chip warn">Растауды күтуде</span>`;
}
function statusChip(s) {
  const m = { queued: ["na", "Кезекте"], format: ["na", "Рәсімдеу тексерілуде"], ocr: ["na", "Қолжазба оқылуда"], review: ["na", "ЖИ мазмұнды оқуда"], done: ["ok", "Дайын"], error: ["bad", "Қате"] };
  const [c, l] = m[s.status] || ["na", s.status];
  return `<span class="chip ${c}">${l}</span>`;
}
const typeSuffix = (a, size) => {
  const t = TYPES[a.type] || a.type;
  return t.toLowerCase() === a.title.trim().toLowerCase() ? "" : ` <span class="mute" style="font-weight:400${size ? ";font-size:" + size + "px" : ""}">· ${esc(t)}</span>`;
};
const pct = (v) => (v === null || v === undefined) ? "—" : `${Math.round(v)}%`;
const scoreTxt = (v) => (v === null || v === undefined) ? "—" : `${v}`;

// ------------------------------------------------------------------ chrome
async function refreshChrome() {
  const rb = $("#roleBadge");
  if (store.role) {
    rb.hidden = false;
    rb.outerHTML = `<button id="roleBadge" class="badge" type="button" title="Рөлді ауыстыру">${store.role === "teacher" ? "Оқытушы" : "Студент"} ⇄</button>`;
    $("#roleBadge").onclick = () => { store.role = ""; location.hash = "#/"; };
  } else rb.hidden = true;
  try { const d = await api("/api/demo-mode"); $("#demoBadge").hidden = !d.enabled; } catch {}
}
$("#themeBtn").onclick = () => {
  const r = document.documentElement;
  const cur = r.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  r.dataset.theme = cur === "dark" ? "light" : "dark";
  try { localStorage.setItem("olshem-theme", r.dataset.theme); } catch {}
  const f = $("iframe.report"); if (f) f.contentWindow.location.reload();
};

// ------------------------------------------------------------------ router
const routes = [
  [/^#?\/?$/, home],
  [/^#\/t$/, teacherHome],
  [/^#\/t\/new$/, newAssignment],
  [/^#\/t\/a\/(\d+)(?:\/(\w+))?$/, teacherAssignment],
  [/^#\/s$/, studentHome],
  [/^#\/s\/a\/(\d+)$/, studentAssignment],
  [/^#\/r\/(\w+)$/, submissionView],
];
async function route() {
  clearTimers();
  const h = location.hash || "#/";
  if (h.startsWith("#/t") && store.role !== "teacher") store.role = "teacher";
  if (h.startsWith("#/s") && store.role !== "student") store.role = "student";
  refreshChrome();
  for (const [re, fn] of routes) {
    const m = h.match(re);
    if (m) {
      try { await fn(...m.slice(1)); }
      catch (e) { view().innerHTML = `<div class="card" style="margin-top:30px"><h2>Бет ашылмады</h2><p class="mute">${esc(e.message)}</p><a class="btn" href="#/">Басты бетке</a></div>`; }
      $("#main").focus({ preventScroll: true });
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ home
function home() {
  view().innerHTML = `
  <section class="hero">
    <h1>Жазбаша жұмыстарды оқытушы талаптары бойынша алдын ала тексеру</h1>
    <p>Оқытушы талаптарын бір рет жүктейді — жүйе оларды тексеру тізіміне айналдырады. Студент жұмысын тапсырмас бұрын тексеріп,
    бет нөмірі мен дәйексөзге дейін нақтыланған ескертпелер алады.</p>
  </section>
  <div class="grid2">
    <a class="card role" href="#/t"><div class="ic" aria-hidden="true">✎</div><h2>Оқытушы</h2>
      <p class="mute">Талаптарды жүктеп, ЖИ құрған тексеру тізімін түзетесіз және бекітесіз. Топтың жұмыстары мен ортақ статистиканы көресіз.</p></a>
    <a class="card role" href="#/s"><div class="ic" aria-hidden="true">⇪</div><h2>Студент</h2>
      <p class="mute">Жұмысыңызды (.docx, .pdf немесе қолжазба фотосы) жүктеп, тапсырмас бұрын қай талап орындалмағанын біліп аласыз.</p></a>
  </div>
  <h2 style="margin-top:34px">Қалай жұмыс істейді</h2>
  <div class="steps">
    <div><b>Талаптар → тізім.</b> <span class="mute">ЖИ ПОӘК пен силлабусты оқып, ережелер тізімін құрады. Оқытушы оны түзетіп, растайды.</span></div>
    <div><b>Рәсімдеу.</b> <span class="mute">Өріс, қаріп, интервал, бет саны, бөлімдер, кесте атаулары — бағдарлама дәл өлшейді.</span></div>
    <div><b>Мазмұн.</b> <span class="mute">ЖИ тақырыпқа сәйкестікті, қорытынды мен кодты бағалайды. Әр тұжырым жұмыстан алынған дәйексөзбен тексеріледі.</span></div>
    <div><b>Есеп.</b> <span class="mute">Қазақ тіліндегі есеп: талаптарға сәйкестік пайызы және ЖИ ұсынған мазмұн бағасы.</span></div>
  </div>
  <p class="small mute">Демо нұсқа: нақты кіру жүйесі жоқ, рөлді осы жерден таңдайсыз. Болашақта SmartENU арқылы кіру қосылады.</p>`;
}

// ------------------------------------------------------------------ teacher: list
async function teacherHome() {
  const [list, dm, health] = await Promise.all([api("/api/assignments"), api("/api/demo-mode"), api("/api/health").catch(() => null)]);
  const aiLine = health ? (health.ai_configured ? (Object.values(health.models).some((m) => m.status === "ok") ? `<span class="chip ok">ЖИ қолжетімді</span>` : `<span class="chip na">ЖИ күйі тексерілмеген</span>`) : `<span class="chip bad">ЖИ кілті орнатылмаған</span>`) : "";
  view().innerHTML = `
  <div class="page-head"><div><div class="crumbs">Оқытушы</div><h1>Тапсырмалар</h1></div>
    <a class="btn primary" href="#/t/new">+ Жаңа тапсырма</a></div>
  <div class="stack">${list.length ? list.map((a) => `
    <a class="card list-item" href="#/t/a/${a.id}">
      <div><div class="meta">${esc(a.course.name)}${a.course.code ? " · " + esc(a.course.code) : ""}</div>
        <h3>${esc(a.title)}${typeSuffix(a)}</h3>
        <div class="meta">${a.deadline ? "Мерзімі: " + fmtDate(a.deadline) + " · " : ""}${a.submissions_count} жұмыс${a.is_demo ? " · демо деректер" : ""}</div></div>
      ${checklistChip(a)}
    </a>`).join("") : `<div class="card empty">Әзірге тапсырма жоқ. «Жаңа тапсырма» батырмасын басыңыз.</div>`}</div>
  <div class="card" style="margin-top:22px">
    <div class="row"><label class="switch"><input type="checkbox" id="demoSw" ${dm.enabled ? "checked" : ""}><span></span></label>
      <div><b>Демо режимі</b> ${aiLine}<div class="hint">Қорғау кезінде ЖИ сервисі жауап бермесе қосыңыз: үлгі жұмыстар үшін алдын ала сақталған нақты нәтиже көрсетіледі,
      ал есепте бұл ашық жазылады. Басқа файлдарда тек бағдарламалық тексеру жүреді.</div></div></div>
  </div>`;
  $("#demoSw").onchange = async (e) => {
    try { await api("/api/demo-mode", { method: "PUT", json: { enabled: e.target.checked } }); toast(e.target.checked ? "Демо режимі қосылды" : "Демо режимі өшірілді"); refreshChrome(); }
    catch (err) { toast(err.message, true); e.target.checked = !e.target.checked; }
  };
  if (list.some((a) => a.checklist_status === "extracting")) every(3000, () => location.hash === "#/t" && teacherHome());
}

// ------------------------------------------------------------------ teacher: new assignment
function fileDrop(id, { multiple = false, accept = "", label = "", hint = "" }) {
  return `<div class="drop" id="${id}" tabindex="0" role="button" aria-label="${esc(label)}">
    <input type="file" ${multiple ? "multiple" : ""} accept="${accept}">
    <div class="big">${esc(label)}</div><div class="hint">${esc(hint)}</div><ul class="files"></ul></div>`;
}
function bindDrop(el) {
  const input = $("input", el), ul = $(".files", el);
  let files = [];
  const show = () => { ul.innerHTML = files.map((f, i) => `<li><span>${esc(f.name)} <span class="mute">· ${(f.size / 1048576).toFixed(1)} МБ</span></span><a href="#" data-i="${i}">алып тастау</a></li>`).join(""); };
  const add = (list) => { files = input.multiple ? files.concat([...list]) : [...list].slice(0, 1); show(); };
  el.onclick = (e) => { if (e.target.dataset.i !== undefined) { e.preventDefault(); e.stopPropagation(); files.splice(+e.target.dataset.i, 1); show(); return; } input.click(); };
  el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  input.onchange = () => { add(input.files); input.value = ""; };
  el.ondragover = (e) => { e.preventDefault(); el.classList.add("over"); };
  el.ondragleave = () => el.classList.remove("over");
  el.ondrop = (e) => { e.preventDefault(); el.classList.remove("over"); add(e.dataTransfer.files); };
  return () => files;
}

async function newAssignment() {
  const courses = await api("/api/courses").catch(() => []);
  view().innerHTML = `
  <div class="page-head"><div><div class="crumbs"><a href="#/t">Тапсырмалар</a> /</div><h1>Жаңа тапсырма</h1></div></div>
  <form class="card" id="f" novalidate>
    <div class="grid2">
      <div class="field"><label class="f" for="cn">Пән атауы</label><input type="text" id="cn" list="cl" required placeholder="Деректер базасы және SQL сұратымдар">
        <datalist id="cl">${courses.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist></div>
      <div class="field"><label class="f" for="cc">Пән коды <span class="mute">(міндетті емес)</span></label><input type="text" id="cc"></div>
      <div class="field"><label class="f" for="ti">Тапсырма атауы</label><input type="text" id="ti" required placeholder="Курстық жұмыс"></div>
      <div class="field"><label class="f" for="ty">Түрі</label><select id="ty">${Object.entries(TYPES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
      <div class="field"><label class="f" for="dl">Тапсыру мерзімі <span class="mute">(міндетті емес)</span></label><input type="date" id="dl"></div>
    </div>
    <div class="grid2">
      <div class="field"><label class="f">Талаптар</label>${fileDrop("reqDrop", { multiple: true, accept: ".pdf,.jpg,.jpeg,.png,.webp", label: "ПОӘК / әдістемелік нұсқау", hint: "PDF немесе фото · бірнеше файл болады · 20 МБ-қа дейін" })}</div>
      <div class="field"><label class="f">Силлабус <span class="mute">(міндетті емес)</span></label>${fileDrop("sylDrop", { accept: ".pdf", label: "Силлабус PDF", hint: "Тақырыптар тізімі мен оқыту нәтижелері мазмұнды бағалауға көмектеседі" })}</div>
    </div>
    <div class="field"><label class="f" for="rt">Немесе талаптарды мәтінмен жазыңыз</label>
      <textarea id="rt" placeholder="Мысалы: Көлемі 8–10 бет. Times New Roman, 14 pt, интервал 1,0. Кіріспе, негізгі бөлім, қорытынды және кемінде 5 дереккөз болуы керек."></textarea></div>
    <div class="row"><button class="btn primary" id="go" type="submit">Талаптарды талдау</button>
      <span class="hint">ЖИ талаптарды тексеру тізіміне айналдырады (10–20 секунд). Тізімді кейін өзіңіз түзетіп, растайсыз.</span></div>
  </form>`;
  const reqFiles = bindDrop($("#reqDrop")), sylFiles = bindDrop($("#sylDrop"));
  $("#f").onsubmit = async (e) => {
    e.preventDefault();
    const cn = $("#cn").value.trim(), ti = $("#ti").value.trim();
    if (!cn || !ti) return toast("Пән атауы мен тапсырма атауын толтырыңыз", true);
    if (!reqFiles().length && !$("#rt").value.trim()) return toast("Талаптар файлын жүктеңіз немесе мәтінін жазыңыз", true);
    const fd = new FormData();
    fd.append("course_name", cn); fd.append("course_code", $("#cc").value.trim()); fd.append("title", ti);
    fd.append("type", $("#ty").value); if ($("#dl").value) fd.append("deadline", $("#dl").value);
    fd.append("requirement_text", $("#rt").value);
    reqFiles().forEach((f) => fd.append("requirement_files", f));
    if (sylFiles()[0]) fd.append("syllabus_file", sylFiles()[0]);
    $("#go").disabled = true; $("#go").innerHTML = `<span class="spinner"></span>Жүктелуде…`;
    try { const a = await api("/api/assignments", { method: "POST", form: fd }); location.hash = `#/t/a/${a.id}`; }
    catch (err) { toast(err.message, true); $("#go").disabled = false; $("#go").textContent = "Талаптарды талдау"; }
  };
}

// ------------------------------------------------------------------ teacher: assignment
async function teacherAssignment(id, tab = "checklist") {
  const a = await api(`/api/assignments/${id}`);
  view().innerHTML = `
  <div class="page-head"><div><div class="crumbs"><a href="#/t">Тапсырмалар</a> / ${esc(a.course.name)}</div>
    <h1>${esc(a.title)}${typeSuffix(a, 18)}</h1>
    <div class="meta">${a.deadline ? "Мерзімі: " + fmtDate(a.deadline) + " · " : ""}${a.requirement_files.length} талап файлы${a.has_syllabus ? " · силлабус бар" : ""}${a.has_requirement_text ? " · мәтін түріндегі талап" : ""}</div></div>
    ${checklistChip(a)}</div>
  <nav class="tabs" aria-label="Тапсырма бөлімдері">
    <a href="#/t/a/${id}/checklist" class="${tab === "checklist" ? "on" : ""}">Тексеру тізімі</a>
    <a href="#/t/a/${id}/subs" class="${tab === "subs" ? "on" : ""}">Жұмыстар (${a.submissions_count})</a>
    <a href="#/t/a/${id}/stats" class="${tab === "stats" ? "on" : ""}">Топ статистикасы</a>
  </nav><div id="tab"></div>`;
  if (tab === "subs") return subsTab(a);
  if (tab === "stats") return statsTab(a);
  return checklistTab(a);
}

function checklistTab(a) {
  const el = $("#tab");
  if (a.checklist_status === "extracting") {
    el.innerHTML = `<div class="card"><span class="spinner"></span><b>ЖИ талаптарды оқып, тексеру тізімін құрып жатыр…</b>
      <p class="hint">Әдетте 10–20 секунд. Бет өзі жаңарады.</p></div>`;
    every(2500, async () => { const n = await api(`/api/assignments/${a.id}`).catch(() => null); if (n && n.checklist_status !== "extracting") route(); });
    return;
  }
  if (a.checklist_status === "error" && !a.checklist) {
    el.innerHTML = `<div class="banner bad"><b>Талаптарды автоматты өңдеу мүмкін болмады.</b><br>${esc(a.checklist_error)}</div>
      <div class="row"><button class="btn primary" id="retry">Қайталау</button><button class="btn" id="manual">Тізімді қолмен құру</button></div>`;
    $("#retry").onclick = async () => { await api(`/api/assignments/${a.id}/extract`, { method: "POST" }); route(); };
    $("#manual").onclick = () => { a.checklist = { course: a.course.name, assignment: a.title, rules: [] }; a.checklist_status = "ready"; checklistEditor(a); };
    return;
  }
  checklistEditor(a);
}

function ruleParams(r, i) {
  const m = r.metric;
  const num = (k, lbl) => `<div class="p"><label for="${k}${i}">${lbl}</label><input type="number" step="any" id="${k}${i}" data-k="${k}" value="${r[k] ?? ""}"></div>`;
  let h = "";
  if (NUMERIC.includes(m)) h += num("min", m === "references_min" ? "Кемінде" : "Ең аз") + (m === "references_min" ? "" : num("max", "Ең көп"));
  if (m === "font_name") h += `<div class="p wide"><label for="v${i}">Рұқсат етілген қаріптер (| арқылы)</label><input type="text" id="v${i}" data-k="value" value="${esc(r.value || "")}"></div>`;
  if (m === "table_caption") h += `<div class="p"><label for="v${i}">Үлгі</label><input type="text" id="v${i}" data-k="value" value="${esc(r.value || "Кесте-1")}"></div>
     <label class="check"><input type="checkbox" data-k="skip_result_tables" ${r.skip_result_tables ? "checked" : ""}> «Нәтиже:» кестелерін есептемеу</label>`;
  if (m === "page_count") h += `<label class="check"><input type="checkbox" data-k="exclude_appendix" ${r.exclude_appendix ? "checked" : ""}> Қосымшаларды бет санына қоспау</label>`;
  if (m === "page_number_position") h += `<div class="p"><label for="v${i}">Орны</label><select id="v${i}" data-k="value">${[["bottom-center", "Төменде, ортада"], ["bottom-right", "Төменде, оң жақта"], ["top-center", "Жоғарыда, ортада"]].map(([v, l]) => `<option value="${v}" ${r.value === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>`;
  if (m === "required_sections") h += `<div class="p wide"><label for="it${i}">Бөлімдер (әр жолға біреу)</label><textarea id="it${i}" data-k="items" style="min-height:150px;font-weight:400">${esc((r.items || []).join("\n"))}</textarea></div>`;
  if (m === "references_order") h += `<span class="hint">Нормативтік құжаттар басында, қалғаны алфавит бойынша тексеріледі.</span>`;
  return h;
}

function ruleCard(r, i) {
  const metricSel = `<select data-k="metric" aria-label="Кім тексереді">${Object.entries(METRICS).map(([k, v]) => `<option value="${k}" ${r.metric === k ? "selected" : ""}>${k === "none" ? v : "Бағдарлама: " + v}</option>`).join("")}</select>`;
  return `<div class="rule ${r.enabled ? "" : "off"}" data-i="${i}">
    <label class="switch" title="Ережені қосу/өшіру"><input type="checkbox" data-k="enabled" ${r.enabled ? "checked" : ""} aria-label="Ереже қосулы"><span></span></label>
    <div>
      <div class="row" style="margin-bottom:6px"><span class="src-tag ${r.check === "ai" ? "ai" : ""}">${r.check === "ai" ? "ЖИ" : "Бағдарлама"}</span>
        <span class="meta">${esc(r.id)}</span><span class="spacer"></span>
        <button class="btn sm ghost danger" type="button" data-del title="Ережені жою">Жою</button></div>
      <textarea data-k="text_kk" aria-label="Ереже мәтіні" rows="1">${esc(r.text_kk)}</textarea>
      <div class="params">
        <div class="p wide"><label>Кім тексереді</label>${metricSel}</div>
        <div class="p"><label>Маңыздылығы</label><select data-k="severity">${SEVERITY.map((s) => `<option ${r.severity === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
        <div class="p"><label>Санаты</label><select data-k="category">${CATEGORY.map((s) => `<option ${r.category === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
        <label class="check"><input type="checkbox" data-k="optional" ${r.optional ? "checked" : ""}> Міндетті емес (ұсыныс)</label>
      </div>
      <div class="params">${ruleParams(r, i)}</div>
      ${r.source_quote ? `<div class="quote">Түпнұсқада: «${esc(r.source_quote)}»</div>` : ""}
    </div></div>`;
}

function checklistEditor(a) {
  const el = $("#tab");
  const cl = JSON.parse(JSON.stringify(a.checklist));
  cl.rules.forEach((r) => { r.enabled ??= true; r.optional ??= false; });
  let dirty = false;
  const counts = () => { const on = cl.rules.filter((r) => r.enabled); return `${on.length} ереже қосулы: ${on.filter((r) => r.check === "auto").length} бағдарлама, ${on.filter((r) => r.check === "ai").length} ЖИ`; };
  const render = () => {
    el.innerHTML = `
    ${a.checklist_confirmed ? `<div class="banner ok">✓ Тізім расталды — студенттер жұмыс жүктей алады. Өзгерткен соң қайта растаңыз.</div>`
      : `<div class="banner warn"><b>ЖИ құрған тізімді тексеріңіз.</b> Мәндерді түзетіңіз, артығын өшіріңіз, жетпегенін қосыңыз — тек сіз растағаннан кейін студенттер жұмыс жүктей алады.</div>`}
    <div class="row" style="margin-bottom:12px"><span class="meta" id="cnt">${counts()}</span><span class="spacer"></span>
      ${a.checklist_model ? `<span class="meta">ЖИ моделі: ${esc(a.checklist_model)}</span>` : ""}</div>
    <div id="rules">${cl.rules.map(ruleCard).join("") || `<div class="card empty">Ереже жоқ. Төмендегі батырмамен қосыңыз.</div>`}</div>
    <div class="sticky-bar row"><button class="btn" id="add" type="button">+ Ереже қосу</button><span class="spacer"></span>
      <button class="btn" id="save" type="button">Сақтау</button><button class="btn primary" id="confirm" type="button">Растау және студенттерге ашу</button></div>`;
    $$("#rules textarea[data-k=text_kk]").forEach(autosize);
  };
  const autosize = (t) => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; };
  render();
  el.addEventListener("input", (e) => {
    const card = e.target.closest(".rule"); if (!card) return;
    const r = cl.rules[+card.dataset.i], k = e.target.dataset.k; if (!k) return;
    dirty = true;
    if (e.target.type === "checkbox") r[k] = e.target.checked;
    else if (k === "min" || k === "max") r[k] = e.target.value === "" ? null : parseFloat(e.target.value.replace(",", "."));
    else if (k === "items") r.items = e.target.value.split("\n").map((s) => s.trim()).filter(Boolean);
    else r[k] = e.target.value;
    if (k === "text_kk") autosize(e.target);
    if (k === "enabled") { card.classList.toggle("off", !r.enabled); $("#cnt").textContent = counts(); }
    if (k === "metric") { r.check = r.metric === "none" ? "ai" : "auto"; card.outerHTML = ruleCard(r, +card.dataset.i); $("#cnt").textContent = counts(); }
  });
  el.addEventListener("click", async (e) => {
    if (e.target.closest("[data-del]")) {
      const i = +e.target.closest(".rule").dataset.i;
      if (!confirm("Бұл ережені жоямыз ба?")) return;
      cl.rules.splice(i, 1); dirty = true; render();
    } else if (e.target.id === "add") {
      let n = cl.rules.length + 1; while (cl.rules.some((r) => r.id === `rule-${n}`)) n++;
      cl.rules.push({ id: `rule-${n}`, category: "мазмұн", text_kk: "", check: "ai", metric: "none", severity: "маңызды", source_quote: "", enabled: true, optional: false });
      dirty = true; render();
      const last = $$("#rules .rule").pop(); last.scrollIntoView({ behavior: "smooth", block: "center" }); $("textarea", last).focus();
    } else if (e.target.id === "save" || e.target.id === "confirm") {
      const confirmIt = e.target.id === "confirm";
      e.target.disabled = true;
      try {
        const res = await api(`/api/assignments/${a.id}/checklist`, { method: "PUT", json: { checklist: cl, confirm: confirmIt } });
        Object.assign(a, res); dirty = false;
        toast(confirmIt ? "Тізім расталды. Студенттер енді жұмыс жүктей алады." : "Сақталды (әлі расталмаған)");
        if (confirmIt) route(); else render();
      } catch (err) { toast(err.message, true); e.target.disabled = false; }
    }
  });
  window.onbeforeunload = () => (dirty ? true : undefined);
  timers.push(setInterval(() => { if (!location.hash.includes(`/t/a/${a.id}`)) { window.onbeforeunload = null; } }, 1000));
}

async function subsTab(a) {
  const el = $("#tab");
  const load = async () => {
    const subs = await api(`/api/assignments/${a.id}/submissions`);
    el.innerHTML = subs.length ? `<div class="card" style="padding:6px 12px"><table class="tbl">
      <thead><tr><th>Студент</th><th>Файл</th><th>Күйі</th><th>Сәйкестік</th><th>Мазмұн (ЖИ)</th><th>Ескерту</th><th>Уақыты</th><th></th></tr></thead><tbody>
      ${subs.map((s) => `<tr>
        <td data-l="Студент"><b>${esc(s.student_label || "—")}</b>${s.demo ? ` <span class="chip warn">демо</span>` : ""}</td>
        <td data-l="Файл" class="meta">${esc(s.original_name)}</td>
        <td data-l="Күйі">${statusChip(s)}</td>
        <td data-l="Сәйкестік" class="num">${pct(s.compliance_pct)}</td>
        <td data-l="Мазмұн (ЖИ)" class="num" title="${s.ai_error ? esc(s.ai_error) : "ЖИ ұсынысы, соңғы баға сізде"}">${scoreTxt(s.ai_score)}</td>
        <td data-l="Ескерту" class="num">${s.status === "done" ? s.problems : "—"}</td>
        <td data-l="Уақыты" class="meta">${fmtTime(s.created_at)}</td>
        <td data-l=""><div class="row" style="gap:6px;flex-wrap:nowrap">${s.status === "done" || s.status === "error" ? `<a class="btn sm" href="#/r/${s.id}">${s.status === "done" ? "Есеп" : "Толығырақ"}</a>` : ""}
          <button class="btn sm ghost danger" data-del="${s.id}" title="Жою">✕</button></div></td></tr>`).join("")}
      </tbody></table></div>
      <p class="hint" style="margin-top:10px">«Сәйкестік» — бағдарлама есептеген пайыз. «Мазмұн (ЖИ)» — тек ұсыныс; соңғы баға сізде.</p>`
      : `<div class="card empty">Әзірге жұмыс жіберілмеген.</div>`;
    return subs;
  };
  const subs = await load();
  el.onclick = async (e) => {
    const id = e.target.dataset.del; if (!id) return;
    if (!confirm("Жұмыс пен оның файлын біржола жоямыз ба?")) return;
    try { await api(`/api/submissions/${id}`, { method: "DELETE" }); toast("Жойылды"); load(); } catch (err) { toast(err.message, true); }
  };
  if (subs.some((s) => !["done", "error"].includes(s.status))) every(3000, load);
}

async function statsTab(a) {
  const st = await api(`/api/assignments/${a.id}/stats`);
  const maxB = Math.max(1, ...Object.values(st.compliance_buckets));
  $("#tab").innerHTML = `
  <div class="grid3">
    <div class="card kpi"><b>${st.submissions_done}</b><span>тексерілген жұмыс (барлығы ${st.submissions_total})</span></div>
    <div class="card kpi"><b>${pct(st.avg_compliance_pct)}</b><span>орташа талаптарға сәйкестік</span></div>
    <div class="card kpi"><b>${st.avg_ai_score ?? "—"}</b><span>орташа мазмұн бағасы (ЖИ ұсынысы)</span></div>
  </div>
  <div class="grid2" style="margin-top:16px;align-items:start">
    <div class="card"><h2>Ең жиі кездесетін мәселелер</h2>
      ${st.top_problems.length ? st.top_problems.map((p) => `<div class="bar"><div><div>${esc(p.text_kk)}</div><div class="meta">${p.source} · сәйкес емес: ${p.failed}, ішінара: ${p.partial}</div></div>
        <div class="track" role="img" aria-label="${p.share_pct}%"><i class="f" style="width:${p.share_pct * p.failed / Math.max(1, p.failed + p.partial)}%"></i><i class="p" style="width:${p.share_pct * p.partial / Math.max(1, p.failed + p.partial)}%"></i></div>
        <div class="num">${p.share_pct}%</div></div>`).join("") : `<p class="mute">Мәселе табылмады немесе тексерілген жұмыс жоқ.</p>`}
      <div class="legend"><span><i style="background:var(--bad)"></i>сәйкес емес</span><span><i style="background:var(--warn)"></i>ішінара</span><span>% — жұмыстардың үлесі</span></div>
    </div>
    <div class="card"><h2>Сәйкестік бойынша бөліну</h2>
      ${Object.entries(st.compliance_buckets).map(([k, v]) => `<div class="bar" style="grid-template-columns:80px 1fr 30px"><div class="meta">${k}</div>
        <div class="track"><i style="width:${100 * v / maxB}%;background:var(--accent)"></i></div><div class="num">${v}</div></div>`).join("")}
      <p class="hint" style="margin-top:10px">Топқа ортақ қателерді сабақта бір рет түсіндіру — әр жұмысқа жеке жазудан тиімдірек.</p>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ student
async function studentHome() {
  const list = await api("/api/assignments?confirmed_only=true");
  view().innerHTML = `
  <div class="page-head"><div><div class="crumbs">Студент</div><h1>Тапсырманы таңдаңыз</h1>
    <p class="mute">Жұмысыңызды оқытушыға тапсырмас бұрын тексеріп алыңыз.</p></div></div>
  <div class="stack">${list.length ? list.map((a) => `
    <a class="card list-item" href="#/s/a/${a.id}"><div><div class="meta">${esc(a.course.name)}</div>
      <h3>${esc(a.title)}${typeSuffix(a)}</h3>
      <div class="meta">${a.deadline ? "Мерзімі: " + fmtDate(a.deadline) + " · " : ""}${a.checklist.rules.filter((r) => r.enabled).length} талап</div></div>
      <span class="btn primary sm">Тексеру →</span></a>`).join("") : `<div class="card empty">Оқытушы растаған тапсырма әлі жоқ.</div>`}</div>`;
}

async function studentAssignment(id) {
  const a = await api(`/api/assignments/${id}`);
  const rules = (a.checklist?.rules || []).filter((r) => r.enabled);
  view().innerHTML = `
  <div class="page-head"><div><div class="crumbs"><a href="#/s">Тапсырмалар</a> / ${esc(a.course.name)}</div>
    <h1>${esc(a.title)}</h1><div class="meta">${esc(TYPES[a.type] || a.type)}${a.deadline ? " · Мерзімі: " + fmtDate(a.deadline) : ""}</div></div></div>
  ${!a.checklist_confirmed ? `<div class="banner warn">Оқытушы тексеру тізімін әлі растаған жоқ.</div>` : ""}
  <div class="grid2" style="align-items:start">
    <form class="card" id="f">
      <h2>Жұмысты жүктеу</h2>
      <div class="field"><label class="f" for="lbl">Аты-жөніңіз немесе студенттік код <span class="mute">(міндетті емес)</span></label>
        <input type="text" id="lbl" maxlength="80"><div class="hint">Есепте көрсетіледі. ЖИ-ге жіберілмейді — мәтіннен де жасырылады.</div></div>
      <div class="field">${fileDrop("wDrop", { multiple: true, accept: ".docx,.pdf,.jpg,.jpeg,.png,.webp", label: "Файлды осында сүйреңіз немесе таңдаңыз", hint: ".docx (ең дәл), .pdf немесе қолжазба беттерінің фотолары (ретімен) · 20 МБ-қа дейін" })}</div>
      <div class="row"><button class="btn primary" id="go" type="submit" ${a.checklist_confirmed ? "" : "disabled"}>Тексеруге жіберу</button>
        ${a.is_demo && a.checklist_confirmed ? `<button class="btn" id="sample" type="button">Үлгі жұмыспен көру</button>` : ""}</div>
      <p class="hint" style="margin-top:10px">Тексеру шамамен 45 секунд алады. Файл тек осы серверде сақталады.</p>
    </form>
    <div class="card"><details ${rules.length <= 8 ? "open" : ""}><summary>Талаптар тізімі (${rules.length})</summary>
      <ul style="padding-left:18px;margin:10px 0 0">${rules.map((r) => `<li style="margin:5px 0">${esc(r.text_kk)} <span class="src-tag ${r.check === "ai" ? "ai" : ""}">${r.check === "ai" ? "ЖИ" : "Бағдарлама"}</span>${r.optional ? ` <span class="meta">(ұсыныс)</span>` : ""}</li>`).join("")}</ul></details></div>
  </div>`;
  const files = bindDrop($("#wDrop"));
  $("#f").onsubmit = async (e) => {
    e.preventDefault();
    const fs = files();
    if (!fs.length) return toast("Алдымен файл таңдаңыз", true);
    const fd = new FormData();
    fs.forEach((f) => fd.append("files", f)); fd.append("student_label", $("#lbl").value.trim());
    $("#go").disabled = true; $("#go").innerHTML = `<span class="spinner"></span>Жүктелуде…`;
    try { const s = await api(`/api/assignments/${id}/submissions`, { method: "POST", form: fd }); location.hash = `#/r/${s.id}`; }
    catch (err) { toast(err.message, true); $("#go").disabled = false; $("#go").textContent = "Тексеруге жіберу"; }
  };
  const sb = $("#sample");
  if (sb) sb.onclick = async () => {
    sb.disabled = true;
    try { const s = await api(`/api/assignments/${id}/submissions/sample`, { method: "POST" }); location.hash = `#/r/${s.id}`; }
    catch (err) { toast(err.message, true); sb.disabled = false; }
  };
}

// ------------------------------------------------------------------ submission progress + report
const STAGE_HINT = {
  queued: "Кезекте тұр…",
  format: "Бағдарлама өрістерді, қаріпті, интервалды, бет санын және бөлімдерді өлшеп жатыр…",
  ocr: "ЖИ қолжазбаны оқып жатыр — қазақ әріптерін (ә ғ қ ң ө ұ ү һ і) бөлек тексереді…",
  review: "ЖИ жұмысты оқытушы талаптары мен силлабус бойынша оқып жатыр. Әдетте 25–35 секунд.",
};
async function submissionView(sid) {
  let s = await api(`/api/submissions/${sid}`);
  const back = store.role === "teacher" ? `#/t/a/${s.assignment_id}/subs` : `#/s/a/${s.assignment_id}`;
  view().innerHTML = `
  <div class="page-head"><div><div class="crumbs"><a href="${back}">${esc(s.assignment_title)}</a> /</div>
    <h1>${esc(s.student_label || s.original_name || "Жұмыс")}</h1><div class="meta">${esc(s.original_name)}</div></div><div id="acts" class="row"></div></div>
  <div class="card" id="prog"></div><div id="rep" style="margin-top:16px"></div>`;
  const draw = () => {
    $("#prog").style.setProperty("--n", s.stages.length);
    $("#prog").innerHTML = `<div class="stepper" style="--n:${s.stages.length}">${s.stages.map((st) => `<div class="st ${st.state}">${esc(st.label)}</div>`).join("")}</div>
      ${s.status === "done" ? `<div class="row"><b>Тексеру аяқталды</b><span class="meta">${s.elapsed_s > 0.5 ? Math.round(s.elapsed_s) + " с" : ""}</span>
          ${s.demo ? `<span class="chip warn">демо: сақталған нәтиже</span>` : ""}
          ${s.ai_error ? `<span class="chip warn" title="${esc(s.ai_error)}">мазмұн бағаланбады</span>` : ""}</div>`
      : s.status === "error" ? `<div class="banner bad" style="margin:0"><b>Тексеру сәтсіз аяқталды.</b> ${esc(s.error || "")}</div>`
      : `<p style="margin:0"><span class="spinner"></span>${STAGE_HINT[s.status] || ""} <span class="meta" id="el">${Math.round(s.elapsed_s || 0)} с</span></p>`}`;
    if (s.status === "done") {
      $("#acts").innerHTML = `<a class="btn" href="${s.report_url}" target="_blank" rel="noopener">Жаңа бетте ашу</a>
        <button class="btn" id="pr">Басып шығару / PDF</button>${store.role === "student" ? `<a class="btn primary" href="#/s/a/${s.assignment_id}">Жаңа нұсқаны жүктеу</a>` : ""}`;
      $("#pr").onclick = () => $("iframe.report").contentWindow.print();
      $("#rep").innerHTML = `<iframe class="report" title="Тексеру есебі" src="${s.report_url}?embed=1"></iframe>`;
      const f = $("iframe.report");
      const fit = () => { try { f.style.height = f.contentDocument.documentElement.scrollHeight + 20 + "px"; } catch {} };
      f.onload = () => { fit(); setTimeout(fit, 300); };
    } else if (s.status === "error") {
      $("#acts").innerHTML = `<button class="btn primary" id="rt">Қайталау</button>`;
      $("#rt").onclick = async () => { try { await api(`/api/submissions/${sid}/retry`, { method: "POST" }); route(); } catch (e) { toast(e.message, true); } };
    }
  };
  draw();
  if (!["done", "error"].includes(s.status)) {
    const t0 = Date.now() - (s.elapsed_s || 0) * 1000;
    every(1000, () => { const el = $("#el"); if (el) el.textContent = Math.round((Date.now() - t0) / 1000) + " с"; });
    every(1500, async () => {
      try { const n = await api(`/api/submissions/${sid}`); if (n.status !== s.status || ["done", "error"].includes(n.status)) { s = n; draw(); if (["done", "error"].includes(n.status)) clearTimers(); } }
      catch {}
    });
  }
}

route();
