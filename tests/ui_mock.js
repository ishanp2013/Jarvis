// Dev-only stand-in for the Python bridge, so the dashboard can be checked in a normal browser.
(() => {
  let S = { wake_word_enabled: true, wake_threshold: 0.5, follow_up_seconds: 6, stt_model: "base.en", tts_provider: "edge",
    edge_voice: "en-GB-RyanNeural", edge_rate: "-5%", edge_pitch: "-8Hz", llm_provider: "gemini", gemini_model: "gemini-2.5-flash-lite",
    tts_volume: 1, elevenlabs_stability: 0.55, elevenlabs_similarity: 0.75, elevenlabs_style: 0.1, discord_channels: [], whatsapp_enabled: true,
    browser_path: "C:\\...\\Opera GX\\opera.exe", ollama_model: "qwen2.5:3b", ollama_url: "http://127.0.0.1:11434" };
  const integ = { microsoft: { configured: false, connected: false }, outlook_classic: { available: true, connected: false },
    discord: { token: false, connected: false, channels: [] }, whatsapp: { connected: true }, gemini: { key: false }, elevenlabs: { key: false } };
  const api = {
    init: async () => ({ settings: S, secrets: { gemini_api_key: false, elevenlabs_api_key: false, discord_bot_token: false },
      state: "idle", ready: { wake: true, stt: true }, mic: true, history: [
        { role: "user", text: "What's running on my computer?", ts: Date.now() / 1000 - 60 },
        { role: "assistant", text: "You have 6 apps open: opera, discord, spotify, whatsapp, olk, explorer.", ts: Date.now() / 1000 - 58 },
        { role: "assistant", text: "Here's what I found.", sources: [{ title: "Example source", url: "https://example.com" }], ts: Date.now() / 1000 }],
      memories: [{ id: 1, text: "my exam is on Friday" }], activity: [], pending: [], integrations: integ }),
    integrations: async () => integ, save_settings: async (v) => (S = { ...S, ...v }), set_secret: async () => ({}),
    edge_voices: async () => ["en-GB-RyanNeural", "en-GB-ThomasNeural"], activity: async () => [{ ts: Date.now() / 1000, kind: "tool", text: "open_app {\"name\": \"discord\"}" }],
    send_text: async (t) => { onJarvis("message", { role: "user", text: t }); onJarvis("state", { state: "thinking" });
      setTimeout(() => { onJarvis("message", { role: "assistant", text: "Mock reply." }); onJarvis("state", { state: "speaking" }); }, 600);
      setTimeout(() => onJarvis("state", { state: "idle" }), 2500); },
    push_to_talk: async () => { onJarvis("state", { state: "listening" }); return "ok"; }, stop: async () => onJarvis("state", { state: "idle" }),
    set_mic: async (on) => on, approve: async (id) => onJarvis("approval_done", { id }), reject: async (id) => onJarvis("approval_done", { id }),
    test_voice: async () => {}, forget: async () => [], clear_history: async () => {}, open_link: async () => {},
  };
  window.pywebview = { api };
  setTimeout(() => {
    window.dispatchEvent(new Event("pywebviewready"));
    setTimeout(() => {
      onJarvis("system", { cpu: 23, ram: 71, jarvis_cpu: 1.2, jarvis_mb: 310 });
      onJarvis("approval", { id: "a1", tool: "email_reply", title: "Send reply", args: { id: "x", body: "Thanks, I'll be there at 4." },
        preview: { id: "x", body: "Thanks, I'll be there at 4.", replying_to: "Teacher: Project deadline" }, mode: "button" });
    }, 300);
  }, 100);
})();
