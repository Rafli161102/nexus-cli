# nexus-cli

**Nexus Terminal (`nexus` / `ai`)** is an open-source, animated Terminal UI and unified CLI control hub that brings all your **AI CLIs**, **developer & GitHub CLIs**, **local scripts**, and **zero-key public APIs** together in one place.

Chat multi-turn like ChatGPT, Gemini, or Claude directly inside your terminal, switch or compare AI agents with one keystroke, stream local Ollama models with zero startup overhead, launch any CLI's native interactive UI inline or in a new terminal window, and query 2,500+ open-source GitHub APIs right from the prompt bar.

---

## Features

- **Unified AI CLI Hub**: Connects `opencode`, `gemini`, `codex`, `crush`, `copilot`, `dsh`, `aider`, `llm`, `mods`, `hermes`, `agy` / `claude`, and local `ollama` in a single interface.
- **Multi-Turn Conversational Chat & Persistence**: Maintains conversation context across turns (`opencode run -c`, `llm -c`, `crush -C`, `mods -C`, `gemini -r latest`, and full `messages[]` history for Ollama HTTP streaming), auto-saves sessions (`/sessions`, `/load`), and exports to Markdown (`/export`).
- **File Context Attachment (`@file`)**: Attach any local file directly into your prompt with `@file path/to/file` (with Tab autocomplete).
- **One-Command Setup & Self-Update**: Run `ai setup` to auto-wire local Ollama into `crush`, `mods`, `llm`, and `aider`, and `ai update` to pull the latest release from GitHub.
- **Real-Time Streaming & Animations**: Live token streaming with animated shimmer indicators, breathing status header, boot scanner, and instant cancellation (`Ctrl+X`).
- **Auto-Switch Fallback**: Automatically rotates models and agents when hitting rate limits, quota errors, or timeouts (`ai limits`, `ai fallback`).
- **Two Seamless Modes (`AI Chat` ↔ `Shell CLI`)**:
  - **AI Chat**: Chat naturally, route with `@agent <prompt>`, compare side-by-side with `@all <prompt>`, or use slash templates (`/explain`, `/fix`, `/review`, `/commit`).
  - **Shell CLI**: Toggle `/shell` (or click `AI Chat` pill) to run standard terminal commands directly without `!`.
- **Native TUI & New Window Launchers**:
  - **`Chat TUI` (`F2`)** or type a bare CLI name (`gemini`, `opencode`, `claude`, `lazygit`, etc.) to suspend Nexus cleanly and enter that CLI's full native interactive session, returning to Nexus on exit.
  - **`New Win` (`F4`)** or `/open <cli>` to pop open the selected CLI in a brand-new terminal window (macOS `Terminal.app` / Linux terminals).
- **Built-in Open-Source GitHub API Hub (`/api` / `ai api`)**:
  - Syncs `public-apis/public-apis` (2,500+ public APIs) and `models.dev/api.json` (320+ AI providers).
  - Live zero-key connectors for GitHub search & trending, Ollama, Open-Meteo weather, Wikipedia, ArXiv papers, HackerNews, CoinGecko crypto, Frankfurter currency rates, npm, PyPI, and arbitrary `GET` calls.
  - Pipe API results straight into AI: `/api hn 5 | summarize today's top AI news`.

---

## Installation

### Prerequisites

- **Python 3.10+**
- *(Recommended)* [`uv`](https://github.com/astral-sh/uv) for fast virtual environment setup
- *(Optional)* Any AI or developer CLIs you want to unify (see [Supported CLIs](#supported-clis))

### Quick Install (macOS & Linux)

```sh
git clone https://github.com/Rafli161102/nexus-cli.git
cd nexus-cli
chmod +x install.sh
./install.sh
ai setup   # Auto-wire local Ollama & sync agent configurations
```

Ensure `~/.local/bin` is in your `$PATH` (add to `~/.zshrc` or `~/.bashrc`):

```sh
export PATH="$HOME/.local/bin:$PATH"
```

*(On macOS, `./install.sh` also creates `~/Applications/Nexus Terminal.app` so you can launch Nexus Terminal from Spotlight or Launchpad.)*

### Install via `pip` / `uv`

```sh
git clone https://github.com/Rafli161102/nexus-cli.git
cd nexus-cli
uv tool install .   # or: pip install .
```

### Sync the Open-Source API Catalog (Optional)

```sh
ai api sync
```

This caches the latest `public-apis/public-apis` and `models.dev` catalogs locally for instant `/api search` and `/api models` lookups.

### Installing Open-Source AI & Dev CLIs (Optional)

Nexus auto-discovers CLIs already on your system. You can install popular open-source GitHub CLIs alongside it:

```sh
# Open-source AI CLIs
npm install -g @google/gemini-cli @openai/codex @charmland/crush @github/copilot @deepseek-ai/dsh
uv tool install aider-chat
uv tool install --with llm-ollama llm
brew install mods ollama

# Open-source GitHub & productivity CLIs
brew install gh lazygit fzf ripgrep bat eza glow jq
```

> **Tip for Local Ollama Users:** Start Ollama (`ollama serve`), pull a fast model such as `ollama pull llama3.2`, and if you use an HTTP proxy, add `export NO_PROXY="127.0.0.1,localhost,::1"` so local CLI requests bypass the proxy.

---

## Usage

### 1. Interactive Terminal UI (`nexus` / `ai`)

Launch the full TUI:

```sh
nexus
# or simply:
ai
```

#### Keyboard Shortcuts

| Key | Action |
|---|---|
| `Enter` | Send prompt / run command |
| `Tab` | Accept `@` / `/` / `!` autocomplete suggestion |
| `Up` / `Down` | Navigate prompt history or autocomplete list |
| `Ctrl+B` | Toggle left CLI & API dock |
| `Ctrl+T` | Cycle to next installed AI agent |
| `Ctrl+G` | Compare prompt across `@all` ready agents |
| `Ctrl+N` | Start a new chat session (clear context & stream) |
| `Ctrl+X` | Cancel/stop active AI thinking or streaming |
| `Ctrl+L` | Clear the conversation view |
| `F2` | Open active CLI's native interactive TUI in this window |
| `F3` | Open model picker modal |
| `F4` | Open active CLI in a new Terminal window |
| `Ctrl+P` | Open Command Palette |
| `Ctrl+Q` | Quit Nexus Terminal |

#### Slash Commands & Routing Inside TUI

- **Direct chat**: Type normally to chat with the active AI agent (multi-turn context enabled).
- **Attach file context**: `@file README.md summarize this file` (or type `@file ` + `Tab` to pick a file).
- **Save, resume, & export**: `/sessions` to list saved chats, `/load 1` to restore, `/export notes.md` to export as Markdown, `/new` for a fresh session.
- **Quick agent route**: `@gemini explain this error` or `@mods summarize README.md`
- **Parallel comparison**: `@all compare Python vs Rust for CLI tools`
- **Inline shell command**: `!git status`, `!rg TODO`, `!glow README.md`
- **Toggle Shell mode**: `/shell` — type `ls`, `git diff`, `gh pr list` without `!`
- **Open CLI in a new window**: `/open gemini` or `/open opencode`
- **Launch native TUI inline**: `/native crush` (or simply type `gemini`, `claude`, `opencode`, `lazygit`)
- **Prompt templates**: `/explain`, `/fix`, `/review`, `/commit`, `/summarize`
- **Open-source API Hub**:
  - `/api sync` — refresh GitHub `public-apis` + `models.dev` + local Ollama
  - `/api gh <query>` / `/api trending [topic]` — search GitHub repositories
  - `/api search <keyword> [--free]` — search 2,500+ public APIs
  - `/api weather <city>` · `/api wiki <topic>` · `/api arxiv <query>` · `/api hn` · `/api crypto` · `/api fx` · `/api npm <pkg>` · `/api pypi <pkg>` · `/api call <url>`
  - Pipe API data to AI: `/api weather Tokyo | suggest what to wear today`

---

### 2. Command-Line Mode (`ai`)

Use `ai` directly from any script or shell pipeline:

```sh
ai "explain what this repository does"   # One-shot to default agent
ai gemini "write a regex for emails"    # Target a specific agent
ai -a codex -m llama3.2:latest "..."    # Explicit agent and model override
ai all "compare approaches for caching" # Query all ready agents in parallel
ai --no-continue "fresh question"       # Start without prior session context
ai --simple                             # Lightweight plain-text REPL fallback

ai agents                               # List all AI agents and status
ai clis                                 # List all discovered AI, Dev, and Script CLIs
ai models opencode                      # List models for an agent
ai use opencode                         # Set default agent
ai doctor                               # Run binary & smoke diagnostics
ai setup                                # Auto-wire local Ollama & refresh configs
ai update                               # Pull latest updates from GitHub
ai limits                               # View quota/cooldown status
ai fallback                             # View or edit auto-switch fallback order
ai api weather San Francisco            # Query API Hub from the command line
ai config                               # Show config file location & effective config
```

---

## Supported CLIs

| Category | Tools |
|---|---|
| **AI Agents & Providers** | `opencode`, `gemini`, `codex`, `crush`, `copilot`, `dsh`, `aider`, `llm`, `mods`, `hermes`, `agy` (`claude`), `ollama` |
| **GitHub & Dev Tools** | `lazygit`, `gh`, `git`, `fzf`, `rg`, `bat`, `eza`, `glow`, `jq`, `uv`, `node`, `bun`, `pnpm`, `yarn`, `python3`, `brew`, `docker`, `claude` |
| **User Scripts** | Any executable scripts placed in `~/bin/` |

---

## Configuration

Nexus stores user overrides in `~/.config/ai-hub/config.json` (or `$AI_HUB_CONFIG_DIR/config.json`) and fallback state in `~/.config/ai-hub/limits.json`.

You can customize `default_agent`, `fallback_agents`, `auto_switch_agent`, per-agent `default_model`, `extra_args`, `timeout`, or add your own custom CLI agents in `agents`.

---

## License

Released under the [MIT License](LICENSE).
