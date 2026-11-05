# Ultron desktop release

The standard text assistant now retains the last six complete turns, sends tool results back
with their original call IDs, and preserves unsent input while a response is busy. Interrupt
checks stop a pending answer from dispatching later tools. Actions already dispatched cannot
be undone by interrupting. New chat clears the in-memory conversation context.

The automatic prompt context is generated locally for every request. It includes the current
task type, host platform, time, actual enabled tool names, and microphone availability. It does
not need a separate model call. Original user requests remain unchanged.

The first-run connection panel now offers an unsaved connection test, explicit model/URL/key
validation, masked key visibility, cancellation, and controls for desktop tools and voice.
Preferences are written atomically. Legacy generic keys are migrated to their original provider
so switching providers cannot accidentally forward the old key. Keys remain in the local ignored
configuration file; they are not encrypted by this release.

OpenAI-compatible, Ollama, Gemini, and Claude adapters retain structured conversation/tool
messages. HTTP redirects are refused and errors omit response bodies and credential values.
OpenAI requests use `max_completion_tokens` and `store: false` on Chat Completions. Model access,
capabilities, billing, and data retention still depend on your provider/account.

A missing microphone no longer tears down the standard text session. Text mode shows the actual
microphone status. The original Gemini Live voice path remains available and requires compatible
audio hardware and a Live-capable model. Tests do not establish real voice or hardware readiness.

## Run

Use Python 3.12 with Tkinter and the native audio/display libraries required by your OS.

Windows PowerShell, from the extracted `Ultron` folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py --doctor
.\.venv\Scripts\python.exe run.py
```

Linux/macOS, from the project folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py --doctor
.venv/bin/python run.py
```

On Debian/Ubuntu install native prerequisites such as `libportaudio2`, `libegl1`, `libgl1`,
`libxkbcommon0`, and `libpulse0` with the OS package manager. Run on a graphical desktop for
interaction. On the configured cloud machine, the saved startup instructions initialize the
local native-library prefix and writable cache locations.

Choose a provider, enter a model ID/key, optionally test it, then Save and start. Local compatible
OpenAI servers can use OpenRouter / Custom with a localhost base URL and a blank key. Ollama
requires its server and an installed model. Enable desktop tools only when you want the assistant
to dispatch the registered actions. Speak replies and Listen on launch can be left off for text
chat. Explore UI previews the workspace without starting a provider session.

No API key is bundled. Live provider use, real microphone/speech output, remote dashboard access,
Windows/macOS actions, and the full set of workstation plugins require validation on your target
machine. Browser automation also needs the optional Playwright browsers from `setup.py`.

## Validate and build

```bash
python -m unittest discover -s tests -v
python run.py --preview
python run.py --preview --workspace --output screenshots/workspace.png
python run.py --preview --size 1100x720 --output screenshots/minimum.png
python scripts/build_release.py
```

For headless Linux tests set `QT_QPA_PLATFORM=offscreen` and `QT_AUDIO_BACKEND=pulseaudio`.
The preview command sets an offscreen display automatically, opens the actual Qt UI, saves its
image, and exits without activating the provider, microphone, or desktop tools.

The build produces `dist/Ultron-source.zip` and its SHA-256 checksum. This is a source release,
not a standalone Windows executable. Extract it and follow the installation commands above.
Local configuration, credentials, memory databases, screenshots, logs, and virtual environments
are excluded from the release archive. CI definitions cover Linux and Windows; only the local
Linux validation was executed in this task.

Provider protocol reference: [OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat/create).
