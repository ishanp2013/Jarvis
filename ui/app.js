"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let api = null;
let S = {};               // settings
let state = "starting";
let level = 0;            // mic loudness while listening
let voiceLevel = 0;       // Jarvis's own voice loudness while speaking
let micOn = false;
let TEAM = {};            // agent name -> profile (title, colour, job…)
let channel = "jarvis";   // the open chat: "jarvis", "team" (#team feed) or a specialist's name
window.orbState = () => ({ state, level, voiceLevel, gameMode: !!window.gameMode });

const LABELS = {
  idle: "Standing by", listening: "Listening", transcribing: "Processing", thinking: "Thinking",
  speaking: "Speaking", starting: "Starting up", "loading speech model": "Loading speech model",
};

// ------------------------------------------------------------ events from Python
window.onJarvis = (kind, d) => {
  switch (kind) {
    case "state": setState(d.state); break;
    case "level": level = d.rms; break;
    case "voice_level": voiceLevel = d.rms; break;
    case "mic": setMic(d.on, d.error); break;
    case "wake": $("#hint").textContent = "Yes?"; break;
    case "message": onMessage(d); break;
    case "handoff": onHandoff(d); break;
    case "approval": showApproval(d); break;
    case "approval_done": doneApproval(d); break;
    case "activity": $("#st-activity").textContent = d.text; addActivity({ ts: Date.now() / 1000, kind: "activity", text: d.text }); break;
    case "warning": toast(d.text); break;
    case "notification": toast(d.text); if (!$("#tab-tasks").classList.contains("hidden")) loadAgent();
      if (!$("#tab-today").classList.contains("hidden")) loadToday(); break;
    case "briefing": if (!$("#tab-today").classList.contains("hidden")) loadToday(); break;
    case "paired": toast(`Paired ${d.name}.`); $("#pair-box").classList.add("hidden"); renderDevices(); break;
    case "game_mode": setGame(d.on);
      if (d.auto) toast(d.on ? `Game mode on${d.game ? " (" + d.game + ")" : ""}: listening paused.` : "Game mode off: listening again.");
      break;
    case "system": setSystem(d); break;
    case "ready": $("#st-stt").textContent = d.stt ? `ready (${S.stt_model})` : "unavailable";
      $("#chip-wake").className = "chip " + (d.wake && S.wake_word_enabled ? "on" : "off"); break;
  }
};

let wakePhrase = "Hey Jarvis";

function setGame(on) {
  window.gameMode = !!on;
  $("#chip-game").className = "chip " + (on ? "mid" : "off");
  $("#chip-game").textContent = on ? "Game mode on" : "Game mode";
  setState(state);
}

function setState(s) {
  state = s;
  $("#state-label").textContent = window.gameMode && s === "idle" ? "Game mode" : LABELS[s] || s;
  $("#st-state").textContent = s;
  const hints = { listening: "Go ahead…", speaking: `Say "${wakePhrase}" or press Stop to interrupt.`,
    idle: window.gameMode ? "Listening is paused while you play. Type below, or press the Game mode chip."
      : micOn ? `Say "${wakePhrase}", or press Talk.` : "Microphone is off. Type below or turn the mic on." };
  $("#hint").textContent = hints[s] || "";
  if (s === "idle") $("#st-activity").textContent = "-";
}

function setMic(on, error) {
  micOn = !!on;
  $("#btn-mic").classList.toggle("muted-mic", !micOn);
  $("#btn-mic").textContent = micOn ? "Mic" : "Muted";
  $("#chip-mic").className = "chip " + (micOn ? "on" : "off");
  $("#chip-mic").textContent = micOn ? "Mic on" : "Mic off";
  $("#st-mic").textContent = micOn ? "on" : error ? "error" : "off";
  if (error) toast("Microphone: " + error);
  setState(state);
}

function setSystem(d) {
  $("#m-cpu").style.width = d.cpu + "%"; $("#v-cpu").textContent = Math.round(d.cpu) + "%";
  $("#m-ram").style.width = d.ram + "%"; $("#v-ram").textContent = Math.round(d.ram) + "%";
  $("#v-me").textContent = `${d.jarvis_mb} MB · ${d.jarvis_cpu}% CPU`;
}

// ------------------------------------------------------------ conversation
function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

// ------------------------------------------------------------ the team (Discord-style chat)
function agentOf(name) { return TEAM[name] || { name: name || "jarvis", title: name ? name[0].toUpperCase() + name.slice(1) : "Jarvis", color: "#ffb040", job: "" }; }

function avatar(name, size) {
  const a = agentOf(name), el = document.createElement("span");
  el.className = "avatar" + (size ? " " + size : ""); el.style.setProperty("--c", a.color); el.textContent = a.title[0];
  el.title = a.title;
  return el;
}

async function loadTeam() {
  try {
    const list = await api.team();
    list.forEach((a) => { TEAM[a.name] = a; });
    renderRoster(list);
    if (channel !== "jarvis" && channel !== "team") renderChannelHead();
    $$("#channels .chan").forEach((b) => { const a = TEAM[b.dataset.chan]; if (a) b.dataset.status = a.status; });
  } catch (e) { console.warn("team", e); }
}

function renderRoster(list) {
  const ul = $("#roster"); ul.innerHTML = "";
  list.forEach((a) => {
    const li = document.createElement("li"); li.dataset.status = a.status; li.style.setProperty("--c", a.color);
    li.appendChild(avatar(a.name, "sm"));
    const t = document.createElement("div");
    const b = document.createElement("b"); b.textContent = a.title;
    const s = document.createElement("small");
    s.textContent = a.status === "working" ? "working…" : a.status === "off" ? "switched off" : a.done_today ? `${a.done_today} done today` : "ready";
    t.append(b, s); li.appendChild(t);
    li.onclick = () => { $('[data-tab="chat"]').click(); selectChannel(a.name); };
    ul.appendChild(li);
  });
}

function renderChannels() {
  const nav = $("#channels"); nav.innerHTML = "";
  const mk = (id, label, icon, color) => {
    const b = document.createElement("button"); b.className = "chan"; b.dataset.chan = id; b.title = label;
    b.style.setProperty("--c", color);
    if (icon) b.appendChild(icon); else { const h = document.createElement("span"); h.className = "avatar hash"; h.textContent = "#"; b.appendChild(h); }
    const l = document.createElement("small"); l.textContent = label; b.appendChild(l);
    b.onclick = () => selectChannel(id);
    nav.appendChild(b);
  };
  mk("jarvis", "Jarvis", avatar("jarvis"), agentOf("jarvis").color);
  mk("team", "team", null, "#8fa7c4");
  const sep = document.createElement("i"); sep.className = "sep"; nav.appendChild(sep);
  Object.values(TEAM).filter((a) => a.name !== "jarvis").forEach((a) => mk(a.name, a.title, avatar(a.name), a.color));
  selectChannel(channel);
}

function renderChannelHead() {
  const head = $("#channel-head"); head.innerHTML = "";
  if (channel === "team") {
    head.innerHTML = "<div><b># team</b><small>Who did what: handoffs between agents and their work, as it happens.</small></div>";
    return;
  }
  const a = agentOf(channel);
  head.style.setProperty("--c", a.color);
  const info = document.createElement("div");
  const b = document.createElement("b"); b.textContent = a.title;
  const s = document.createElement("small");
  s.textContent = channel === "jarvis" ? "Leads the team. Ask anything; he passes work to the right specialist."
    : `${a.job} ${a.used_today != null ? "· " + a.used_today + " AI requests today" : ""}`;
  info.append(b, s);
  head.append(avatar(channel), info);
  if (channel !== "jarvis") {
    const sw = document.createElement("label"); sw.className = "switch"; sw.title = "Switch this agent on or off";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = a.enabled !== false;
    cb.onchange = async () => { (await api.set_agent(channel, cb.checked)).forEach((x) => { TEAM[x.name] = x; }); renderRoster(Object.values(TEAM)); renderChannelHead(); };
    sw.append(cb, document.createElement("i")); head.appendChild(sw);
  }
}

async function selectChannel(id) {
  channel = id;
  $$("#channels .chan").forEach((b) => { b.classList.toggle("active", b.dataset.chan === id); if (b.dataset.chan === id) b.classList.remove("unread"); });
  renderChannelHead();
  const chat = $("#chat"); chat.innerHTML = "";
  $("#ask-input").placeholder = id === "jarvis" || id === "team" ? "Ask Jarvis anything…  (Esc stops him)" : `Message ${agentOf(id).title} directly…`;
  if (id === "team") {
    (await api.team_feed()).forEach(addFeedItem);
  } else {
    (await api.chat_history(id)).forEach(addMessage);
  }
  $("#channel-body").scrollTop = 1e9;
}

function onMessage(m) {
  const ch = m.channel || "jarvis";
  if (channel === ch) addMessage(m);
  else if (channel === "team" && m.role === "assistant" && m.agent && m.agent !== "jarvis") {
    addFeedItem({ ts: Date.now() / 1000, kind: "agent", from: m.agent, text: m.text });
  } else if (m.role === "assistant") {
    const b = $(`#channels .chan[data-chan="${ch}"]`); if (b) b.classList.add("unread");
  }
  if (m.role === "assistant" && m.agent) loadTeam();
}

function onHandoff(h) {
  if (channel === "team") addFeedItem({ ts: Date.now() / 1000, kind: "handoff", from: h.from, to: h.to, text: h.what, status: h.status });
  if (TEAM[h.to]) { TEAM[h.to].status = h.status === "working" ? "working" : "idle"; renderRoster(Object.values(TEAM)); }
  if (h.status === "working") $("#st-activity").textContent = `${agentOf(h.to).title} is working`;
}

function addFeedItem(f) {
  const el = document.createElement("div"); el.className = "feed " + f.kind;
  const from = f.from === "you" ? { title: "You", color: "#e8e8e8" } : agentOf(f.from);
  el.style.setProperty("--c", from.color);
  el.appendChild(f.from === "you" ? Object.assign(document.createElement("span"), { className: "avatar", textContent: "Y" }) : avatar(f.from));
  const body = document.createElement("div");
  const who = document.createElement("b"); who.textContent = from.title;
  if (f.kind === "handoff") {
    const to = agentOf(f.to), arrow = document.createElement("span"); arrow.className = "to"; arrow.style.setProperty("--c", to.color);
    arrow.textContent = " → " + to.title;
    who.appendChild(arrow);
  }
  const t = document.createElement("time"); t.textContent = fmtTime(f.ts);
  const p = document.createElement("p");
  p.textContent = f.kind === "quick" ? `Handled “${f.text}” (no AI needed)` : f.text;  // quick: the text is your request
  if (f.status && f.status !== "open") { const s = document.createElement("em"); s.className = "status " + f.status; s.textContent = f.status; who.appendChild(s); }
  body.append(who, t, p);
  if (f.result) { const r = document.createElement("small"); r.textContent = "Result: " + f.result; body.appendChild(r); }
  el.appendChild(body);
  $("#chat").appendChild(el);
  $("#channel-body").scrollTop = 1e9;
}

function addMessage(m) {
  const el = document.createElement("div");
  el.className = "msg " + m.role;
  if (m.role === "assistant") {
    const a = agentOf(m.agent || "jarvis");
    el.style.setProperty("--c", a.color);
    const who = document.createElement("div"); who.className = "who";
    who.append(avatar(m.agent || "jarvis", "xs"), document.createTextNode(a.title));
    el.appendChild(who);
  }
  el.appendChild(document.createTextNode(m.text));
  if (m.sources && m.sources.length) {
    const src = document.createElement("div");
    src.className = "src";
    m.sources.forEach((s, i) => {
      const a = document.createElement("a");
      a.href = "#"; a.textContent = `[${i + 1}] ${s.title || s.url}`; a.title = s.url;
      a.onclick = (e) => { e.preventDefault(); api.open_link(s.url); };
      src.appendChild(a);
    });
    el.appendChild(src);
  }
  const t = document.createElement("time");
  t.textContent = fmtTime(m.ts || Date.now() / 1000);
  el.appendChild(t);
  const chat = $("#chat");
  chat.appendChild(el);
  while (chat.children.length > 200) chat.firstChild.remove();
  $("#channel-body").scrollTop = 1e9;
}

function addActivity(a, append) {
  const li = document.createElement("li");
  li.innerHTML = `<span></span><em></em>`;
  li.children[0].textContent = new Date(a.ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  li.children[1].textContent = a.kind;
  li.appendChild(document.createTextNode(a.text));
  const ul = $("#activity");
  append ? ul.appendChild(li) : ul.prepend(li);
}

// ------------------------------------------------------------ approvals
const FIELD_LABELS = { to: "To", subject: "Subject", body: "Message", text: "Message", channel: "Channel",
  name: "App", start: "Start", end: "End", location: "Location" };
const READONLY = ["replying_to", "windows", "id", "job", "change", "summary", "tests", "full_path"];

function showApproval(p) {
  const card = document.createElement("div");
  card.className = "approval"; card.id = "ap-" + p.id;
  const h = document.createElement("h4"); h.textContent = p.title + ": needs your approval"; card.appendChild(h);
  const inputs = {};
  const fields = Object.entries(p.preview).sort(([a], [b]) => READONLY.includes(b) - READONLY.includes(a));
  for (const [k, v] of fields) {
    if (k === "id") continue;
    const lab = document.createElement("label");
    lab.textContent = FIELD_LABELS[k] || k.replace("_", " ");
    let inp;
    if (READONLY.includes(k)) { inp = document.createElement("div"); inp.textContent = v; inp.style.color = "var(--text)"; }
    else {
      inp = document.createElement(k === "body" || k === "text" ? "textarea" : "input");
      inp.value = v ?? "";
      if (k in p.args) inputs[k] = inp;
    }
    lab.appendChild(inp); card.appendChild(lab);
  }
  const act = document.createElement("div"); act.className = "actions";
  const no = document.createElement("button"); no.textContent = "Cancel"; no.className = "ghost";
  const yes = document.createElement("button"); yes.className = "go";
  yes.textContent = p.tool.startsWith("email") || p.tool === "discord_post" ? "Approve & send" : "Approve";
  no.onclick = () => api.reject(p.id);
  yes.onclick = () => {
    yes.disabled = true; yes.textContent = "Working…";
    const edits = {}; for (const [k, el] of Object.entries(inputs)) edits[k] = el.value;
    api.approve(p.id, edits);
  };
  act.append(no, yes); card.appendChild(act);
  $("#approvals").appendChild(card);
}

function doneApproval(d) { const el = $("#ap-" + d.id); if (el) el.remove(); }

function toast(text) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = text;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), 7000);
}

// ------------------------------------------------------------ settings binding
// A <select> drops a value it has no option for, so add one (e.g. a pasted ElevenLabs voice ID).
function setValue(el, v) {
  if (el.tagName === "SELECT" && v !== "" && ![...el.options].some((o) => o.value === String(v))) {
    const o = document.createElement("option"); o.value = v; o.textContent = `Custom voice (${v})`; el.appendChild(o);
  }
  el.value = v;
}

function bindSettings() {
  $$("[data-set]").forEach((el) => {
    const k = el.dataset.set;
    if (el.type === "checkbox") el.checked = !!S[k]; else setValue(el, S[k] ?? "");
    el.addEventListener("change", async () => {
      let v = el.type === "checkbox" ? el.checked : el.value.trim();
      if (el.type === "range" || el.type === "number") v = parseFloat(v);
      S = await api.save_settings({ [k]: v });
      $$(`[data-set="${k}"]`).forEach((o) => { if (o !== el && o.type !== "checkbox") setValue(o, S[k] ?? ""); });
      applyShow(); refreshChips();
      if (k === "ms_client_id") refreshIntegrations();
    });
  });
  $$("[data-save-secret]").forEach((b) => b.addEventListener("click", async () => {
    const name = b.dataset.saveSecret, inp = $(`[data-secret="${name}"]`);
    const st = await api.set_secret(name, inp.value);
    inp.value = ""; inp.placeholder = st[name] ? "saved securely (paste to replace)" : "paste key, then Save";
    refreshChips(st); refreshIntegrations();
  }));
  applyShow();
}

function applyShow() {
  $$("[data-show]").forEach((el) => { const [k, v] = el.dataset.show.split("="); el.classList.toggle("hidden", S[k] !== v); });
  $("#st-voice").textContent = S.tts_provider === "edge" ? S.edge_voice : S.tts_provider;
}

async function refreshChips(secrets) {
  secrets = secrets || (await api.init()).secrets;
  $("#chip-wake").className = "chip " + (S.wake_word_enabled ? "on" : "off");
  const ai = $("#chip-ai");
  const names = { gemini: "Gemini", anthropic: "Claude", openai: "ChatGPT", openrouter: "OpenRouter", groq: "Groq",
    mistral: "Mistral", deepseek: "DeepSeek", xai: "Grok", ollama: "Ollama", custom: "Custom" };
  const needsKey = !["off", "ollama", "custom"].includes(S.llm_provider);
  if (S.llm_provider === "off") { ai.className = "chip off"; ai.textContent = "AI off"; }
  else if (needsKey && !secrets[S.llm_provider + "_api_key"]) { ai.className = "chip mid"; ai.textContent = `AI: ${names[S.llm_provider] || S.llm_provider}, no key`; }
  else { ai.className = "chip on"; ai.textContent = "AI: " + (names[S.llm_provider] || S.llm_provider); }
  $$("[data-secret]").forEach((i) => { if (secrets[i.dataset.secret]) i.placeholder = "saved securely (paste to replace)"; });
}

async function refreshIntegrations(integ) {
  integ = integ || await api.integrations();
  const rows = [
    ["Outlook.com / To Do", integ.microsoft.connected ? ["ok", "connected"] : integ.microsoft.configured ? ["warn", "not signed in"] : ["muted", "not set up"]],
    ["Classic Outlook", integ.outlook_classic.connected ? ["ok", "enabled"] : integ.outlook_classic.available ? ["muted", "off"] : ["muted", "not installed"]],
    ["Discord bot", integ.discord.connected ? ["ok", `${integ.discord.channels.length} channels`] : ["muted", "not connected"]],
    ["Gmail / Google", integ.google.connected ? ["ok", "connected"] : integ.google.configured ? ["warn", "not signed in"] : ["muted", "not set up"]],
    ["Google Classroom", integ.classroom.connected ? ["ok", "connected"] : ["muted", "not connected"]],
    ["GitHub", integ.github.connected ? ["ok", "connected"] : ["muted", "not connected"]],
    ["Notion", integ.notion.connected ? ["ok", "connected"] : ["muted", "not connected"]],
    ["Slack", integ.slack.connected ? ["ok", "connected"] : ["muted", "not connected"]],
    ["Telegram", integ.telegram.connected ? ["ok", "connected"] : ["muted", "not connected"]],
    ["Smart home", integ.home.connected ? ["ok", "connected"] : ["muted", "not connected"]],
    ["Games", integ.games.count ? ["ok", `${integ.games.count} installed`] : ["muted", "none found"]],
    ["YouTube Music", ["ok", "browser"]],
    ["Phone", !integ.phone.installed ? ["muted", "no KDE Connect"] : !integ.phone.devices.length ? ["warn", "not paired"]
      : integ.phone.devices.some((d) => d.reachable) ? ["ok", integ.phone.devices[0].name] : ["warn", "not reachable"]],
    ["WhatsApp", integ.whatsapp.connected ? ["ok", S.confirm_sends ? "drafts" : "sends"] : ["muted", "off"]],
    ["Spotify", ["ok", "desktop app"]],
    ["Weather", ["ok", "Open-Meteo"]],
    ["Web search", ["ok", "DuckDuckGo"]],
    ["ElevenLabs", integ.elevenlabs.key ? ["ok", "key saved"] : ["muted", "no key"]],
  ];
  $("#integrations").innerHTML = "";
  for (const [name, [cls, txt]] of rows) {
    const li = document.createElement("li");
    li.innerHTML = `<span></span><b></b>`; li.children[0].textContent = name;
    li.children[1].textContent = txt; li.children[1].className = cls;
    $("#integrations").appendChild(li);
  }
  $("#ms-status").textContent = integ.microsoft.connected ? "Signed in" : "Not signed in";
  $("#classic-toggle").checked = integ.outlook_classic.connected;
  $("#classic-toggle").disabled = !integ.outlook_classic.available;
  if (!integ.outlook_classic.available) $("#classic-status").textContent = "Classic Outlook isn't installed.";
  $("#discord-status").textContent = integ.discord.connected ? "Connected" : "Not connected";
  $("#google-status").textContent = integ.google.connected ? "Signed in" : integ.google.configured ? "Not signed in" : "Add your OAuth client ID and secret first";
  $("#github-status").textContent = integ.github.connected ? "Connected" : "Not connected";
  $("#classroom-status").textContent = integ.classroom.connected ? "Connected" : "Not connected";
  renderDiscordChannels(null, integ.discord.channels);
  $$("[data-service]").forEach((card) => {
    card.querySelector("[data-status]").textContent = integ[card.dataset.service].connected ? "Connected" : "Not connected";
  });
  const url = $('[data-service="home"] [data-url]'); if (url && !url.value) url.value = S.home_url || "";
  $("#games-status").textContent = integ.games.count ? `${integ.games.count} games found in Steam and Epic.` : "No Steam or Epic games found.";
  $("#overlay-toggle").checked = integ.overlay.on;
  $("#autostart-toggle").checked = integ.autostart.on;
  const ph = integ.phone;
  $("#phone-status").textContent = !ph.installed ? "KDE Connect isn't installed on this laptop."
    : !ph.devices.length ? "No phone paired in KDE Connect yet."
    : ph.devices.map((d) => `${d.name}: ${d.reachable ? "connected" : "not reachable"}`).join(", ");
  setGame(integ.game_mode.on);
  wakePhrase = integ.wake.phrase; $("#st-wake").textContent = `"${wakePhrase}"`;
  const builtIn = ["hey_jarvis", "alexa", "hey_mycroft", "hey_rhasspy"].includes(integ.wake.model);
  $("#wake-model").value = builtIn ? integ.wake.model : "custom";
  $("#wake-custom").classList.toggle("hidden", builtIn);
  if (!builtIn) { $("#wake-path").value = integ.wake.model; $("#wake-label").value = S.wake_phrase_label || ""; }
}

function renderDiscordChannels(all, chosen) {
  const box = $("#discord-channels");
  if (!all) {
    box.innerHTML = chosen.length ? "<p class='muted'>Selected: " + chosen.map((c) => "#" + c.name).join(", ").replace(/</g, "") + "</p>" : "";
    return;
  }
  box.innerHTML = "<p class='muted'>Choose which channels Jarvis may read:</p>";
  const ids = new Set(chosen.map((c) => c.id));
  all.forEach((c) => {
    const lab = document.createElement("label"); lab.className = "check";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = ids.has(c.id);
    cb.onchange = () => {
      const sel = all.filter((x, i) => box.querySelectorAll("input")[i].checked).map((x) => ({ id: x.id, name: x.name }));
      api.discord_set_channels(sel).then(() => refreshIntegrations());
    };
    lab.append(cb, document.createTextNode(` ${c.guild} › #${c.name}`));
    box.appendChild(lab);
  });
}

function renderMemories(list) {
  const ul = $("#memories"); ul.innerHTML = "";
  if (!list.length) { ul.innerHTML = "<li class='muted'>Nothing remembered yet. Say “remember that…”.</li>"; return; }
  list.forEach((m) => {
    const li = document.createElement("li"); li.textContent = m.text;
    const b = document.createElement("button"); b.className = "small ghost"; b.textContent = "Forget";
    b.onclick = async () => renderMemories(await api.forget(m.id));
    li.appendChild(b); ul.appendChild(li);
  });
}

function renderTasks(list) {
  const ul = $("#tasks"); ul.innerHTML = "";
  if (!list.length) { ul.innerHTML = "<li class='muted'>Nothing on your list. New assignments from school appear here by themselves.</li>"; return; }
  list.forEach((t) => {
    const li = document.createElement("li");
    li.className = t.due_text.startsWith("overdue") || t.due_text === "today" ? "urgent" : t.due_text === "tomorrow" ? "soon" : "";
    const main = document.createElement("div");
    const title = document.createElement("b"); title.textContent = t.title;
    const meta = document.createElement("small");
    meta.textContent = `${t.due ? "due " + t.due_text : "no due date"} · ${t.kind}${t.source !== "you" ? " · from " + t.source : ""}`;
    main.append(title, meta);
    if (t.details) { main.title = t.details; }
    const done = document.createElement("button"); done.className = "small"; done.textContent = "Done";
    done.onclick = async () => renderTasks(await api.complete_task(t.id));
    const drop = document.createElement("button"); drop.className = "small ghost"; drop.textContent = "Dismiss";
    drop.onclick = async () => renderTasks(await api.dismiss_task(t.id));
    const btns = document.createElement("span");
    if (!t.result_path && ["presentation", "document", "notes", "revision", "spreadsheet", "reading", "other"].includes(t.kind)) {
      const prep = document.createElement("button"); prep.className = "small ghost"; prep.textContent = "Prepare";
      prep.title = "Have Jarvis prepare a draft of this";
      prep.onclick = async () => { toast(await api.prepare_task(t.id)); loadJobs(); };
      btns.append(prep);
    }
    btns.append(done, drop);
    li.append(main, btns); ul.appendChild(li);
  });
}

function when(ts) {
  if (!ts) return "never";
  const d = new Date(ts * 1000), mins = Math.round((d - Date.now()) / 60000);
  if (Math.abs(mins) < 1) return "now";
  if (Math.abs(mins) < 90) return mins < 0 ? `${-mins} min ago` : `in ${mins} min`;
  return d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

// ------------------------------------------------------------ Today view
function li(text, cls, extra) {
  const el = document.createElement("li"); el.textContent = text; if (cls) el.className = cls;
  if (extra) el.appendChild(extra);
  return el;
}

function fill(sel, rows, emptyText) {
  const ul = $(sel); ul.innerHTML = "";
  if (!rows.length) { ul.appendChild(li(emptyText, "muted")); return; }
  rows.forEach((r) => ul.appendChild(r));
}

function renderToday(d) {
  const b = d.briefing, s = b.sections;
  $("#td-brief").textContent = b.spoken;
  $("#td-since").textContent = "Since " + new Date(b.since * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  const t = s.tasks, dueCls = (x) => x.due.startsWith("overdue") || x.due === "today" ? "urgent" : x.due === "tomorrow" ? "soon" : "";
  fill("#td-tasks", [
    ...t.overdue.map((x) => li(`${x.title}: ${x.due}`, "urgent")),
    ...t.new.map((x) => li(`New: ${x.title}, due ${x.due}`, dueCls(x))),
    ...t.top.filter((x) => !t.new.some((n) => n.id === x.id) && !t.overdue.some((o) => o.id === x.id)).slice(0, 4)
      .map((x) => li(`${x.title}, due ${x.due}`, dueCls(x))),
    ...(t.done.length ? [li(`Done since then: ${t.done.join(", ")}`, "muted")] : []),
  ], "No open tasks.");
  const m = s.messages;
  fill("#td-messages", [
    li(`${m.emails} emails, ${m.messages} messages, ${m.school} from school`, "muted"),
    ...m.important.map((x) => li(`${x.summary} (${x.from})`, "soon")),
    ...m.needs_reply.map((x) => li(`Needs a reply: ${x.summary} (${x.from})`)),
    ...m.announcements.map((x) => li(`Announcement: ${x}`)),
  ], "");
  const a = s.agent;
  const files = a.files.map((f) => {
    const btn = document.createElement("button"); btn.className = "small ghost"; btn.textContent = "Open";
    btn.onclick = async () => toast(await api.open_result(f.id));
    return li(`Prepared ${f.title}`, "", btn);
  });
  fill("#td-agent", [
    li(`${a.checks} checks, ${a.analysed} school items understood`, "muted"),
    ...files,
    ...(a.approvals ? [li(`${a.approvals} waiting for your approval (cards in the middle)`, "soon")] : []),
    ...a.failed.map((x) => li(`Couldn't finish: ${x}`, "urgent")),
    ...(a.waiting ? [li(`${a.waiting} waiting for AI budget`, "muted")] : []),
    ...a.problems.map((x) => li(x, "muted")),
  ], "");
  const sc = s.schedule;
  fill("#td-schedule", [
    ...sc.today.map((e) => li(`Today ${e.time}: ${e.subject}`)),
    ...sc.tomorrow.map((e) => li(`Tomorrow ${e.time}: ${e.subject}`, "muted")),
    ...sc.due_tomorrow.map((x) => li(`Due tomorrow: ${x}`, "soon")),
    ...(sc.calendar_error ? [li("Calendar: " + sc.calendar_error, "muted")] : []),
  ], "Nothing on your calendar today or tomorrow.");
  const st = d.status, ph = d.phone;
  fill("#td-devices", [
    li(`${st.name}: ${st.battery ? st.battery.percent + "%" + (st.battery.plugged ? " charging" : "") : "mains"}, ` +
       `CPU ${Math.round(st.cpu)}%, ${st.keep_awake ? "kept awake" : "normal sleep"}${st.game_mode ? ", game mode" : ""}`),
    ...(ph.devices || []).map((x) => li(`${x.name}: ${x.reachable ? "connected" : "not reachable"}`, x.reachable ? "" : "muted")),
    ...(!ph.installed ? [li("Phone: KDE Connect not installed", "muted")] : []),
  ], "");
  fill("#td-activity", d.activity.slice(0, 8).map((x) => li(`${fmtTime(x.ts)} ${x.text.slice(0, 140)}`, "muted")), "Nothing yet.");
}

async function loadToday() { try { renderToday(await api.today()); } catch (e) { $("#td-brief").textContent = "Couldn't load: " + e.message; } }

const JOB_STATE = { done: "ready", running: "working on it", queued: "queued", waiting: "waiting for AI budget", failed: "couldn't finish" };

async function loadJobs() {
  const list = await api.jobs(), ul = $("#jobs"); ul.innerHTML = "";
  if (!list.length) { ul.innerHTML = "<li class='muted'>Nothing yet. Try saying “make a 10-slide presentation about renewable energy”.</li>"; return; }
  list.slice(0, 10).forEach((j) => {
    const li = document.createElement("li"); li.className = j.state === "failed" ? "urgent" : j.state === "done" ? "" : "soon";
    const main = document.createElement("div");
    const b = document.createElement("b"); b.textContent = j.title;
    const s = document.createElement("small");
    s.textContent = `${j.kind} · ${JOB_STATE[j.state] || j.state}${j.state === "running" && j.step ? " (" + j.step + ")" : ""}${j.error ? " · " + j.error : ""}`;
    main.append(b, s);
    if (j.review && j.review.length) main.title = "Jarvis's own check noted: " + j.review.join(" ");
    const btns = document.createElement("span");
    if (j.state === "done") {
      const o = document.createElement("button"); o.className = "small"; o.textContent = "Open";
      o.onclick = async () => toast(await api.open_result(j.id)); btns.append(o);
    }
    li.append(main, btns); ul.appendChild(li);
  });
}

async function loadAgent() {
  renderTasks(await api.tasks());
  loadJobs();
  const s = await api.agent_status();
  $("#ag-last").textContent = s.running ? "checking now…" : when(s.last_run);
  $("#ag-next").textContent = s.enabled ? when(s.next_run) : "off";
  $("#ag-usage").textContent = `${s.usage.total} of about ${s.usage.limit} (agent ${s.usage.agent} of ${s.usage.agent_budget})${s.usage.exhausted ? ", daily limit reached" : ""}`;
  $("#ag-summary").textContent = s.summary;
  $("#ag-problems").textContent = (s.problems || []).join(" ");
}

async function renderBuilder() {
  const { status: s, changes } = await api.builder_info();
  $("#builder-status").textContent = !s.installed ? "Claude Code isn't installed on this laptop."
    : !s.signed_in ? "Claude Code isn't signed in. Run 'claude' in a terminal and sign in with your personal account."
    : s.personal === false && !s.confirmed ? "⚠ Claude Code is signed in with a company or school account, so Builder won't use it. Sign in with your own account (run 'claude', then /login)."
    : !s.enabled ? "Ready, but switched off below." : "Ready.";
  const names = { ready: "waiting for you", applied: "applied", undone: "undone", discarded: "discarded", failed: "failed", running: "working", queued: "queued", done: "no changes" };
  fill("#builder-changes", changes.map((c) => li(`${c.title}: ${names[c.state] || c.state}${c.stat ? " · " + c.stat : ""}${c.tests_passed === false ? " · tests failed" : ""}`,
    c.state === "failed" ? "urgent" : c.state === "ready" ? "soon" : "")), "No changes yet.");
}

async function renderDevices() {
  const list = await api.devices(), ul = $("#devices"); ul.innerHTML = "";
  list.forEach((d) => {
    const li = document.createElement("li");
    li.textContent = `${d.name} · last used ${new Date(d.last_seen * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`;
    const b = document.createElement("button"); b.className = "small ghost"; b.textContent = "Remove";
    b.onclick = async () => { await api.remove_device(d.id); renderDevices(); };
    li.appendChild(b); ul.appendChild(li);
  });
}

async function renderRemote() {
  const r = await api.remote_status();
  $("#remote-status").textContent = !r.installed ? "Tailscale not installed" : !r.running ? "Tailscale installed, not signed in"
    : `Reachable at https://${r.host}`;
  renderDevices();
}

function renderRoutines(book) {
  const ul = $("#routines"); ul.innerHTML = "";
  if (!Object.keys(book).length) { ul.innerHTML = "<li class='muted'>No routines yet. Say “when I say focus mode, close Discord and open Notepad”.</li>"; return; }
  for (const [name, steps] of Object.entries(book)) {
    const li = document.createElement("li"); li.textContent = `“${name}”: ${steps.join(", then ")}`;
    const b = document.createElement("button"); b.className = "small ghost"; b.textContent = "Delete";
    b.onclick = async () => renderRoutines(await api.delete_routine(name));
    li.appendChild(b); ul.appendChild(li);
  }
}

// ------------------------------------------------------------ UI wiring
function wire() {
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    const tab = b.dataset.tab;
    $$(".tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === tab));
    $$(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== "tab-" + tab));
    if (tab === "activity") loadActivity();
    if (tab === "tasks") loadAgent();
    if (tab === "today") loadToday();
    if (tab === "settings") { api.routines().then(renderRoutines); renderRemote(); renderBuilder(); }
  }));
  $("#btn-mic").onclick = async () => setMic(await api.set_mic(!micOn));
  $("#btn-talk").onclick = async () => { const r = await api.push_to_talk(); if (r !== "ok") toast(r); };
  $("#btn-stop").onclick = () => api.stop();
  $("#ask").onsubmit = (e) => {
    e.preventDefault();
    const v = $("#ask-input").value.trim(); if (!v) return;
    $("#ask-input").value = "";
    if (TEAM[channel] && channel !== "jarvis") { api.ask_agent(channel, v); return; }  // a direct chat with one agent
    if (channel !== "jarvis") selectChannel("jarvis");  // from #team: the answer shows in Jarvis's chat
    api.send_text(v);
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") api.stop();
    if (e.ctrlKey && e.code === "Space") { e.preventDefault(); $("#btn-talk").click(); }
  });
  $("#test-voice").onclick = () => api.test_voice();
  $("#refresh-activity").onclick = loadActivity;
  $("#clear-history").onclick = async () => {
    if (!confirm("Delete all conversation history? Remembered facts are kept.")) return;
    await api.clear_history(); $("#chat").innerHTML = "";
  };
  $("#el-load").onclick = async () => {
    $("#el-usage").textContent = "Loading…";
    const r = await api.elevenlabs_info();
    if (!r.ok) { $("#el-usage").textContent = "Error: " + r.error; return; }
    const u = r.usage; $("#el-usage").textContent = `Plan: ${u.tier}. Used ${u.used.toLocaleString()} of ${u.limit.toLocaleString()} characters this month.`;
    const sel = $("#el-voices"); sel.innerHTML = "";
    r.voices.forEach((v) => { const o = document.createElement("option"); o.value = v.id;
      o.textContent = v.name + (v.labels.accent ? ` (${v.labels.accent}${v.labels.age ? ", " + v.labels.age : ""})` : ""); sel.appendChild(o); });
    setValue(sel, S.elevenlabs_voice_id || "");
  };
  // Shows progress in a status line and always ends with a result, even if the request itself fails.
  const connectFlow = async (status, waiting, call, done) => {
    const el = $(status); el.textContent = waiting;
    let r = null, text;
    try {
      r = await call();
      text = r.ok ? done(r) : "Error: " + r.error;
    } catch (e) {
      text = "Error: " + (e.message || e);
    }
    try { await refreshIntegrations(); } catch {}
    el.textContent = text;  // after the refresh, which would otherwise overwrite it
    return r;
  };
  $("#ms-connect").onclick = () => connectFlow("#ms-status", "Complete sign-in in your browser…", () => api.ms_connect(), () => "Signed in");
  $("#ms-disconnect").onclick = async () => refreshIntegrations(await api.ms_disconnect());
  $("#google-connect").onclick = () => connectFlow("#google-status", "Complete sign-in in your browser…",
    () => api.google_connect(), (r) => "Signed in as " + r.account);
  $("#google-disconnect").onclick = async () => refreshIntegrations(await api.google_disconnect());
  $("#github-connect").onclick = async () => {
    const r = await connectFlow("#github-status", "Connecting…", () => api.github_connect($("#github-token").value || null),
      (r) => "Connected as " + r.user);
    if (r && r.ok) $("#github-token").value = "";
  };
  $("#github-disconnect").onclick = async () => refreshIntegrations(await api.github_disconnect());
  $("#classic-toggle").onchange = async (e) => {
    const r = await api.classic_outlook(e.target.checked);
    $("#classic-status").textContent = r.ok ? (r.accounts ? "Accounts: " + r.accounts.join(", ") : "Disabled") : "Error: " + r.error;
    refreshIntegrations();
  };
  $("#discord-connect").onclick = async () => {
    const r = await connectFlow("#discord-status", "Connecting…", () => api.discord_connect($("#discord-token").value || null),
      (r) => `Connected as ${r.bot}`);
    if (!r || !r.ok) return;
    $("#discord-token").value = "";
    renderDiscordChannels(r.channels, S.discord_channels || []);
  };
  $("#discord-disconnect").onclick = async () => refreshIntegrations(await api.discord_disconnect());
  // Notion, Slack, Telegram, Home Assistant: same token flow, one handler
  $$("[data-service]").forEach((card) => {
    const name = card.dataset.service, tok = card.querySelector("[data-token]"), url = card.querySelector("[data-url]");
    const status = `[data-service="${name}"] [data-status]`;
    card.querySelector("[data-connect]").onclick = async () => {
      const r = await connectFlow(status, "Connecting…", () => api.connect_service(name, tok.value || null, url ? url.value : null),
        (r) => "Connected: " + r.who);
      if (r && r.ok) tok.value = "";
    };
    card.querySelector("[data-disconnect]").onclick = async () => refreshIntegrations(await api.disconnect_service(name));
  });
  $("#brief-me").onclick = async () => { $("#td-brief").textContent = await api.brief_me(); loadToday(); };
  $$("[data-quick]").forEach((b) => b.onclick = async () => {
    const q = b.dataset.quick;
    if (q === "ring") toast(await api.phone_ring());
    if (q === "game") { toast(await api.game_mode(!window.gameMode)); refreshIntegrations(); }
    if (q === "check") toast(await api.agent_run_now());
    if (q === "tasks") $('[data-tab="tasks"]').click();
  });
  $("#agent-run").onclick = async () => {
    toast(await api.agent_run_now());
    $("#ag-last").textContent = "checking now…";
    const poll = setInterval(async () => { const s = await api.agent_status(); if (!s.running) { clearInterval(poll); loadAgent(); } }, 3000);
  };
  $("#task-add").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api.add_task($("#task-title").value, $("#task-due").value);
    if (!r.ok) { toast(r.error); return; }
    $("#task-title").value = ""; $("#task-due").value = ""; renderTasks(r.tasks);
  };
  $("#classroom-connect").onclick = () => connectFlow("#classroom-status", "Complete sign-in in your browser with your school account…",
    () => api.classroom_connect(), (r) => `Signed in as ${r.account}: ${r.classes} classes found`);
  $("#classroom-disconnect").onclick = async () => refreshIntegrations(await api.classroom_disconnect());
  $("#phone-ring").onclick = async () => { $("#phone-out").textContent = await api.phone_ring(); };
  $("#phone-notes").onclick = async () => { $("#phone-out").textContent = "Checking…"; $("#phone-out").textContent = await api.phone_notifications(); };
  $("#phone-yt").onclick = async () => { $("#phone-out").textContent = await api.phone_open("youtube"); };
  $("#autostart-toggle").onchange = async (e) => { e.target.checked = await api.set_autostart(e.target.checked); };
  $("#pair-start").onclick = async () => {
    const r = await api.pair_start();
    $("#pair-box").classList.remove("hidden");
    $("#pair-code-show").textContent = r.code;
    $("#pair-qr").innerHTML = r.qr || "";  // SVG made locally by Jarvis from its own address
    $("#pair-info").textContent = r.url ? `On your phone, open ${r.url} and enter the code (or scan the QR code).`
      : "Set up Tailscale first so your phone can reach this laptop. You can still test pairing at http://127.0.0.1:8765/m here.";
    clearTimeout(window.pairTimer);
    window.pairTimer = setTimeout(() => $("#pair-box").classList.add("hidden"), 5 * 60 * 1000);
  };
  $("#chip-game").onclick = async () => { toast(await api.game_mode(!window.gameMode)); refreshIntegrations(); };
  $("#overlay-toggle").onchange = async (e) => { e.target.checked = await api.set_overlay(e.target.checked); };
  $("#wake-model").onchange = (e) => $("#wake-custom").classList.toggle("hidden", e.target.value !== "custom");
  $("#wake-apply").onclick = async () => {
    const custom = $("#wake-model").value === "custom";
    $("#wake-status").textContent = "Loading…";
    const r = await api.set_wake_model(custom ? $("#wake-path").value : $("#wake-model").value, custom ? $("#wake-label").value : "");
    $("#wake-status").textContent = r.ok ? `Now listening for "${r.phrase}".` : "Error: " + r.error;
    if (r.ok) refreshIntegrations();
  };
  $("#wa-add").onclick = async () => {
    const r = await api.whatsapp_save_contact($("#wa-name").value, $("#wa-phone").value);
    if (!r.ok) { toast(r.error); return; }
    $("#wa-name").value = ""; $("#wa-phone").value = "";
    renderContacts(r.contacts);
  };
}

function renderContacts(book) {
  const ul = $("#wa-contacts"); ul.innerHTML = "";
  for (const [name, phone] of Object.entries(book)) {
    const li = document.createElement("li");
    li.textContent = `${name} · +${phone}`;
    const b = document.createElement("button"); b.className = "small ghost"; b.textContent = "Remove";
    b.onclick = async () => renderContacts(await api.whatsapp_remove_contact(name));
    li.appendChild(b); ul.appendChild(li);
  }
}

async function loadActivity() {
  const list = await api.activity(); $("#activity").innerHTML = "";
  list.forEach((a) => addActivity(a, true));
}

// The core: 3D when the machine can (and low-power mode is off), the 2D orb otherwise.
let coreStarted = false;
function startCore() {
  if (coreStarted || !api) return;  // needs the settings first
  if (!S.ui_low_power) {
    if (!window.startCore3D && !window.core3dFailed) return;  // the 3D module is still loading
    if (window.startCore3D) {
      try {
        if (window.startCore3D($("#core-host"))) { coreStarted = true; $("#orb").classList.add("hidden"); return; }
      } catch (e) { console.warn("3D core unavailable", e); }
    }
  }
  coreStarted = true;  // low-power mode, no WebGL, or the module failed: the 2D orb
  startOrb($("#orb"));
}
window.addEventListener("core3d-ready", startCore);
setTimeout(() => { if (!coreStarted) { window.core3dFailed = true; startCore(); } }, 4000);  // module didn't load: 2D

// Boot sequence: a short "systems coming online" screen while the dashboard loads.
(() => {
  const lines = ["Initialising core", "Loading voice and wake word", "Connecting the team: Scholar, Forge, Herald, Operator, Scout",
    "Checking integrations", "All systems online"];
  let i = 0;
  const tick = setInterval(() => {
    if (i < lines.length) { const d = document.createElement("div"); d.textContent = "› " + lines[i++]; $("#boot-lines").appendChild(d); }
    else { clearInterval(tick); }
  }, 260);
  window.endBoot = () => setTimeout(() => $("#boot").classList.add("done"), Math.max(0, 1500 - performance.now()));
})();

setInterval(() => { $("#clock").textContent = new Date().toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }); }, 1000);
window.addEventListener("online", () => { $("#chip-net").className = "chip on"; $("#chip-net").textContent = "Online"; });
window.addEventListener("offline", () => { $("#chip-net").className = "chip off"; $("#chip-net").textContent = "Offline"; });

// ------------------------------------------------------------ boot
let booted = false;
window.addEventListener("pywebviewready", async () => {
  // The dashboard is served by the background core; web-bridge.js provides window.jarvisApi. In the desktop
  // window pywebview also announces itself, so only start once and keep using Jarvis's own API.
  if (booted) return;
  booted = true;
  api = window.jarvisApi || window.pywebview.api;
  const init = await api.init();
  S = init.settings;
  const ev = $("#edge-voices");
  (await api.edge_voices()).forEach((v) => { const o = document.createElement("option"); o.value = o.textContent = v; ev.appendChild(o); });
  bindSettings(); wire();
  setMic(init.mic); setState(init.state);
  $("#chip-net").className = "chip " + (navigator.onLine ? "on" : "off");
  $("#chip-wake").className = "chip " + (S.wake_word_enabled ? "on" : "off");
  if (init.ready.stt) $("#st-stt").textContent = `ready (${S.stt_model})`;
  init.history.forEach(addMessage);
  await loadTeam();
  renderChannels();
  startCore();
  window.endBoot();
  setInterval(() => { if (!document.hidden) loadTeam(); }, 15000);
  init.pending.forEach(showApproval);
  renderMemories(init.memories);
  renderContacts(await api.whatsapp_contacts());
  renderRoutines(await api.routines());
  refreshChips(init.secrets); refreshIntegrations(init.integrations);
  loadToday();
  setInterval(() => { if (!document.hidden && !$("#tab-today").classList.contains("hidden")) loadToday(); }, 60000);
});
