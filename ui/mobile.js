"use strict";
// Jarvis on the phone: talks to the laptop's Jarvis over Tailscale with this phone's own device key
// (an HttpOnly cookie set when pairing). On the laptop itself, the page uses the per-run token instead.
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let state = "idle", level = 0, voiceLevel = 0;  // read by orb.js
let speakReplies = localStorage.getItem("speak") !== "0";
let awaitingReply = false;

// ------------------------------------------------------------ talking to the laptop
class Offline extends Error {}
class NotPaired extends Error {}

async function call(name, ...args) {
  const headers = { "Content-Type": "application/json" };
  if (window.JARVIS_TOKEN) headers["X-Jarvis-Token"] = window.JARVIS_TOKEN;
  let r;
  try {
    r = await fetch("/api/" + name, { method: "POST", headers, body: JSON.stringify(args), credentials: "same-origin" });
  } catch {
    setOnline(false);
    throw new Offline("Laptop offline");
  }
  if (r.status >= 502) { setOnline(false); throw new Offline("Laptop offline"); }  // Tailscale can't reach Jarvis
  setOnline(true);
  const data = await r.json().catch(() => null);
  if (r.status === 403) {
    if (data === "bad token") { showPair(); throw new NotPaired("Pair this phone first"); }
    throw new Error(typeof data === "string" ? data : "Not allowed");
  }
  if (!r.ok) throw new Error(data && data.error ? data.error : "Request failed (" + r.status + ")");
  return data;
}

function setOnline(on) {
  $("#dot").className = "dot " + (on ? "on" : "off");
  if (on) {
    localStorage.setItem("lastSeen", Date.now());
    $("#status").textContent = "Laptop online";
    $("#offline").classList.add("hidden");
  } else {
    const t = +localStorage.getItem("lastSeen");
    $("#last-seen").textContent = t ? `(last seen ${ago(t)})` : "";
    $("#status").textContent = "Laptop offline";
    $("#offline").classList.remove("hidden");
  }
}

function ago(t) {
  const m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : new Date(t).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

let es = null;
function listen() {
  if (es) es.close();
  es = new EventSource("/events" + (window.JARVIS_TOKEN ? "?token=" + encodeURIComponent(window.JARVIS_TOKEN) : ""));
  es.onopen = () => setOnline(true);
  es.onmessage = (e) => { const m = JSON.parse(e.data); onEvent(m.kind, m.data); };
  es.onerror = () => { es.close(); es = null; setTimeout(check, 3000); };
}

async function check() {
  try { await call("ping"); if (!es) listen(); } catch (e) { if (!(e instanceof NotPaired)) setTimeout(check, 10000); }
}

function onEvent(kind, d) {
  switch (kind) {
    case "state": state = d.state; break;
    case "voice_level": voiceLevel = d.rms; break;
    case "message": addMessage(d); if (d.role === "assistant" && awaitingReply) { awaitingReply = false; say(d.text); } break;
    case "image": addImage(d); break;
    case "approval": showApproval(d); break;
    case "approval_done": { const el = $("#ap-" + d.id); if (el) el.remove(); break; }
    case "warning": toast(d.text); break;
    case "notification": toast(d.text); if (!$("#tab-tasks").classList.contains("hidden")) loadTasks(); break;
  }
}

// ------------------------------------------------------------ chat
const AGENT_COLOURS = { jarvis: "#ffb040", scholar: "#6fb3ff", forge: "#ff8a5c", herald: "#c58cff", operator: "#4fe3a1", scout: "#ffd84f" };

function addMessage(m) {
  if (m.channel && m.channel !== "jarvis") return;  // the phone shows the main chat with Jarvis
  const div = document.createElement("div");
  div.className = "msg " + m.role;
  if (m.role === "assistant") {  // which team member answered
    const name = m.agent || "jarvis";
    div.style.setProperty("--c", AGENT_COLOURS[name] || "#ffb040");
    const who = document.createElement("div"); who.className = "who";
    who.append(document.createElement("i"), document.createTextNode(name[0].toUpperCase() + name.slice(1)));
    div.appendChild(who);
  }
  div.appendChild(document.createTextNode(m.text));
  (m.sources || []).forEach((s, i) => {
    const a = document.createElement("a");
    a.href = s.url; a.target = "_blank"; a.rel = "noopener"; a.textContent = `[${i + 1}] ${s.title}`;
    div.append(document.createElement("br"), a);
  });
  const small = document.createElement("small");
  small.textContent = new Date((m.ts || Date.now() / 1000) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  div.appendChild(small);
  $("#chat").appendChild(div);
  $("#chat").scrollTop = $("#chat").scrollHeight;
}

function addImage(d) {
  const div = document.createElement("div"); div.className = "msg assistant";
  const img = document.createElement("img"); img.src = d.data; img.alt = d.caption || "image";
  img.onclick = () => window.open(d.data);
  div.append(document.createTextNode(d.caption || ""), img);
  $("#chat").appendChild(div); $("#chat").scrollTop = $("#chat").scrollHeight;
}

function say(text) {
  if (!speakReplies || !("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance(text);
  const v = speechSynthesis.getVoices().find((x) => /en-GB/i.test(x.lang) && /male|ryan|george|daniel/i.test(x.name))
    || speechSynthesis.getVoices().find((x) => /en-GB/i.test(x.lang));
  if (v) u.voice = v;
  speechSynthesis.cancel(); speechSynthesis.speak(u);
}

async function send(text) {
  text = text.trim(); if (!text) return;
  try { awaitingReply = true; await call("send_text", text); } catch (e) { awaitingReply = false; toast(e.message); }
}

function showApproval(p) {
  if ($("#ap-" + p.id)) return;
  const card = document.createElement("div"); card.className = "approval"; card.id = "ap-" + p.id;
  const b = document.createElement("b"); b.textContent = p.title;
  const pre = document.createElement("pre");
  pre.textContent = Object.entries(p.preview || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
  const row = document.createElement("div"); row.className = "row";
  const ok = document.createElement("button"); ok.textContent = "Approve";
  ok.onclick = async () => { card.remove(); try { awaitingReply = true; toast(await call("approve", p.id)); } catch (e) { toast(e.message); } };
  const no = document.createElement("button"); no.textContent = "Cancel";
  no.onclick = async () => { card.remove(); try { await call("reject", p.id); } catch (e) { toast(e.message); } };
  row.append(ok, no); card.append(b, pre, row); $("#approvals").appendChild(card);
}

// hold-to-talk: recorded here, transcribed by the laptop's own speech model
let rec = null, chunks = [];
async function startRec() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      $("#mic").classList.remove("rec");
      const blob = new Blob(chunks, { type: rec.mimeType });
      if (blob.size < 2000) return;
      const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(blob); });
      try {
        awaitingReply = true;
        const r = await call("voice", b64);
        if (!r.ok) { awaitingReply = false; toast(r.error || "I didn't catch that."); }
      } catch (e) { awaitingReply = false; toast(e.message); }
    };
    rec.start(); $("#mic").classList.add("rec");
  } catch { toast("The microphone needs permission, and works only over the https:// address."); }
}
function stopRec() { if (rec && rec.state === "recording") rec.stop(); }

// ------------------------------------------------------------ today tab
function rows(sel, items, empty) {
  const ul = $(sel); ul.innerHTML = "";
  (items.length ? items : [{ text: empty }]).forEach((x) => {
    const li = document.createElement("li"); const d = document.createElement("div");
    const b = document.createElement("b"); b.textContent = x.text; d.appendChild(b);
    if (x.sub) { const s = document.createElement("small"); s.textContent = x.sub; d.appendChild(s); }
    li.className = x.cls || ""; li.appendChild(d);
    if (x.button) li.appendChild(x.button);
    ul.appendChild(li);
  });
}

async function loadToday() {
  try {
    const d = await call("today"), s = d.briefing.sections;
    $("#td-brief").textContent = d.briefing.spoken;
    const cls = (x) => x.due.startsWith("overdue") || x.due === "today" ? "urgent" : x.due === "tomorrow" ? "soon" : "";
    rows("#td-tasks", [...s.tasks.overdue, ...s.tasks.top.filter((x) => !s.tasks.overdue.some((o) => o.id === x.id))].slice(0, 6)
      .map((x) => ({ text: x.title, sub: "due " + x.due, cls: cls(x) })), "Nothing open.");
    const files = s.agent.files.map((f) => {
      const o = document.createElement("button"); o.textContent = "Open on laptop";
      o.onclick = async () => { try { toast(await call("open_result", f.id)); } catch (e) { toast(e.message); } };
      return { text: "Prepared " + f.title, sub: f.file, button: o };
    });
    rows("#td-agent", [...files,
      ...(s.agent.approvals ? [{ text: `${s.agent.approvals} waiting for your approval`, sub: "see the Chat tab", cls: "soon" }] : []),
      ...s.agent.failed.map((x) => ({ text: "Couldn't finish " + x, cls: "urgent" })),
      { text: `${s.agent.checks} checks, ${s.messages.school} school items`, sub: `${s.messages.emails} emails, ${s.messages.messages} messages` }], "");
    rows("#td-schedule", [...s.schedule.today.map((e) => ({ text: e.subject, sub: "today " + e.time })),
      ...s.schedule.tomorrow.map((e) => ({ text: e.subject, sub: "tomorrow " + e.time }))], "Nothing on your calendar.");
  } catch (e) { if (!(e instanceof Offline) && !(e instanceof NotPaired)) toast(e.message); }
}

// ------------------------------------------------------------ tasks tab
function renderTasks(list) {
  const ul = $("#tasks"); ul.innerHTML = "";
  if (!list.length) { const li = document.createElement("li"); li.textContent = "Nothing on your list."; ul.appendChild(li); return; }
  list.forEach((t) => {
    const li = document.createElement("li");
    li.className = t.due_text.startsWith("overdue") || t.due_text === "today" ? "urgent" : t.due_text === "tomorrow" ? "soon" : "";
    const d = document.createElement("div");
    const b = document.createElement("b"); b.textContent = t.title;
    const s = document.createElement("small"); s.textContent = (t.due ? "due " + t.due_text : "no due date") + " · " + t.kind;
    d.append(b, s);
    const done = document.createElement("button"); done.textContent = "Done";
    done.onclick = async () => { try { renderTasks(await call("complete_task", t.id)); } catch (e) { toast(e.message); } };
    li.append(d, done); ul.appendChild(li);
  });
}

async function loadJobs() {
  const ul = $("#jobs"); ul.innerHTML = "";
  const states = { done: "ready", running: "working on it", queued: "queued", waiting: "waiting for AI budget", failed: "couldn't finish" };
  const list = (await call("jobs")).slice(0, 8);
  if (!list.length) { const li = document.createElement("li"); li.textContent = "Nothing prepared yet."; ul.appendChild(li); return; }
  list.forEach((j) => {
    const li = document.createElement("li");
    const d = document.createElement("div");
    const b = document.createElement("b"); b.textContent = j.title;
    const s = document.createElement("small"); s.textContent = `${j.kind} · ${states[j.state] || j.state}`;
    d.append(b, s); li.appendChild(d);
    if (j.state === "done") {
      const o = document.createElement("button"); o.textContent = "Open on laptop";
      o.onclick = async () => { try { toast(await call("open_result", j.id)); } catch (e) { toast(e.message); } };
      li.appendChild(o);
    }
    ul.appendChild(li);
  });
}

async function loadTasks() {
  try {
    loadJobs().catch(() => {});
    renderTasks(await call("tasks"));
    const s = await call("agent_status");
    const last = s.last_run ? new Date(s.last_run * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "never";
    $("#ag-text").textContent = `${s.running ? "Checking now… " : ""}Last check ${last}. ${s.summary} AI used today: ${s.usage.total} of about ${s.usage.limit}.`;
  } catch (e) { if (!(e instanceof Offline)) toast(e.message); }
}

// ------------------------------------------------------------ laptop tab
async function loadLaptop() {
  try {
    const s = await call("laptop_status");
    $("#lp-name").textContent = s.name;
    $("#lp-battery").textContent = s.battery ? `${s.battery.percent}%${s.battery.plugged ? " ⚡" : ""}` : "mains";
    $("#lp-cpu").textContent = Math.round(s.cpu) + "%";
    $("#lp-ram").textContent = Math.round(s.ram) + "%";
    $("#lp-awake").textContent = s.keep_awake ? "kept awake" : "normal";
    $("#lp-state").textContent = s.game_mode ? "game mode" : s.state;
    $("#lp-uptime").textContent = s.uptime_h + " h";
  } catch (e) { if (!(e instanceof Offline)) toast(e.message); }
}

function out(node) { const o = $("#lp-out"); o.innerHTML = ""; if (typeof node === "string") o.textContent = node; else o.appendChild(node); }

function wireLaptop() {
  $$("#quick-open button").forEach((b) => b.onclick = () => { send(b.dataset.cmd); toast("Sent: " + b.dataset.cmd); });
  $("#btn-shot").onclick = async () => {
    out("Taking a screenshot…");
    try { const img = document.createElement("img"); img.src = await call("screenshot"); img.onclick = () => window.open(img.src); out(img); }
    catch (e) { out(e.message); }
  };
  $("#btn-apps").onclick = async () => {
    try {
      const apps = await call("running_apps");
      const ul = document.createElement("ul");
      apps.forEach((a) => { const li = document.createElement("li"); li.textContent = a.app + (a.title ? " · " + a.title.slice(0, 50) : ""); ul.appendChild(li); });
      out(apps.length ? ul : "Nothing with a window is open.");
    } catch (e) { out(e.message); }
  };
  $("#btn-lock").onclick = async () => { try { out(await call("lock_laptop")); } catch (e) { out(e.message); } };
  $("#btn-game").onclick = async () => { try { const s = await call("laptop_status"); out(await call("game_mode", !s.game_mode)); } catch (e) { out(e.message); } };
  for (const [id, action, label] of [["#btn-restart", "restart", "Restart"], ["#btn-shutdown", "shutdown", "Shut down"]]) {
    $(id).onclick = async () => {
      if (!confirm(`${label} the laptop? Anything unsaved on it will be lost. It happens after 30 seconds, and "Cancel" stops it.`)) return;
      try { out(await call("power", action)); } catch (e) { out(e.message); }
    };
  }
  $("#btn-cancel").onclick = async () => { try { out(await call("cancel_power")); } catch (e) { out(e.message); } };
}

// ------------------------------------------------------------ pairing
function showPair() {
  $("#app").classList.add("hidden"); $("#tabs").classList.add("hidden"); $("#pair").classList.remove("hidden");
  $("#status").textContent = "Not paired";
  const code = (location.hash.match(/pair=(\d{6})/) || [])[1];
  if (code) $("#pair-code").value = code;
}

async function pair(code, name) {
  const r = await fetch("/pair", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
    body: JSON.stringify({ code, name }) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.ok) throw new Error(d.error || "Pairing failed.");
  history.replaceState(null, "", "/m");
}

// ------------------------------------------------------------ start
function toast(text) {
  const t = $("#toast"); t.textContent = text; t.classList.remove("hidden");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.add("hidden"), 4000);
}

async function start() {
  try {
    const init = await call("init");
    $("#pair").classList.add("hidden"); $("#app").classList.remove("hidden"); $("#tabs").classList.remove("hidden");
    $("#chat").innerHTML = "";
    init.history.forEach(addMessage);
    init.pending.forEach(showApproval);
    state = init.state;
    listen();
    loadToday();
  } catch (e) {
    if (e instanceof Offline) { $("#app").classList.remove("hidden"); $("#tabs").classList.remove("hidden"); setTimeout(start, 10000); }
  }
}

window.addEventListener("load", () => {
  startOrb($("#pair-orb"));
  $$("#tabs button").forEach((b) => b.onclick = () => {
    $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== "tab-" + b.dataset.tab));
    if (b.dataset.tab === "laptop") loadLaptop();
    if (b.dataset.tab === "tasks") loadTasks();
    if (b.dataset.tab === "today") loadToday();
  });
  $("#td-read").onclick = () => { const was = speakReplies; speakReplies = true; say($("#td-brief").textContent); speakReplies = was; };
  $("#td-refresh").onclick = async () => {
    try { $("#td-brief").textContent = await call("brief_me"); loadToday(); } catch (e) { toast(e.message); }
  };
  $("#task-add").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await call("add_task", $("#task-title").value, $("#task-due").value);
      if (!r.ok) { toast(r.error); return; }
      $("#task-title").value = ""; $("#task-due").value = ""; renderTasks(r.tasks);
    } catch (err) { toast(err.message); }
  };
  $("#agent-run").onclick = async () => {
    try { toast(await call("agent_run_now")); setTimeout(loadTasks, 2000); } catch (e) { toast(e.message); }
  };
  $("#ask").onsubmit = (e) => { e.preventDefault(); send($("#ask-input").value); $("#ask-input").value = ""; };
  const mic = $("#mic");
  mic.addEventListener("pointerdown", (e) => { e.preventDefault(); startRec(); });
  mic.addEventListener("pointerup", stopRec); mic.addEventListener("pointerleave", stopRec);
  $("#pair-name").value = /Android/i.test(navigator.userAgent) ? "Android phone" : "Phone";
  $("#pair-form").onsubmit = async (e) => {
    e.preventDefault(); $("#pair-err").textContent = "";
    try { await pair($("#pair-code").value, $("#pair-name").value); start(); }
    catch (err) { $("#pair-err").textContent = err.message; }
  };
  wireLaptop();
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
  start();
  setInterval(() => { if (!document.hidden) check(); }, 20000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
});
