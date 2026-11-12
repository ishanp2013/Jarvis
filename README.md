# J.A.R.V.I.S

A voice assistant for Windows 11 in the spirit of Iron Man's Jarvis. Say **"Hey Jarvis"**, talk naturally, and it opens apps, plays music, reads your email, answers questions with sources, looks at your screen and runs your routines. It answers in a calm British voice and a gold hologram orb animates as it speaks.

It is built to stay light on a mid-range laptop (it was developed on a Ryzen 5 3500U). Wake-word detection and speech recognition run on your PC, and common commands work with no AI and no internet.

## Features

**Voice**
- "Hey Jarvis" wake word (also Alexa, Hey Mycroft, Hey Rhasspy, or your own trained phrase)
- Speech recognition on your PC (faster-whisper), so your voice isn't uploaded
- Natural voices: Microsoft neural voices (free), ElevenLabs (your own key, with adjustable stability, similarity and style) or the offline Windows voice
- Keep talking without repeating the wake word, and interrupt it mid-sentence
- Starts speaking while the AI is still writing its answer
- Instant replies to "hi", "who are you", "tell me a joke" and similar
- Ends replies with "sir" (or any word you choose)

**AI brain (pick one)**
- Anthropic Claude, OpenAI, Google Gemini, OpenRouter (including free models), Groq, Mistral, DeepSeek, xAI Grok
- Fully local with Ollama or LM Studio
- Common commands work with no AI at all

**Windows control**
- Open, close and switch apps
- Arrange windows ("Notepad on the left and Chrome on the right")
- Find files with Windows Search
- Press buttons inside apps
- Media keys and volume, lock the PC, system info
- Routines: "when I say focus mode, close Discord and open Notion"
- **Screen understanding:** "what's on my screen?", "explain this error"
- **Clipboard:** "summarise what I copied", "translate my clipboard into French"
- **Game mode:** stops listening for the wake word while a game is in front, then comes back by itself
- **Floating orb:** a small round Jarvis that stays on top. Click to talk, double-click for the dashboard

**Music, video and games**
- **Spotify desktop app, works with a free account:** "play the song Dracula", "play my liked songs", "play any song"
- **YouTube and YouTube Music:** "play Dracula on YouTube" opens the top video
- **Steam and Epic games:** "play Rocket League"

**Connections (all optional, all official APIs)**
| Service | What Jarvis can do |
|---|---|
| Gmail, Google Calendar, Google Tasks, Google Drive | read and send mail; see and add events and tasks; search and read Drive files |
| Outlook.com, Outlook Calendar, Microsoft To Do | the same, through Microsoft Graph or classic Outlook |
| GitHub | repos, notifications, assigned issues and review requests; open issues |
| Discord | read and post in chosen channels, as your bot |
| Slack | read and post in channels, as your bot |
| Telegram | read messages to your bot and reply |
| WhatsApp | send to saved contacts through the WhatsApp desktop app |
| Notion | search, read and add notes |
| Home Assistant | lights, switches, fans, climate and scenes |
| Weather | Open-Meteo, no key needed |
| Web research | DuckDuckGo, with sources |

**Dashboard**
- Live orb
- Conversation, activity log, settings and connections
- CPU and RAM, plus what Jarvis itself is using
- Runs in its own window, or in your browser at `http://127.0.0.1:8765`

## Privacy and safety

- **Secrets:** API keys and tokens live in Windows Credential Manager, and sign-in tokens are encrypted with Windows DPAPI. Nothing secret is written to plain files or logs.
- **Mic:** you can turn it off in one click, which closes it completely.
- **Disconnecting:** every connection has a Disconnect button.
- **Sending:** sends happen only when your own words ask for them. If the AI tries to send something on its own initiative (for example after reading an email), you get an approval card. Risky in-app buttons (Send, Delete, Buy) and new calendar events always ask first.
- **Private mode** keeps email, calendar, messages, GitHub, Notion and Drive away from online AI.
- **Screen and clipboard:** the screen is captured only when you ask about it, and it is never saved.
- **What it won't do:** no self-bots, no unofficial WhatsApp tools, no deleting files, no purchases.
- **Activity log:** every action is recorded in the Activity tab.

## Requirements

- Windows 10 or 11
- Python 3.11 (`py -3.11` must work)
- A microphone and speakers
- About 1 GB of disk space for the Python packages and the speech models

## Install

```bat
git clone https://github.com/ishanp2013/Jarvis.git
cd Jarvis
setup.bat
```

`setup.bat` creates a Python environment in `%LOCALAPPDATA%\JarvisAssistant`, installs the packages, downloads the wake-word and speech models (about 160 MB, once) and can add a desktop shortcut.

## Run

| | |
|---|---|
| `Jarvis.bat` | Jarvis in its own window |
| `Jarvis-Web.bat` | Jarvis with the dashboard in your browser at http://127.0.0.1:8765 |
| `run_tests.bat` | the test suite (nothing on your PC is opened or closed) |

Then open **Settings** to choose an AI model and voice, and **Connections** to link the services you want. [SETUP.md](SETUP.md) has step-by-step instructions for every key and connection, plus costs and troubleshooting.

## Example commands

- "Hey Jarvis, open Spotify and play my liked songs"
- "Put Discord on the left and Opera on the right"
- "Do I have any unread emails?"
- "What's on my calendar tomorrow?"
- "What's the weather like?"
- "Search the web for the newest Python version"
- "Explain this error" (while the error is on screen)
- "Translate what I copied into English"
- "Send hi to Sam on WhatsApp"
- "Post 'build is green' in #dev on Slack"
- "Turn off the bedroom light"
- "Play Rocket League"
- "When I say study mode, close Discord and play lo-fi on YouTube"

## Project layout

```
jarvis/
  app.py          desktop window, events, game mode, floating orb
  brain.py        command router, tools, AI providers, streaming, screen reading
  speech.py       wake word, speech-to-text, text-to-speech
  listener.py     microphone loop
  providers.py    AI provider list
  config.py       settings and Credential Manager secrets
  web.py          local browser dashboard server
  tools/          one module per app or service (spotify, google, github, notion, …)
ui/               dashboard and floating orb (HTML, CSS, JS)
tests/            test suite
```

## Notes

- API keys are separate from chat subscriptions: ChatGPT Plus or Claude Pro don't include API use. Gemini, Groq, Mistral and OpenRouter have free options, and Ollama or LM Studio run on your own PC for free.
- Spotify, WhatsApp and app buttons are driven through the desktop apps, since there's no official free API for those. A big change to an app's layout can stop them working until Jarvis is updated.
- Windows only.
