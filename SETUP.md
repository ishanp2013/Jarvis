# Jarvis: setup and connection guide

## 1. Start it

1. Run **`setup.bat`** once. It does three things:
   - creates the Python 3.11 environment in `%LOCALAPPDATA%\JarvisAssistant\venv`;
   - downloads the wake-word and speech models (about 160 MB);
   - optionally makes a desktop shortcut.
2. Run **`Jarvis.bat`**, or use the shortcut.
3. Say **"Hey Jarvis"**. You'll hear a short chime; then give your command. You can also press **Talk** (Ctrl+Space) or type in the box.
4. To interrupt, say "Hey Jarvis" again, press **Stop**, or press **Esc**. **Mic** closes the microphone completely.

Your data is kept in `%LOCALAPPDATA%\JarvisAssistant`:
- settings, conversation history, memory and the activity log;
- `jarvis.log`, which has tokens redacted;
- the Microsoft token, encrypted with Windows DPAPI.

API keys are stored in **Windows Credential Manager**, not in files.

> **Disk space:** this PC had only about 2 GB free while I was building Jarvis. Jarvis itself needs about 1.2 GB (Python environment plus models). Free up space before trying a local Ollama model (1–2 GB each).

## 2. What works where

| Feature | Needs internet | Account/key needed |
|---|---|---|
| Wake word, speech recognition | No (runs locally) | No |
| Open/close/switch apps, YouTube, websites, system info, media keys, lock | No | No |
| Voice: Microsoft neural (default) | Yes | No |
| Voice: Windows offline | No | No |
| Voice: ElevenLabs | Yes | Free ElevenLabs key |
| General questions, research summaries, drafting | Yes (Gemini), or no (Ollama) | Gemini key, or Ollama installed |
| Web search with links | Yes | No (DuckDuckGo) |
| Outlook.com mail, calendar, To Do | Yes | Free Microsoft app registration (below) |
| Classic Outlook mail and calendar (incl. Gmail over IMAP) | Yes | Already set up in classic Outlook |
| Discord channels | Yes | Your own Discord bot (below) |
| WhatsApp | No | Drafts only (see below) |

These commands work with no AI model at all:
- "open Opera GX", "launch Discord", "open YouTube and search for lofi"
- "switch to Spotify", "close Discord" (asks first)
- "what's running on my computer", "system status", "volume up", "lock my PC"
- "remember that…", "what do you remember"
- "read my emails", "what's on my calendar", "my tasks", "add a task…", "check discord"

## 3. AI model and costs (checked against official docs, 3 Nov 2026)

**Claude Pro (your father's account): can't be used.**
- Pro doesn't include API access.
- Anthropic's terms forbid sharing an account login.
- Using a Claude.ai subscription login to power other apps is not permitted; apps are meant to use API keys.

**Google AI Pro (your father's account): doesn't help.**
- AI Pro benefits apply only in the Gemini apps and the AI Studio web interface. They include no Gemini API quota.
- AI Pro can be shared with up to 5 people through a Google One family group, but that still gives no API access.

**Gemini API free tier: the practical free option, with conditions you must check yourself.**
- You get a free key at <https://aistudio.google.com/apikey>. It needs no billing. Jarvis never creates keys or enables billing.
- The free-tier terms require users to be **18 or over**.
- Apps used in the **UK, EEA or Switzerland** must use the *paid* tier.
- Google may use free-tier content to improve its products, and human reviewers may read it.
- Free-tier limits are shown per project in AI Studio.
- That data use is why **Private mode** is on by default: email, calendar, tasks and Discord content are handled locally and never sent to Gemini.
- If you're under 18 or in the UK/EEA, set the provider to **Ollama** or **Off** instead.

**Other providers (Settings → AI model).** Pick one, paste its key and press Save. Each key is stored in Windows Credential Manager. Model names can be edited.
- **Anthropic Claude:** key from console.anthropic.com (paid per use). The default model is Claude Opus 5.5; Claude Haiku 5.5 is the cheapest. "Thinking effort" set to Low gives the quickest replies. If Claude's safety checks decline a request, the API retries it on a suitable fallback model automatically.
- **OpenAI ChatGPT:** key from platform.openai.com (paid per use). A ChatGPT Plus subscription doesn't include API use.
- **OpenRouter:** one key for many models (Claude, GPT, Gemini, Llama…); models ending in `:free` cost nothing.
- **Groq, Mistral:** both have free tiers. **DeepSeek, xAI Grok:** paid, per use.
- **Other OpenAI-compatible:** any server that speaks the OpenAI format, such as LM Studio on this PC (`http://127.0.0.1:1234/v1`, no key needed).
- Private mode treats every provider except Ollama and local servers as cloud AI.

Greetings and small talk ("hi", "who are you", "what can you do", "thanks", "tell me a joke") always get an instant answer, even with no AI model.

**Ollama (local, free, private).**
- Install it from <https://ollama.com>, then run `ollama pull qwen2.5:1.5b` (about 1 GB) or `qwen2.5:3b` (about 2 GB).
- Choose "Ollama" in Settings.
- On a Ryzen 5 3500U, expect a few seconds per reply. That's slower than Gemini but fully offline.

## 4. Voice

**Default: Microsoft neural voices (free).**
- `en-GB-RyanNeural` (deep, calm, British) or `en-GB-ThomasNeural`.
- This uses an unofficial Edge read-aloud endpoint, which occasionally fails. If it does, Jarvis falls back to the offline Windows voice.

**ElevenLabs (optional).**
- The free plan gives 10,000 credits a month. Flash v2.5 costs 0.5–1 credit per character, so that's about 10–20 minutes of speech a month.
- Free-plan output is for non-commercial use with attribution.
- Using a VPN can get free usage blocked.
- That's too little for all-day conversation, so use it as a premium voice, not the default. Don't buy anything.

To set up ElevenLabs:
1. Create a free account, then create an API key (Profile → API keys).
2. In Settings → Voice:
   - paste the key and save it;
   - press **Load my voices and usage**;
   - pick a voice. Look for labels like *British, middle-aged, calm/deep*. Premade voices such as "George" or "Daniel" fit, if they're still listed.
3. Lower **Stability** for more expression; raise it for a steadier, more "AI" delivery.

## 5. Microsoft: Outlook.com, Calendar and To Do

This uses Microsoft's official sign-in and the Microsoft Graph API.

**Create the free app registration (one time):**
1. Go to <https://entra.microsoft.com> (or portal.azure.com) and sign in with your **personal** Microsoft account.
   - Microsoft now asks personal accounts to have a directory. A free Azure sign-up creates one.
   - If it asks for payment details, stop: don't enter any.
2. Go to **App registrations → New registration**.
   - Name: `Jarvis`.
   - Supported accounts: **Personal Microsoft accounts only**.
   - Redirect URI: platform **Public client/native (mobile & desktop)**, value `http://localhost`.
3. Go to **Authentication** and set **Allow public client flows** to **Yes**.
4. Go to **API permissions → Add → Microsoft Graph → Delegated** and add:
   - `User.Read`
   - `Mail.Read`
   - `Mail.Send`
   - `Calendars.ReadWrite`
   - `Tasks.ReadWrite`
5. Copy the **Application (client) ID**.
6. In Jarvis, go to **Connections**, paste the ID, and press **Sign in**. Microsoft's login page opens in your browser and shows the permissions it's asking for.

To revoke access later:
- press **Disconnect** in Jarvis;
- remove "Jarvis" at <https://account.live.com/consent/Manage>.

**About Gmail inside Outlook. Please read this.**
- Microsoft Graph only sees your **Outlook.com mailbox**.
- Outlook.com no longer allows adding Gmail as a "connected account".
- When you add Gmail to the *new Outlook for Windows* app, Gmail syncs through Microsoft's cloud, but Microsoft doesn't document Graph access to it. **Don't expect Jarvis to see Gmail through Graph.**

Two working options for Gmail:
- **Classic Outlook (installed on this PC).** Add Gmail to classic Outlook, then turn on **Classic Outlook** in Jarvis's Connections. Jarvis reads and sends through classic Outlook's own object model, locally, with no cloud registration. Classic Outlook must be signed in and set up. The new Outlook app has no such interface.
- **Gmail forwarding.** In Gmail settings, forward mail to your Outlook.com address. Jarvis then sees copies through Graph. Replies would come from your Outlook.com address.

**Google Calendar.** Outlook's Gmail connection does **not** give Jarvis Google Calendar access. Without signing in to Google:
1. In Google Calendar → Settings → your calendar, copy the **Secret address in iCal format**.
2. In Outlook.com → Calendar → Add calendar → **Subscribe from web**, paste it.
3. The result is **read-only** and refreshes every few hours, sometimes taking over a day.

Jarvis reads all your Outlook calendars, so subscribed ones should be included. Microsoft doesn't document whether subscribed calendars appear in Graph, so this is untested.

**To Do.** Tasks and reminders go to your default Microsoft To Do list.

## 6. Discord (official bot, no self-bots)

1. Go to <https://discord.com/developers/applications> → **New Application** → **Bot**.
   - Press **Reset Token** and copy the token.
   - Turn on **Message Content Intent**.
2. Go to **OAuth2 → URL Generator**.
   - Scope: `bot`.
   - Permissions: *View Channels*, *Read Message History*, *Send Messages*.
   - Open the URL and invite the bot to a server you manage.
3. In Jarvis → Connections, paste the token, press **Connect**, and tick the channels Jarvis may read.

Limits:
- The bot sees only servers it's invited to.
- It can't read your personal DMs; Discord restricts that to approved partners.
- For a server you don't run, ask its admin to invite the bot.

## 7. WhatsApp

WhatsApp has no official API for reading a personal account. Unofficial tools risk getting your number banned, so Jarvis doesn't use them.

What Jarvis does: it works through the WhatsApp desktop app. For a contact saved under Connections → WhatsApp, "send hi to Sam on WhatsApp" opens Sam's chat with the message typed in, and Jarvis presses Enter to send it, but only once WhatsApp is the window in front. For a name that isn't saved, it types the message and you pick the chat. With **Ask before sending** on (Settings → Confirmations), it only types the message and you press Send. Jarvis can't read WhatsApp chats.

## 7b. Google: Gmail, Google Calendar, Google Tasks and Google Drive

Uses Google's official sign-in. You need your own free OAuth client, made once:
1. Go to console.cloud.google.com and create a project (free, no billing).
2. **APIs & Services → Library**: enable **Gmail API**, **Google Calendar API**, **Google Tasks API** and **Google Drive API**.
3. **OAuth consent screen**: choose External, fill in the app name and your email, and add your own Gmail address under **Test users**.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Copy the client ID and secret.
5. In Jarvis: Connections → Google, paste both (press Save for the secret), then **Sign in** and approve on Google's page.

While the app stays in "Testing" mode, Google makes you sign in again every 7 days. Once connected, all the email, calendar and task commands work with Gmail, Google Calendar and Google Tasks. If Outlook is also connected, Outlook is used first.

**Google Drive** is read-only: "find my biology notes in Drive", "read the budget sheet". If you signed in before Drive was added, press **Sign in** once more and tick the Drive box.

## 7c. GitHub

On github.com: Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate. Give read access to the repositories you want, plus **Issues** and **Pull requests** (add Issues: write if you want Jarvis to open issues). Paste it into Connections → GitHub. Then try "show my GitHub repos" or, with an AI model, "what's waiting for my review on GitHub?".

**Notifications:** GitHub only lets *classic* tokens read notifications. If you want "check my GitHub notifications", make a classic token instead (Personal access tokens → Tokens (classic)) with the `notifications` and `repo` scopes.

## 7e. Notion

1. Go to notion.so/my-integrations → **New integration** (type: Internal). Copy the token.
2. In Notion, open each page Jarvis may use → **⋯ → Connections → add your integration**. Jarvis can't see any page you don't share.
3. Connections → Notion: paste the token and press **Connect**. Optionally paste the link of the page where new notes should go.

Try "add buy milk to Notion", "search Notion for the science project", "read my reading list page".

## 7f. Slack

1. api.slack.com/apps → **Create New App** → From scratch, pick your workspace.
2. **OAuth & Permissions → Bot Token Scopes**: `channels:read`, `channels:history`, `groups:read`, `groups:history`, `chat:write`, `users:read`. Install it to the workspace and copy the **Bot User OAuth Token** (`xoxb-…`).
3. In Slack, type `/invite @YourBot` in each channel Jarvis may use.
4. Connections → Slack: paste the token and press **Connect**.

Jarvis posts as the bot, never as you. Try "read the latest in #general on Slack" or "post 'meeting moved to 5' in #team on Slack".

## 7g. Telegram

1. In Telegram, message **@BotFather** → `/newbot`, and copy the token it gives you.
2. Connections → Telegram: paste it and press **Connect**.

A bot can't use your personal account. It sees messages people send *to the bot*, and it can only message people who have messaged it first. Try "check Telegram" or "send hi to Sam on Telegram".

## 7h. Smart home (Home Assistant)

Needs your own Home Assistant server. In Home Assistant, open your profile → **Security → Long-lived access tokens → Create token**. In Connections → Smart home, enter the server address (for example `http://homeassistant.local:8123`) and the token.

Try "turn on the bedroom light", "turn the fan off", "dim the desk lamp to 30%". Locks, alarms and anything else security-related are never touched.

## 7i. Games, YouTube and YouTube Music (no setup)

- **Games:** "play Rocket League", "launch Fall Guys", "open FNAF". Jarvis finds games installed through Steam and Epic and starts them through the launcher's own link. It only matches titles you actually have, so "open Notepad" still opens Notepad.
- **YouTube:** "play Dracula on YouTube" opens the top video directly. "Play Blinding Lights on YouTube Music" does the same on music.youtube.com.

## 7j. Screen and clipboard

- **Screen:** "what's on my screen?", "explain this error", "what does this chart show?". Jarvis takes one screenshot of the screen you're using, sends it to your chosen AI model and answers. Nothing is saved. It only looks when your words are about the screen. With OpenRouter's free models, Jarvis picks a free model that can see images. Other providers use your chat model, or set one under Settings → AI model.
- **Clipboard:** "summarise what I copied", "translate my clipboard into French", "read my clipboard". The AI can also copy text for you ("copy that to my clipboard").

Screenshots and clipboard text go to the AI provider you chose, so think before asking about a screen with private things on it.

## 7k. Game mode, floating orb and wake words

- **Game mode** stops listening for the wake word, so your game gets the CPU. It switches on by itself when a Steam or Epic game (or any full-screen game) is in front, and off again about 6 seconds after you leave it. You can also say "game mode on", or click the **Game mode** chip at the top. To come back from a game mode you turned on yourself, type "game mode off" or click the chip. Turn the automatic part off in Settings → Desktop.
- **Floating orb:** Settings → Desktop → **Floating orb**. A small round Jarvis that stays on top of other windows: click it to talk, double-click to open the dashboard, right-click to stop it talking, drag to move it.
- **Wake word:** Settings → Listening → Wake word: *Hey Jarvis*, *Alexa*, *Hey Mycroft* or *Hey Rhasspy*. For your own phrase ("Hey Friday"), train a model with openWakeWord's free training notebook (search "openWakeWord automatic model training", it runs in Google Colab), download the `.onnx` file it makes, choose **My own wake word** and paste the file's path. Training takes about an hour in Colab. Your PC is too slow to train one itself.
- **Faster replies:** with an AI model, Jarvis starts speaking as soon as the first sentence of the answer arrives (Settings → AI model → *Start speaking while the AI is still writing*).

## 7d. Weather

Free from Open-Meteo, with no key or account. Set your home city in Settings, then say "what's the weather?", "weather in London" or "will it rain tomorrow?".

### Windows, files, buttons and routines (ideas borrowed from Atticus)

All of these work offline with no AI model.
- **Window layout:** "Notepad on the left and Chrome on the right", "Discord on the top right", "maximise Spotify", "minimise Discord", "Spotify on the other screen". Positions are left, right, top, bottom, the four corners, thirds and centre. Apps that aren't open get opened first.
- **Find files:** "find my notes about the Tokyo trip", "where is my lease PDF". Uses the Windows Search index, so it matches file names and the text inside documents. Jarvis opens the best match and names a couple of others. Programs and scripts are only shown in File Explorer, never run.
- **Press buttons in apps:** "press seven in Calculator", "in Settings, click Bluetooth". Uses Windows' accessibility interface, so the mouse doesn't move. Buttons that could send, delete, buy or confirm show an approval card first, and only the on-screen button approves them. Some apps (Spotify, for one) don't expose their buttons this way.
- **Routines:** "when I say focus mode, close Discord and open Notepad". Saying "focus mode" later runs each step with the usual safety checks, so closing an app still asks first. "What routines do I have?" lists them, "forget the focus mode routine" deletes one, and they're also listed in Settings.

### Spotify

Say "play the song Dracula", "play Dracula by Tame Impala", "play my liked songs" or "play any song". Add "on Spotify" if you like. "Play music", "pause", "next song" and "previous track" still work as media keys.

How it works: Spotify's official playback API needs Premium plus a developer app, so Jarvis drives the desktop app instead. No key or login is needed.
- **Songs:** Jarvis finds the song's Spotify link with a web search (needs internet, 5 to 10 seconds), pauses whatever is playing and opens the link. Spotify then starts it by itself.
- **Liked Songs:** Jarvis opens the playlist, finds the green Play button in a picture of the Spotify window and clicks it. The mouse jumps there for a moment and comes back, and Spotify comes to the front.
- **Any song:** Jarvis turns on Shuffle for Liked Songs if it's off, starts playing, then skips once to land on a random song.

If Spotify's layout changes and Jarvis can't find the button, it says so and leaves the page open for you to press Play.

## 8. Safety rules built in

- **Closing apps** and **sending** email, Discord, Slack, Telegram, WhatsApp messages or GitHub issues happen straight away when you ask, as you chose. Turn either back on under Settings → Confirmations.
- **Private mode** keeps email, calendar, tasks, Discord, GitHub, Notion, Drive, Slack and Telegram away from online AI models. Simple commands ("check my email", "show my GitHub repos") still work without the AI.
- **The screen** is only captured when your words are about it, and never saved.
- A send has to come from **your own words** ("email Bob that…", "post … in general"). If the AI decides to send something while doing another job, for example after reading an email that says "forward this to…", Jarvis shows an approval card instead, and only the on-screen button approves it.
- **Creating calendar events** and **pressing risky buttons** in apps (Send, Delete, Buy…) still show a card.
- Jarvis never deletes files and never makes purchases. Protected system processes can't be closed.
- Content from emails and web pages is treated as information, never as instructions.
- Every tool use, approval, connection change and mic toggle goes into the **Activity** tab.

## 9. Troubleshooting

- **Wake word too sensitive, or not sensitive enough:** Settings → Wake sensitivity (lower means it triggers more easily).
- **Slow recognition:** switch the speech model to `tiny.en`. For better accuracy, use `small.en` (slower).
- **Voicemod:** if Voicemod is installed, make sure Windows' default *input* device is your real microphone (Settings → Sound).
- **Smart App Control:** it blocks scikit-learn's DLLs on this PC. Jarvis doesn't need scikit-learn (setup removes it), so leave Smart App Control on.
- **Tests:** `run_tests.bat`. Desktop actions are mocked; nothing gets opened or closed.
