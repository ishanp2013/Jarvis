"use strict";
// The floating orb: always on top, animates with Jarvis, click to talk, double-click for the dashboard.
let state = "idle", level = 0, voiceLevel = 0;
const tags = { listening: "listening", thinking: "thinking", transcribing: "…", speaking: "", idle: "" };

window.onJarvis = (kind, d) => {
  if (kind === "state") { state = d.state; document.getElementById("tag").textContent = tags[d.state] ?? ""; }
  if (kind === "level") level = d.rms;
  if (kind === "voice_level") voiceLevel = d.rms;
  if (kind === "game_mode") { window.gameMode = d.on; document.body.classList.toggle("game", d.on);
    document.getElementById("tag").textContent = d.on ? "game mode" : ""; }
};

startOrb(document.getElementById("orb"));

let wired = false;
window.addEventListener("pywebviewready", async () => {
  // In browser mode the page is served by Jarvis and talks through web-bridge.js (window.jarvisApi);
  // pywebview also announces itself, so only wire up once.
  if (wired) return;
  wired = true;
  const api = window.jarvisApi || window.pywebview.api;
  let clickTimer = null;
  document.body.addEventListener("click", () => {  // wait briefly so a double-click doesn't also start listening
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => api.push_to_talk(), 260);
  });
  document.body.addEventListener("dblclick", () => { clearTimeout(clickTimer); api.show_dashboard(); });
  document.body.addEventListener("contextmenu", (e) => { e.preventDefault(); api.stop(); });
  try {
    const init = await api.init();
    state = init.state;
    if (init.integrations.game_mode.on) window.onJarvis("game_mode", { on: true });
  } catch {}
});
