// Browser mode only (python -m jarvis --web): stands in for pywebview's bridge.
// window.pywebview.api.<method>(...args) becomes POST /api/<method>; events arrive over /events.
(() => {
  const call = async (name, args) => {
    const r = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jarvis-Token": window.JARVIS_TOKEN },
      body: JSON.stringify(args),
    });
    const data = await r.json().catch(() => null);
    if (r.status === 403 && data === "bad token") {  // Jarvis was restarted: this page's code is stale
      restarted();
      throw new Error("Jarvis was restarted. Reloading the page, then try again.");
    }
    if (!r.ok) throw new Error(data && data.error ? data.error : "Request failed (" + r.status + ")");
    return data;
  };
  let reloading = false;
  const restarted = () => { if (!reloading) { reloading = true; setTimeout(() => location.reload(), 2500); } };
  window.jarvisApi = new Proxy({}, { get: (_, name) => (...args) => call(name, args) });
  window.pywebview = { api: window.jarvisApi };

  const connect = () => {
    const es = new EventSource("/events?token=" + encodeURIComponent(window.JARVIS_TOKEN));
    es.onmessage = (e) => { const m = JSON.parse(e.data); window.onJarvis && window.onJarvis(m.kind, m.data); };
    es.onerror = () => {
      es.close();
      // If the server came back with a new code, reload; otherwise just reconnect.
      setTimeout(() => fetch("/api/ping", { method: "POST", headers: { "X-Jarvis-Token": window.JARVIS_TOKEN } })
        .then(async (r) => (r.status === 403 && (await r.json().catch(() => null)) === "bad token" ? restarted() : connect()))
        .catch(() => setTimeout(connect, 2000)), 2000);
    };
  };
  window.addEventListener("DOMContentLoaded", () => {
    connect();
    window.dispatchEvent(new Event("pywebviewready"));
  });
})();
