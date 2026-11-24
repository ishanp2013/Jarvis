# J.A.R.V.I.S

A personal AI assistant for Windows 11, in the spirit of Iron Man's Jarvis. Say **"Hey Jarvis"** and talk naturally. Jarvis can:
- run your laptop, play your music and read your email
- control your Android phone
- watch your school sources for assignments and deadlines
- prepare finished presentations and notes
- brief you when you come back

A gold hologram orb animates as it speaks.

Jarvis runs in the background, starts with Windows and is reachable from your phone anywhere through a private network. It's built to stay light on a mid-range laptop (developed on a Ryzen 5 3500U). Wake word and speech recognition run on your PC, and common commands work with no AI and no internet.

---

## Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Install (step by step)](#install-step-by-step)
4. [Choose an AI model](#choose-an-ai-model)
5. [Voice and wake word](#voice-and-wake-word)
6. [Run in the background](#run-in-the-background)
7. [Connect your accounts](#connect-your-accounts)
8. [Your phone](#your-phone)
9. [The background agent (school)](#the-background-agent-school)
10. [Prepared work (presentations, documents, notes)](#prepared-work)
11. [Briefings and the Today tab](#briefings-and-the-today-tab)
12. [More features](#more-features)
13. [Things you can say](#things-you-can-say)
14. [Privacy and safety](#privacy-and-safety)
15. [Troubleshooting](#troubleshooting)
16. [Project layout and tests](#project-layout-and-tests)

---

## Features

| Area | What Jarvis does |
|---|---|
| **Voice** | "Hey Jarvis" wake word (or Alexa, Hey Mycroft, Hey Rhasspy, or your own). Speech recognition on your PC. Natural British voice. Keep talking without repeating the wake word. Interrupt it any time. Starts speaking while the AI is still writing. |
| **AI** | Your choice of Claude, ChatGPT, Gemini, OpenRouter, BazaarLink and OrcaRouter (free models), Groq, Mistral, DeepSeek, Grok, or fully offline with Ollama / LM Studio. Shares a daily AI budget so free plans last, and switches to backup models when one runs out. |
| **Windows** | Open, close, switch and arrange apps. Find files ("the presentation I was working on yesterday"). Press buttons in apps. Media keys, lock, restart and shut down with confirmation. Routines. Screen understanding ("explain this error"). Clipboard ("translate what I copied"). |
| **Music, video, games** | Spotify desktop app (works with a free account): a song, Liked Songs, any song. YouTube and YouTube Music. Steam and Epic games. |
| **Accounts** | Gmail, Google Calendar, Tasks, Drive, Classroom, Outlook, Microsoft To Do, GitHub, Discord, Slack, Telegram, WhatsApp, Notion, Home Assistant, weather, web research with sources. |
| **Phone** | **From your phone:** chat, talk, screenshot the laptop, see what's running, open apps, lock, restart. **From the laptop:** find your phone, open apps on it, read its notifications. |
| **Background agent** | Checks Classroom, Gmail and phone notifications every 45 minutes. Understands assignments and tests, keeps a task list, drafts replies for your approval, and reminds you before deadlines. |
| **Prepared work** | Turns tasks into finished PowerPoint decks, Word documents, study notes, revision sheets and spreadsheets, researched from reliable sources and saved in *Documents\School Projects*. |
| **Briefings** | "Welcome back. You received 8 messages… I've prepared your science presentation…", spoken when you return, plus a Today tab on the laptop and phone. |
| **Dashboard** | A holographic HUD: a 3D Jarvis core that pulses with your voice and his (a flat 2D core in low-power mode), a boot sequence, live system meters, and a **Team** tab that works like Discord: talk to Jarvis, watch the **#team** channel as agents hand work to each other, or chat directly with one specialist. |
| **Builder** | "Tell Claude Code to make the UI cooler": after your approval, Claude Code changes Jarvis's own code on a separate copy, the tests run, and you choose to apply or discard it. "Undo Builder's last change" puts it back. Needs Claude Code signed in with your own personal account. |
| **System control** | Operator makes folders; moves, copies and renames files; and runs Windows commands. Harmless things just happen. Only major actions ask first: deleting (always to the Recycle Bin), commands that change the system, restart/shutdown and risky buttons. Windows' own folders are never touched. |
| **Jarvis and his team** | Jarvis talks to you and passes work to five specialists: **Scholar** (school, tasks), **Forge** (makes files), **Herald** (messages), **Operator** (laptop and phone), **Scout** (research). Each uses only its own tools, and only Herald can send, enforced in code. Common commands use no AI; a chat question costs 1 request; delegated work costs 2 or more. Scout searches the web before answering. |

---

## Requirements

- **Windows 10 or 11.**
- **Python 3.11**, from python.org or the Microsoft Store (`py -3.11` must work in Command Prompt).
- **A microphone and speakers.**
- **About 1.5 GB of free disk space** for the Python packages and speech models.
- **Optional:** an Android phone, for the phone features.

---

## Install (step by step)

### Step 1: Install Python 3.11
1. Get **Python 3.11** from <https://www.python.org/downloads/> or the Microsoft Store.
2. During install, tick **"Add python.exe to PATH"**.
3. Check it: open **Command Prompt** and type `py -3.11 --version`. It should print `Python 3.11.x`.

### Step 2: Get Jarvis
Either:
- **With Git:** `git clone https://github.com/ishanp2013/Jarvis.git`, or
- **Without Git:** on GitHub, **Code → Download ZIP**, then unzip it somewhere permanent (for example your Desktop).

### Step 3: Run the setup
1. Open the Jarvis folder and double-click **`setup.bat`**.
2. Wait while it:
   - creates its own Python environment in `%LOCALAPPDATA%\JarvisAssistant\venv`, so your system Python stays untouched;
   - installs the packages;
   - downloads the wake-word and speech models (about 160 MB, one time).
3. When it asks **"Create a desktop shortcut?"**, type `y`.

### Step 4: Start Jarvis
- Double-click **`Jarvis.bat`** (or the desktop shortcut). The dashboard window opens, and the background core starts if it isn't running yet.
- Or double-click **`Jarvis-Web.bat`** to use the dashboard in your browser at <http://127.0.0.1:8765>.
- Windows may ask for **microphone permission**. Allow it.
- Wait for **"Standing by"**, then say **"Hey Jarvis"**. You'll hear a chime; then say something like **"open YouTube"**.
- You can also press **Talk** (Ctrl+Space) or type in the box. To interrupt, say "Hey Jarvis", press **Stop** or press **Esc**. **Mic** turns the microphone off completely.

Common commands already work at this point, even with no AI.

---

## Choose an AI model

Go to **Settings → AI model**, pick a provider, paste its key, press **Save**. Keys are stored in Windows Credential Manager, never in files.

| Provider | Cost | Where to get a key |
|---|---|---|
| **OpenRouter** (recommended free start) | Free models available (about 50 requests/day) | <https://openrouter.ai/keys>. Set the model to `openrouter/free`. |
| Google Gemini | Free tier (18+ only; not free in UK/EEA) | <https://aistudio.google.com/apikey> |
| BazaarLink | Free models (small daily allowance) | <https://bazaarlink.ai>. Model `auto:free`. |
| OrcaRouter | Free models available | <https://www.orcarouter.ai>. Model `orcarouter/free`. |
| Groq, Mistral | Free tiers | console.groq.com, console.mistral.ai |
| Anthropic Claude | Paid per use | <https://console.anthropic.com> |
| OpenAI ChatGPT | Paid per use | <https://platform.openai.com> |
| DeepSeek, xAI Grok | Paid per use | their developer consoles |
| Ollama / LM Studio | Free, offline, on your PC | <https://ollama.com>, then `ollama pull qwen2.5:3b` |

**Backups:** under **Settings → AI model → Backups**, press **+ Add backup** as many times as you like. For each one, pick the service, paste its key and press **Save** (empty model = that service's usual one). The arrows change the order. When a model hits its limit, runs out of credit or its key stops working, Jarvis carries on with the next one and goes back once the first resets (free plans: midnight UTC). Every model gets the same conversation and memories, because Jarvis keeps those himself. If a request had already done something (sent a message, moved a file) when the limit hit, it isn't repeated: Jarvis switches and asks you to say it again.

> **API keys are separate from subscriptions.** ChatGPT Plus, Claude Pro or Google AI Pro don't include API use. Never use someone else's account or key.

**Private mode** (Settings → AI model) is on by default. It keeps your email, calendar, tasks and messages away from online AI models. Simple commands like "check my email" still work without the AI.

**Daily budget:** Jarvis counts every request to an online model. The background agent uses at most 25 a day and always leaves 15 for your own questions. Change these in the **Tasks** tab to match your plan.

---

## Voice and wake word

**Voice** (Settings → Voice):
- **Microsoft neural (default, free):** `en-GB-RyanNeural` is a deep, calm British voice.
- **ElevenLabs (optional):**
  1. Make a free account at elevenlabs.io and create an API key (Profile → API keys).
  2. Paste the key and press **Save**.
  3. Press **Load my voices and usage** and pick a voice, or paste a voice ID from the ElevenLabs voice library. Library voices may need a paid plan.
  4. Adjust **Stability**, **Similarity** and **Style**.
- **Windows offline voice:** works with no internet.

**Wake word** (Settings → Listening):
- Pick *Hey Jarvis*, *Alexa*, *Hey Mycroft* or *Hey Rhasspy*, and press **Use this wake word**.
- **Your own phrase** (for example "Hey Friday"):
  1. Train a model with openWakeWord's free training notebook. Search "openWakeWord automatic model training"; it runs in Google Colab and takes about an hour.
  2. Download the `.onnx` file it makes.
  3. Choose **My own wake word** and paste the file's path.
- **Wake sensitivity:** lower triggers more easily.

---

## Run in the background

Settings → **Phone and background**:
1. Tick **Start Jarvis in the background when I sign in to Windows**. This adds a shortcut to your own Startup folder; no admin rights are needed.
2. Tick **Keep the laptop awake while it's plugged in** so background work and phone access keep going. On battery, normal sleep applies.
   > Closing the lid still sleeps the laptop. If you want Jarvis to keep working with the lid shut while charging, change that yourself: Control Panel → Power Options → *Choose what closing the lid does* → "Do nothing" when plugged in.
3. To open the dashboard, use `Jarvis.bat`, or double-click the floating orb. To stop Jarvis completely, end `pythonw.exe` in Task Manager.

---

## Connect your accounts

All connections are optional and use each service's **official** sign-in or API. You can disconnect any of them in **Connections**.

### Google: Gmail, Calendar, Tasks, Drive
1. Go to <https://console.cloud.google.com> and **create a project** (free, no billing).
2. **APIs & Services → Library**: enable **Gmail API**, **Google Calendar API**, **Google Tasks API** and **Google Drive API**.
3. **Google Auth Platform → Audience** (or *OAuth consent screen*):
   - User type **External**.
   - Fill in the app name and your email.
   - Under **Test users**, add your Gmail address. Without this, Google shows *Error 403: access_denied*.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**, then copy the **client ID** and **client secret**.
5. In Jarvis → **Connections → Google**: paste the client ID, paste the secret and press **Save**, then press **Sign in**.
6. On Google's page you'll see *"Google hasn't verified this app"*. That's normal for your own app: click **Continue** and tick every box.

While the app is in Testing mode, Google makes the sign-in expire every 7 days (Jarvis then says "Google sign-in has expired", and background checks of Gmail stop). To stop that, go to **Google Auth Platform → Audience** and press **Publish app** (status *In production*). It stays your private, unverified app: you still see the "hasn't verified" page when signing in, but the sign-in no longer expires weekly. Then sign in again in Jarvis once.

### Google Classroom (school account)
1. In the same Google Cloud project, enable the **Google Classroom API**.
2. Add your **school** email under **Test users**.
3. Jarvis → **Connections → Google Classroom → Sign in with school account**, and choose your school account.
4. If Google says *"Access blocked"*, your school doesn't allow outside apps, and only the school's IT admin can change that. Use **Classroom by email** below instead.

#### Classroom by email (when the school account can't be connected)
Classroom emails you about new work, announcements, teacher comments and due dates. Forward **only those** from your school Gmail to your personal Gmail, and Scholar picks them up in the background (every 45 minutes), turning new work into tasks with due dates. Nothing connects to your school account.

1. **Classroom → ⚙️ Settings → Notifications**: turn on **Allow email notifications** (and the kinds you want).
2. **School Gmail → ⚙️ → See all settings → Forwarding and POP/IMAP → Add a forwarding address**: enter your personal Gmail. Google emails a confirmation code to your personal Gmail; open that email and confirm.
3. Still in that tab, leave **Disable forwarding** selected and save. (This keeps the rest of your school mail where it is; the filter below forwards only Classroom's emails.)
4. **School Gmail → search box → Show search options**: in **From** type `classroom.google.com`, then **Create filter** → tick **Forward it to** and choose your personal Gmail → **Create filter**.
5. Make sure your personal Gmail is connected in Jarvis (**Connections → Google**) and the sign-in hasn't expired (see above).

If your school ever turns forwarding off, Gmail shows it on that settings tab; nothing breaks in Jarvis, the Classroom emails just stop arriving.

### Microsoft: Outlook.com, Calendar, To Do
1. Go to <https://entra.microsoft.com> with your **personal** Microsoft account. If it asks for payment details, stop.
2. **App registrations → New registration**:
   - Name `Jarvis`.
   - **Personal Microsoft accounts only**.
   - Redirect URI: *Public client/native*, `http://localhost`.
3. **Authentication**: set **Allow public client flows** to **Yes**.
4. **API permissions → Microsoft Graph → Delegated**: add `User.Read`, `Mail.Read`, `Mail.Send`, `Calendars.ReadWrite` and `Tasks.ReadWrite`.
5. Copy the **Application (client) ID**, paste it into Jarvis → **Connections → Microsoft**, and press **Sign in**.

If classic Outlook is installed and signed in, you can tick **Classic Outlook** instead, with no registration.

### GitHub
1. github.com → Settings → Developer settings → **Personal access tokens**:
   - **Fine-grained token:** read access to your repos, Issues and Pull requests (Issues: write to open issues).
   - **Classic token** with `repo` and `notifications`, if you want "check my GitHub notifications". GitHub doesn't give fine-grained tokens access to notifications.
2. Jarvis → **Connections → GitHub**: paste the token and press **Connect**.

### Discord (your own bot)
1. Go to <https://discord.com/developers/applications> → **New Application** → **Bot**.
2. Press **Reset Token** and copy it. Turn on **Message Content Intent**.
3. **OAuth2 → URL Generator**:
   - Scope `bot`.
   - Permissions *View Channels*, *Read Message History*, *Send Messages*.
   - Open the link and invite the bot to your server. For a class server, ask its admin.
4. Jarvis → **Connections → Discord**: paste the token, press **Connect**, and tick the channels Jarvis may read.

The bot can't read your personal DMs.

### Slack (your own bot)
1. Go to <https://api.slack.com/apps> → **Create New App → From scratch**.
2. **OAuth & Permissions → Bot Token Scopes**: `channels:read`, `channels:history`, `groups:read`, `groups:history`, `chat:write`, `users:read`.
3. **Install to Workspace** and copy the `xoxb-…` token.
4. In each channel, type `/invite @YourBot`.
5. Jarvis → **Connections → Slack**: paste the token and press **Connect**.

### Telegram (your own bot)
1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. Jarvis → **Connections → Telegram**: paste it and press **Connect**.
3. People must message your bot once before Jarvis can reply to them.

### Notion
1. Go to <https://www.notion.so/my-integrations> → **New integration** (Internal) and copy the token.
2. In Notion, open each page Jarvis may use → **⋯ → Connections** → add your integration.
3. Jarvis → **Connections → Notion**: paste the token and press **Connect**. Optionally paste the link of the page where notes should go.

### WhatsApp
- Install **WhatsApp Desktop** on the laptop and sign in.
- In **Connections → WhatsApp**, save contacts (name and number) so "send hi to Sam on WhatsApp" can open the right chat. Numbers stay on your PC.
- **Checking replies:** ask "has Sam replied on WhatsApp?", "has Sam seen my message on WhatsApp?", "what did Sam say on WhatsApp?" or "check my WhatsApp". No AI request is used.
  - "Check my WhatsApp" reads only the chat list (names, times, last-message previews, unread counts); nothing is opened.
  - Questions about one person open that chat in WhatsApp Desktop and read the messages it has loaded (usually the most recent few dozen): who sent each, when, whether yours were sent, delivered or read, and reactions like a 👍 on your message. Opening a chat marks its new messages as read, just like you opening it; afterwards Jarvis goes back to the chat you had open. It takes about 10 seconds.
  - Only chats in the recent list (usually 15 to 20) can be opened. If WhatsApp is minimised, its window shows without taking focus, then goes back. WhatsApp Desktop has to be running.
  - Turn it off with **Connections → WhatsApp → Let Jarvis read the WhatsApp chat list**.

### Smart home (Home Assistant)
1. In Home Assistant: your profile → **Security → Long-lived access tokens → Create token**.
2. Jarvis → **Connections → Smart home**: enter the address (for example `http://homeassistant.local:8123`) and the token.

Locks and alarms are never touched.

### No setup needed
- **Spotify:** the Microsoft Store desktop app, signed in. Works with a free account.
- **YouTube and YouTube Music:** open in your browser.
- **Steam and Epic games:** found automatically.
- **Weather:** Open-Meteo. Set your home city in Settings.
- **Web search:** DuckDuckGo, with sources.

---

## Your phone

### A. Control the laptop from your phone (anywhere, through Tailscale)
1. Install **Tailscale** on the laptop (<https://tailscale.com/download> or the Microsoft Store) and sign in with your personal account.
2. Install **Tailscale** on your phone (Play Store) and sign in with the **same** account.
3. On the laptop, open **Command Prompt** and run once:
   ```
   tailscale serve --bg 8765
   ```
   If it asks to enable HTTPS, open the link it prints and allow it. This shares Jarvis only with your own Tailscale devices, not the internet.
4. In Jarvis: **Settings → Phone and background → Pair a phone**. A 6-digit code and a QR code appear.
5. On the phone, open the address shown (`https://<laptop>.<tailnet>.ts.net`) in Chrome, or scan the QR code, then enter the code.
6. Chrome menu **⋮ → Add to Home screen**, so Jarvis works like an app.

**On the phone:**
- **Today:** your briefing, what's coming up, what Jarvis did, and your schedule.
- **Chat:** type or hold 🎤 to talk. The laptop's Whisper transcribes it, and the phone reads the reply aloud.
- **Tasks:** your task list, prepared work (with *Open on laptop*), and *Check school now*.
- **Laptop:** battery, CPU, memory and status, quick-open buttons, screenshot, what's running, lock, game mode, and restart or shut down (always confirmed, with a 30-second cancellable countdown).

If the laptop is asleep or off, the app still opens and shows **"Laptop offline (last seen …)"**. Commands can't run until it's back.

### B. Control your phone from the laptop (KDE Connect, Android)
1. Install **KDE Connect** on the laptop (Microsoft Store) and on the phone (Play Store).
2. With both on the same Wi-Fi, open KDE Connect on both and **pair** them.
3. On the phone, open KDE Connect → your laptop → **Plugin settings**, and turn on:
   - **Notification sync** (allow notification access when Android asks)
   - **Ring my phone**
   - **Share and receive**
4. In Jarvis → **Connections**, the phone card shows *connected*.

**Not possible, by design:**
- **Unlocking the phone:** Android only unlocks with your PIN or fingerprint, and Jarvis never tries to get around that.
- **Pressing Call or Send inside phone apps:** Jarvis opens the chat and you tap. WhatsApp messages are sent through WhatsApp Desktop on the laptop instead.

---

## The background agent (school)

Every 45 minutes (or when you press **Check school now**), Jarvis:
1. Collects what's new from **Google Classroom**, **Gmail/Outlook**, **phone notifications** (WhatsApp groups and the like) and selected **Discord** channels.
2. Sends **only school items** to the AI. Everything else is just counted.
3. Works out what each one means: assignment, test, announcement or request, how important it is, the **real due date** ("next Thursday" becomes a date), and exactly what's asked.
4. Adds assignments and tests to your **task list**, sorted by urgency.
5. Drafts replies to school emails as **approval cards**, with blanks like "[will / won't]" where only you can decide. Nothing is sent without your tap.
6. **Reminds you** the afternoon before a deadline and the morning of it, on the laptop and your phone.

**Set it up:**
1. Open the **Tasks** tab.
2. Under **School senders and groups**, add one per line:
   - your school's email domain (for example `@yourschool.edu`)
   - teachers' email addresses
   - WhatsApp group names (for example `Class 9B`)
3. Connect **Google Classroom** (above), and turn on KDE Connect's **Notification sync** for WhatsApp groups.
4. Optionally adjust the check interval and the AI budget.

You can also manage tasks yourself: "add a task maths worksheet by Friday", "what's due?", "mark the maths worksheet as done".

---

## Prepared work

Jarvis can turn a task into a finished file, saved in **Documents\School Projects\<task name>**:
- **PowerPoint decks:**
  - the requested number of slides
  - free-licence photos from Wikimedia Commons, credited on the slide
  - a real chart when the sources give real numbers
  - speaker notes and a sources slide
- **Word documents:** reports, study notes, revision sheets with practice questions, PDF summaries.
- **Excel spreadsheets**, with working formulas.

**How it works:**
1. **Plan:** the AI plans the outline.
2. **Research:** Jarvis researches reliable sources (Wikipedia and government, university and education sites first).
3. **Write:** the AI writes from those sources, citing them.
4. **Build:** Jarvis adds pictures and builds the file.
5. **Check:** the AI reviews the draft against the assignment, and Jarvis checks the file itself (slide count, no empty pages).
6. **Save:** existing files are never overwritten.

A presentation takes about 3 to 5 minutes and about 4 AI requests.

**Ways to start one:**
- **Automatically:** new assignments are prepared by themselves. You can turn this off in the Tasks tab.
- **Prepare button:** on any task in the Tasks tab.
- **Say it:** "make a 10-slide presentation about renewable energy", "make study notes on photosynthesis", "summarise my biology PDF".
- **Open it:** "show me the presentation", **Open** in the Tasks or Today tab, or *Open on laptop* from your phone.

> **It's a draft.** AI models can make mistakes, including wrong numbers and maths. Read it, check it and make it your own before handing anything in. Jarvis never submits work.

---

## Briefings and the Today tab

- **When you come back:** after 30+ minutes without keyboard or mouse, and when the laptop starts, Jarvis gives a short spoken briefing. It covers new messages and emails, new assignments, files it prepared, what's due, replies needed, approvals waiting, and today's calendar.
- **On demand:** say "what did I miss?", "brief me" or "what's happening today?".
- **When it stays quiet:** if nothing is new, in game mode, or between 22:00 and 07:00.
- **No AI used:** briefings are made locally from templates, and nothing leaves the laptop.
- **Today tab:** the first tab on the dashboard and the phone app. It shows the same information visually, plus devices, quick controls and recent activity.

---

## More features

| Feature | How to use it |
|---|---|
| **Screen understanding** | "What's on my screen?", "explain this error". One screenshot goes to your AI and nothing is saved. With OpenRouter, Jarvis picks a free model that can see images. |
| **Clipboard** | "Summarise what I copied", "translate my clipboard into French", "read my clipboard". |
| **Game mode** | Turns on by itself when a Steam/Epic or full-screen game is in front, and stops wake-word listening so the game runs smoothly. Or say "game mode on", or click the **Game mode** chip. |
| **Floating orb** | Settings → Desktop → **Floating orb**: a small always-on-top Jarvis. Click to talk, double-click for the dashboard, right-click to stop, drag to move. |
| **Window layout** | "Notepad on the left and Chrome on the right", "maximise Spotify", "Discord on the top right". |
| **Find files** | "Find my notes about the Tokyo trip", "find the presentation I was working on yesterday". |
| **Buttons in apps** | "Press seven in Calculator". Risky buttons (Send, Delete, Buy) ask first. |
| **Routines** | "When I say study mode, close Discord and play lo-fi on YouTube." |
| **Memory** | "Remember that my maths teacher is Ms Rao", "what do you remember?" |
| **Confirmations** | Settings → Confirmations: choose whether closing apps and sending messages asks first. |

---

## Things you can say

| | |
|---|---|
| **Apps & web** | "Open Opera", "close Discord", "switch to Spotify", "open Google Classroom", "play Dracula on YouTube" |
| **Music** | "Play my liked songs", "play any song", "play the song Dracula", "next song", "volume up" |
| **Games** | "Play Rocket League", "game mode on" |
| **Info** | "What's the weather?", "search the web for the newest Python version", "system status" |
| **Email & calendar** | "Do I have any unread emails?", "what's on my calendar tomorrow?", "email Ms Rao that I'll be late" |
| **School** | "What's due?", "check for new assignments", "add a task history essay by Monday", "mark the essay as done" |
| **Prepared work** | "Make a 10-slide presentation about volcanoes", "make a revision sheet for quadratics", "show me the presentation" |
| **Phone** | "Find my phone", "open WhatsApp on my phone", "who messaged me recently?", "call Sam on WhatsApp" |
| **Laptop** (from the phone) | "Take a screenshot and show it to me", "what's running on my laptop", "restart my laptop" |
| **Briefing** | "What did I miss?", "brief me" |
| **Small talk** | "Hi", "who are you?", "tell me a joke" |

---

## Privacy and safety

- **Secrets:** API keys and tokens are kept in **Windows Credential Manager**, and Google/Microsoft sign-ins are encrypted with Windows DPAPI. Logs mask anything that looks like a secret.
- **Microphone:** **Mic** closes it completely. Speech is recognised on your PC.
- **Phone access:** the server listens only on your PC. Your phone reaches it through Tailscale, which covers only your own devices. Phones must be paired with a one-time code, and you can remove them at any time.
- **Sends:** a message, email or post goes out only when your own words ask for it. If the AI decides to send something itself (for example after reading an email), you get an approval card. Instructions hidden inside emails or web pages are treated as data, never obeyed.
- **Private mode** keeps personal data away from online AI. The school agent only sends items from your listed school senders.
- **Never does:** unlock your phone, delete files, make purchases, create API keys, or use unofficial WhatsApp tools or self-bots.
- **Activity log:** everything is recorded in the **Activity** tab.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **Google: Error 403 access_denied** | Add your Gmail address under **Test users** in Google Cloud (Google Auth Platform → Audience). |
| **"… API is switched off in your Google Cloud project"** | Enable that API under APIs & Services → Library, wait a minute, and try again. |
| **"Google hasn't verified this app"** | Normal for your own app: click **Continue**. |
| **Connect button stuck / dashboard frozen** | Jarvis restarted; the page reloads by itself. Otherwise refresh it. |
| **Phone shows "Laptop offline"** | The laptop is asleep, off or not on Tailscale. Check that both devices are signed in to Tailscale and that `tailscale serve --bg 8765` was run. |
| **No phone notifications** | Turn on **Notification sync** for the laptop in the phone's KDE Connect app. |
| **AI says the usage limit is reached** | Free plans have daily limits. It resets (OpenRouter: midnight UTC). Basic commands keep working. |
| **Wake word too sensitive / not sensitive enough** | Settings → Listening → **Wake sensitivity**. |
| **Slow speech recognition** | Settings → Listening → speech model `tiny.en` (faster) or `small.en` (more accurate). |
| **Voice stopped working** | The free Microsoft voice occasionally fails. Jarvis falls back to the Windows voice by itself. |
| **Smart App Control** | Jarvis doesn't need scikit-learn (setup removes it), so you can leave Smart App Control on. |

More detail on every connection is in **[SETUP.md](SETUP.md)**.

---

## Project layout and tests

```
jarvis/
  app.py          background core, API, game mode, floating orb, briefings
  brain.py        command router, tools, AI providers, streaming, screen reading
  speech.py       wake word, speech-to-text, text-to-speech
  listener.py     microphone loop
  web.py          local server for the dashboard, orb and phone (pairing, device keys)
  ai.py           background AI requests and the daily budget
  power.py        keep awake while plugged in
  autostart.py    start at sign-in
  team/           Jarvis's team: the agents (Jarvis, Scholar, Forge, Herald, Operator, Scout), their tools and permissions
  agent/          background agent: sources, triage, tasks, worker, research, briefing, file builders
  tools/          one module per app or service (spotify, google, classroom, phone, github, …)
ui/               dashboard, floating orb, phone app (service worker for offline)
tests/            test suite
```

The dashboard bundles [Three.js](https://threejs.org) (MIT) and the Orbitron and Rajdhani fonts (SIL Open Font License) in `ui/vendor`, so it works offline.

Run the tests with **`run_tests.bat`**. Desktop actions and online services are mocked, so nothing is opened, closed or sent.

Settings, history and the task list are kept in `%LOCALAPPDATA%\JarvisAssistant`, never in this folder.
