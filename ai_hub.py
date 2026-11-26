#!/usr/bin/env python3
"""
nexus-cli (`ai` / `nexus`) — Unified Terminal & Control Hub for all AI and Dev CLIs.

Brings together AI CLIs (opencode, gemini, codex, crush, copilot, dsh, aider,
llm, mods, hermes, agy/claude, ollama), open-source GitHub & Dev CLIs, and
local scripts in one animated TUI and fast one-shot CLI.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP = "ai-hub"
ROOT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("AI_HUB_CONFIG_DIR", Path.home() / ".config" / APP))
CONFIG_PATH = CONFIG_DIR / "config.json"
LIMITS_PATH = CONFIG_DIR / "limits.json"
VENV_PYTHON = Path.home() / ".local" / "share" / "ai-hub" / "venv" / "bin" / "python"
TUI_SCRIPT = ROOT_DIR / "nexus_tui.py"
VERSION = "2.0.0"

# ---------------------------------------------------------------- styling
TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def c(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if TTY else s

def dim(s):    return c("2", s)
def bold(s):   return c("1", s)
def red(s):    return c("31", s)
def green(s):  return c("32", s)
def yellow(s): return c("33", s)
def blue(s):   return c("34", s)
def cyan(s):   return c("36", s)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Z]|\r")

def clean(text: str) -> str:
    return ANSI_RE.sub("", text).strip("\n")

def build_env(cfg: dict) -> dict[str, str]:
    env = dict(os.environ)
    local_bin = str(Path.home() / ".local" / "bin")
    opencode_bin = str(Path.home() / ".opencode" / "bin")
    path_parts = [p for p in env.get("PATH", "").split(":") if p]
    for p in (local_bin, opencode_bin, "/usr/local/bin", "/opt/homebrew/bin"):
        if os.path.isdir(p) and p not in path_parts:
            path_parts.insert(0, p)
    env["PATH"] = ":".join(path_parts)
    if os.path.exists("/etc/ssl/cert.pem"):
        env.setdefault("SSL_CERT_FILE", "/etc/ssl/cert.pem")
        env.setdefault("NODE_EXTRA_CA_CERTS", "/etc/ssl/cert.pem")
    no_proxy_cur = env.get("NO_PROXY") or env.get("no_proxy") or ""
    parts_np = [p.strip() for p in no_proxy_cur.split(",") if p.strip()]
    for host in ("127.0.0.1", "localhost", "::1"):
        if host not in parts_np:
            parts_np.append(host)
    env["NO_PROXY"] = ",".join(parts_np)
    env["no_proxy"] = env["NO_PROXY"]
    env.setdefault("OLLAMA_API_BASE", "http://127.0.0.1:11434")
    env.setdefault("OLLAMA_HOST", "http://127.0.0.1:11434")
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    env.update(cfg.get("env") or {})
    return env

# ---------------------------------------------------------------- defaults
def default_agents() -> dict:
    home = str(Path.home())
    return {
        "opencode": {
            "label": "OpenCode (multi-provider + Ollama)",
            "kind": "agent",
            "bin": shutil.which("opencode") or f"{home}/.opencode/bin/opencode",
            "one_shot": ["run", "{prompt}"],
            "model_flag": ["-m", "{model}"],
            "model_flag_pos": 1,
            "continue": ["-c"],
            "continue_pos": 1,
            "interactive": [],
            "default_model": "opencode/beam-free",
            "fallback_models": [
                "opencode/nemotron-3.5-lightning-free",
                "opencode/iceman-free",
                "opencode/big-pickle",
                "opencode/flint-40b-free",
                "opencode/hy4-flash-free",
                "ollama/llama3.2:latest",
            ],
            "extra_args": [],
            "timeout": 180,
            "note": "Fast multi-provider coding agent with free cloud models & local Ollama fallback.",
        },
        "gemini": {
            "label": "Gemini CLI (google-gemini/gemini-cli)",
            "kind": "agent",
            "bin": shutil.which("gemini") or "gemini",
            "one_shot": ["-p", "{prompt}"],
            "model_flag": ["-m", "{model}"],
            "continue": ["-r", "latest"],
            "interactive": [],
            "default_model": "",
            "extra_args": [],
            "timeout": 300,
            "no_discovery": True,
            "note": "Google Gemini CLI. Launch interactive mode (`F2`) once to authenticate.",
        },
        "codex": {
            "label": "Codex CLI (openai/codex · Ollama)",
            "kind": "agent",
            "bin": shutil.which("codex") or "codex",
            "one_shot": ["exec", "--oss", "--local-provider", "ollama", "--skip-git-repo-check", "{prompt}"],
            "model_flag": ["-m", "{model}"],
            "model_flag_pos": 1,
            "continue": [],
            "interactive": ["--oss", "--local-provider", "ollama"],
            "default_model": "llama3.2:latest",
            "fallback_models": ["qwen2.5:7b"],
            "extra_args": [],
            "timeout": 300,
            "no_discovery": True,
            "note": "OpenAI Codex CLI wired to local Ollama OSS provider (or use `codex login`).",
        },
        "crush": {
            "label": "Crush (charmbracelet/crush · Ollama)",
            "kind": "agent",
            "bin": shutil.which("crush") or "crush",
            "one_shot": ["run", "-y", "--quiet", "{prompt}"],
            "model_flag": [],
            "continue": ["-C"],
            "continue_pos": 1,
            "interactive": [],
            "default_model": "",
            "extra_args": [],
            "timeout": 300,
            "no_discovery": True,
            "note": "Charmbracelet Crush terminal AI assistant.",
        },
        "copilot": {
            "label": "GitHub Copilot CLI (github/copilot-cli)",
            "kind": "agent",
            "bin": shutil.which("copilot") or "copilot",
            "one_shot": ["-p", "{prompt}"],
            "model_flag": ["--model", "{model}"],
            "continue": [],
            "interactive": [],
            "default_model": "",
            "extra_args": [],
            "timeout": 300,
            "no_discovery": True,
            "note": "GitHub Copilot CLI. Run `copilot login` if not yet authenticated.",
        },
        "dsh": {
            "label": "DeepSeek Harness (deepseek-ai/dsh)",
            "kind": "agent",
            "bin": shutil.which("dsh") or "dsh",
            "one_shot": ["headless", "{prompt}"],
            "model_flag": [],
            "continue": [],
            "interactive": ["tui"],
            "default_model": "",
            "extra_args": [],
            "timeout": 300,
            "no_discovery": True,
            "note": "DeepSeek Harness open-source agent CLI (`dsh tui` / `dsh headless`).",
        },
        "aider": {
            "label": "Aider (Aider-AI/aider · Ollama)",
            "kind": "agent",
            "bin": shutil.which("aider") or f"{home}/.local/bin/aider",
            "one_shot": ["--no-git", "--no-show-model-warnings", "--map-tokens", "0", "--no-check-update", "--chat-mode", "ask", "--message", "{prompt}", "--yes-always", "--no-auto-commits"],
            "model_flag": ["--model", "{model}"],
            "continue": [],
            "interactive": [],
            "default_model": "ollama_chat/llama3.2:latest",
            "fallback_models": ["ollama_chat/qwen2.5:7b"],
            "extra_args": [],
            "timeout": 180,
            "no_discovery": True,
            "note": "Git-aware AI pair programmer wired to local Ollama.",
        },
        "llm": {
            "label": "LLM CLI (simonw/llm · Ollama)",
            "kind": "agent",
            "bin": shutil.which("llm") or f"{home}/.local/bin/llm",
            "one_shot": ["prompt", "{prompt}"],
            "model_flag": ["-m", "{model}"],
            "model_flag_pos": 1,
            "continue": ["-c"],
            "continue_pos": 1,
            "interactive": ["chat"],
            "default_model": "ollama-llama3.2",
            "fallback_models": ["ollama-qwen2.5"],
            "extra_args": [],
            "timeout": 120,
            "note": "Datasette LLM CLI wired to local Ollama & API plugins.",
        },
        "mods": {
            "label": "Mods (charmbracelet/mods · Ollama)",
            "kind": "agent",
            "bin": shutil.which("mods") or "mods",
            "one_shot": ["-q", "--raw", "{prompt}"],
            "model_flag": ["-m", "{model}"],
            "continue": ["-C"],
            "interactive": [],
            "default_model": "llama3.2:latest",
            "fallback_models": ["qwen2.5:7b"],
            "extra_args": [],
            "timeout": 120,
            "no_discovery": True,
            "note": "Charmbracelet AI on the command line (pipe-friendly, fast streaming).",
        },
        "hermes": {
            "label": "Hermes Agent",
            "kind": "agent",
            "bin": shutil.which("hermes") or f"{home}/.local/bin/hermes",
            "one_shot": ["chat", "-q", "{prompt}", "--oneshot", "-Q"],
            "model_flag": ["-m", "{model}"],
            "model_flag_pos": 1,
            "continue": [],
            "interactive": [],
            "default_model": "llama3.2:latest",
            "extra_args": ["--provider", "ollama-launch"],
            "timeout": 180,
            "note": "Hermes Agent with local Ollama launch provider.",
        },
        "agy": {
            "label": "Antigravity CLI (agy / claude)",
            "kind": "agent",
            "bin": shutil.which("agy") or f"{home}/.local/bin/agy",
            "one_shot": ["-p={prompt}"],
            "model_flag": ["--model", "{model}"],
            "continue": ["-c"],
            "continue_first": True,
            "interactive": [],
            "default_model": "",
            "extra_args": [],
            "timeout": 300,
            "no_discovery": True,
            "note": "Antigravity CLI. Run interactive mode once to authenticate.",
        },
        "ollama": {
            "label": "Ollama (local models · fast streaming)",
            "kind": "provider",
            "bin": shutil.which("ollama") or "ollama",
            "one_shot": ["run", "{model}", "{prompt}"],
            "model_flag": [],
            "continue": [],
            "interactive": ["run", "{model}"],
            "default_model": "llama3.2:latest",
            "fallback_models": ["qwen2.5:7b"],
            "extra_args": [],
            "timeout": 180,
            "note": "Local model provider via direct HTTP streaming (keep_alive=30m).",
        },
    }

def load_config() -> dict:
    cfg = {}
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as e:
        die(f"invalid config JSON: {CONFIG_PATH}: {e}")
    except OSError:
        cfg = {}
    agents = default_agents()
    for name, a in (cfg.get("agents") or {}).items():
        agents.setdefault(name, {})
        agents[name].update(a)
    for name, a in list(agents.items()):
        for k, v in list(a.items()):
            if v is None:
                a.pop(k)
    return {
        "default_agent": cfg.get("default_agent", "opencode"),
        "agents": agents,
        "cwd": cfg.get("cwd"),
        "env": cfg.get("env", {}),
        "auto_switch_agent": cfg.get("auto_switch_agent", True),
        "fallback_agents": cfg.get(
            "fallback_agents",
            ["opencode", "mods", "ollama", "llm", "hermes", "aider", "crush", "codex"],
        ),
        "max_fallback_attempts": cfg.get("max_fallback_attempts", 8),
        "max_model_fallbacks": cfg.get("max_model_fallbacks", 3),
    }

def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "default_agent": cfg["default_agent"],
        "cwd": cfg.get("cwd"),
        "env": cfg.get("env", {}),
        "auto_switch_agent": cfg.get("auto_switch_agent", True),
        "fallback_agents": cfg.get("fallback_agents", ["opencode", "mods", "ollama", "llm", "hermes", "aider", "crush", "codex"]),
        "max_fallback_attempts": cfg.get("max_fallback_attempts", 8),
        "max_model_fallbacks": cfg.get("max_model_fallbacks", 3),
        "agents": cfg["agents"],
    }
    CONFIG_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

def die(msg: str, code: int = 1):
    print(red("✗ " + msg), file=sys.stderr)
    sys.exit(code)

# ---------------------------------------------------------------- helpers
def find_bin(agent: dict) -> str | None:
    b = agent.get("bin") or ""
    if os.path.sep in b:
        if os.path.exists(b) and os.access(b, os.X_OK):
            return b
        return shutil.which(Path(b).name)
    return shutil.which(b)

def build_cmd(agent: dict, prompt: str, model: str, cont: bool, interactive: bool) -> list[str]:
    binpath = find_bin(agent)
    if not binpath:
        raise RuntimeError(f"binary not found: {agent.get('bin')}")
    model = model or agent.get("default_model") or ""
    args = list(agent.get("extra_args") or [])
    if interactive:
        tmpl = list(agent.get("interactive") or [])
    else:
        tmpl = list(agent.get("one_shot") or [])
    def sub(a: str) -> str:
        return a.replace("{prompt}", prompt).replace("{model}", model).replace("{bin}", binpath)
    rendered = [sub(a) for a in tmpl if not (a == "{model}" and not model)]
    model_args = [a.replace("{model}", model) for a in agent["model_flag"]] if (model and agent.get("model_flag")) else []
    cont_args = list(agent["continue"]) if (cont and agent.get("continue")) else []

    if interactive:
        return [binpath] + args + model_args + rendered

    cpos = agent.get("continue_pos")
    mpos = agent.get("model_flag_pos")
    if cont_args and cpos is not None:
        rendered = rendered[:cpos] + cont_args + rendered[cpos:]
        cont_args = []
        if mpos is not None and mpos >= cpos:
            mpos += len(agent["continue"])
    if model_args and mpos is not None:
        rendered = rendered[:mpos] + model_args + rendered[mpos:]
        model_args = []

    base_args = (cont_args + args) if (agent.get("continue_first") and cont_args) else (args + cont_args)
    return [binpath] + base_args + model_args + rendered

_PREP_DONE: set[str] = set()

def prep(name: str, agent: dict, cwd: str, env: dict) -> None:
    if name in _PREP_DONE:
        return
    _PREP_DONE.add(name)
    for cmd in agent.get("autostart") or []:
        binpath = find_bin(agent)
        if not binpath:
            return
        try:
            subprocess.run([binpath, *cmd], cwd=cwd, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except Exception:
            pass

def detect_local_model(binpath: str, name: str, cwd: str, env: dict) -> str:
    """Pick the first locally installed model (used for Ollama)."""
    try:
        if name == "ollama":
            r = subprocess.run([binpath, "list"], capture_output=True, text=True, timeout=15, cwd=cwd, env=env)
            lines = [ln for ln in (r.stdout or "").splitlines()[1:] if ln.strip()]
            if lines:
                return lines[0].split()[0]
    except Exception:
        pass
    return ""

def open_in_new_terminal(cmd: list[str], cwd: str) -> tuple[bool, str]:
    """Open a CLI command in a new Terminal window (macOS Terminal.app or Linux)."""
    shell_cmd = f"cd {shlex.quote(cwd)} && " + " ".join(shlex.quote(x) for x in cmd)
    if sys.platform == "darwin":
        escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
        apple = f'tell application "Terminal"\nactivate\ndo script "{escaped}"\nend tell'
        try:
            r = subprocess.run(["osascript", "-e", apple], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return True, shell_cmd
            return False, (r.stderr or r.stdout or "failed to open Terminal.app").strip()
        except Exception as e:
            return False, str(e)
    for term_bin, args in (
        ("kitty", ["--directory", cwd, "sh", "-c", f"{shell_cmd}; exec $SHELL"]),
        ("wezterm", ["start", "--cwd", cwd, "--", "sh", "-c", f"{shell_cmd}; exec $SHELL"]),
        ("gnome-terminal", ["--working-directory", cwd, "--", "sh", "-c", f"{shell_cmd}; exec $SHELL"]),
        ("x-terminal-emulator", ["-e", "sh", "-c", f"{shell_cmd}; exec $SHELL"]),
    ):
        found = shutil.which(term_bin)
        if found:
            try:
                subprocess.Popen([found, *args], start_new_session=True)
                return True, shell_cmd
            except Exception:
                continue
    return False, "No supported terminal emulator found"

def warm_ollama(model: str = "llama3.2:latest", timeout: int = 10) -> bool:
    """Pre-warm Ollama model in RAM (keep_alive=30m) for faster subsequent replies."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps({"model": model, "prompt": "", "keep_alive": "30m"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with opener.open(req, timeout=timeout) as r:
            r.read()
        return True
    except Exception:
        return False

def stream_ollama_http(prompt: str, model: str, timeout: int | None,
                       on_chunk=None, cancel_event=None,
                       messages: list[dict] | None = None) -> dict:
    """Stream directly from the Ollama HTTP API without CLI startup overhead."""
    t0 = time.time()
    model = model or "llama3.2:latest"
    chat_msgs = list(messages or []) + [{"role": "user", "content": prompt}]
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps({
                "model": model,
                "messages": chat_msgs,
                "stream": True,
                "keep_alive": "30m",
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        chunks: list[str] = []
        with opener.open(req, timeout=timeout or 180) as resp:
            for raw in resp:
                if cancel_event is not None and cancel_event.is_set():
                    return {"agent": "ollama", "ok": False, "output": "".join(chunks),
                            "error": "cancelled by user", "seconds": round(time.time() - t0, 1), "cmd": ["ollama-http", model]}
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                tok = (d.get("message") or {}).get("content", "")
                if tok:
                    chunks.append(tok)
                    if on_chunk is not None:
                        on_chunk("".join(chunks))
                if d.get("done"):
                    break
        return {
            "agent": "ollama", "ok": True, "output": "".join(chunks).strip("\n"),
            "error": "", "returncode": 0, "seconds": round(time.time() - t0, 1),
            "cmd": ["ollama-http", model],
        }
    except Exception as e:
        return {"agent": "ollama", "ok": False, "output": "", "error": str(e),
                "seconds": round(time.time() - t0, 1), "cmd": ["ollama-http", model]}

def run_one(name: str, agent: dict, prompt: str, model: str, cont: bool,
            cwd: str, env: dict, timeout: int | None,
            on_chunk=None, cancel_event=None,
            messages: list[dict] | None = None) -> dict:
    t0 = time.time()
    try:
        prep(name, agent, cwd, env)
        model = model or agent.get("default_model") or ""
        if agent.get("kind") == "provider" and not model:
            bp = find_bin(agent)
            if bp:
                model = detect_local_model(bp, name, cwd, env)
        if name == "ollama":
            if not model:
                return {
                    "agent": name, "ok": False, "output": "",
                    "error": "No local Ollama model found. Run `ollama pull llama3.2` first.",
                    "seconds": round(time.time() - t0, 1), "cmd": [],
                }
            res_http = stream_ollama_http(prompt, model, timeout, on_chunk=on_chunk, cancel_event=cancel_event, messages=messages)
            if res_http["ok"] or (cancel_event is not None and cancel_event.is_set()):
                return res_http
        cmd = build_cmd(agent, prompt, model, cont, interactive=False)
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        sel = selectors.DefaultSelector()
        assert proc.stdout is not None and proc.stderr is not None
        os.set_blocking(proc.stdout.fileno(), False)
        os.set_blocking(proc.stderr.fileno(), False)
        sel.register(proc.stdout, selectors.EVENT_READ, "out")
        sel.register(proc.stderr, selectors.EVENT_READ, "err")
        out_buf = bytearray()
        err_buf = bytearray()
        last_emit = 0.0
        cancelled = False
        timed_out = False
        try:
            while sel.get_map():
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if timeout is not None and (time.time() - t0) > timeout:
                    timed_out = True
                    break
                events = sel.select(timeout=0.08)
                for key, _ in events:
                    try:
                        chunk = os.read(key.fd, 4096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    if key.data == "out":
                        out_buf.extend(chunk)
                        if on_chunk is not None and (time.time() - last_emit) >= 0.08:
                            txt = clean(out_buf.decode("utf-8", errors="replace"))
                            if txt:
                                on_chunk(txt)
                                last_emit = time.time()
                    else:
                        err_buf.extend(chunk)
            if cancelled or timed_out:
                try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception: proc.kill()
                proc.wait()
                out_s = clean(out_buf.decode("utf-8", errors="replace"))
                err_s = "cancelled by user" if cancelled else f"timeout {timeout}s"
                return {"agent": name, "ok": False, "output": out_s,
                        "error": err_s, "seconds": round(time.time() - t0, 1), "cmd": cmd}
            proc.wait()
        finally:
            sel.close()
        out_s = clean(out_buf.decode("utf-8", errors="replace"))
        err_s = clean(err_buf.decode("utf-8", errors="replace"))
        if on_chunk is not None and out_s:
            on_chunk(out_s)
        rc = proc.returncode
        return {
            "agent": name,
            "ok": rc == 0,
            "output": out_s,
            "error": err_s if rc != 0 else "",
            "returncode": rc,
            "seconds": round(time.time() - t0, 1),
            "cmd": cmd,
        }
    except KeyboardInterrupt:
        raise
    except Exception as e:
        return {"agent": name, "ok": False, "output": "", "error": str(e),
                "seconds": round(time.time() - t0, 1), "cmd": []}

# ---------------------------------------------------------------- discovery
DEV_CLI_CATALOG = [
    ("lazygit", "Git interactive TUI (jesseduffield/lazygit)", True),
    ("gh", "GitHub official CLI (cli/cli)", False),
    ("git", "Git distributed version control", False),
    ("fzf", "Interactive fuzzy finder (junegunn/fzf)", True),
    ("rg", "Ripgrep ultra-fast code search (BurntSushi/ripgrep)", False),
    ("bat", "Cat with syntax highlighting (sharkdp/bat)", False),
    ("eza", "Modern ls replacement (eza-community/eza)", False),
    ("glow", "Terminal Markdown reader (charmbracelet/glow)", False),
    ("jq", "JSON processor CLI (jqlang/jq)", False),
    ("uv", "Astral ultra-fast Python package manager", False),
    ("node", "Node.js JavaScript runtime", False),
    ("bun", "Bun all-in-one JS/TS runtime", False),
    ("pnpm", "Fast disk-efficient Node package manager", False),
    ("yarn", "Yarn package manager", False),
    ("python3", "Python 3 interpreter", False),
    ("brew", "Homebrew package manager", False),
    ("docker", "Container runtime CLI", False),
    ("claude", "Claude Code CLI", True),
]

def discover_all_clis(cfg: dict, env: dict | None = None) -> dict[str, list[dict]]:
    """Discover all CLIs on the system: AI agents, Dev/GitHub tools, and ~/bin scripts."""
    search_path = (env or {}).get("PATH") or os.environ.get("PATH", "")
    ai_items = []
    for name, a in cfg["agents"].items():
        bp = find_bin(a)
        ai_items.append({
            "name": name,
            "category": "ai",
            "label": a.get("label", name),
            "kind": a.get("kind", "agent"),
            "path": bp or "",
            "installed": bool(bp),
            "interactive": True,
            "default": name == cfg.get("default_agent"),
            "note": a.get("note", ""),
        })

    dev_items = []
    for name, desc, is_tui in DEV_CLI_CATALOG:
        bp = shutil.which(name, path=search_path)
        if not bp:
            for extra in (Path.home() / ".local" / "bin" / name, Path("/usr/local/bin") / name, Path("/opt/homebrew/bin") / name):
                if extra.exists() and os.access(extra, os.X_OK):
                    bp = str(extra)
                    break
        dev_items.append({
            "name": name,
            "category": "dev",
            "label": desc,
            "kind": "tui" if is_tui else "cli",
            "path": bp or "",
            "installed": bool(bp),
            "interactive": is_tui,
        })

    script_items = []
    user_bin = Path.home() / "bin"
    if user_bin.is_dir():
        for p in sorted(user_bin.iterdir(), key=lambda x: x.name.lower()):
            if p.name.startswith(".") or p.is_dir():
                continue
            if os.access(p, os.X_OK):
                script_items.append({
                    "name": p.name,
                    "category": "scripts",
                    "label": f"User script (~/bin/{p.name})",
                    "kind": "script",
                    "path": str(p),
                    "installed": True,
                    "interactive": False,
                })

    return {"ai": ai_items, "dev": dev_items, "scripts": script_items}

# ---------------------------------------------------------------- models
def list_models(name: str, agent: dict, cwd: str, env: dict) -> list[str]:
    binpath = find_bin(agent)
    if not binpath:
        return []
    probes = {
        "ollama":   [["list"]],
        "opencode": [["models"]],
        "agy":      [["models"]],
        "hermes":   [["status"]],
        "llm":      [["models", "list"]],
    }.get(name, [["models"], ["--list-models"]])
    for args in probes:
        try:
            r = subprocess.run([binpath, *args], capture_output=True, text=True,
                               timeout=45, cwd=cwd, env=env)
        except Exception:
            continue
        text = clean((r.stdout or "") + "\n" + (r.stderr or ""))
        if r.returncode == 0 and text.strip():
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            lines = [ln for ln in lines if not ln.lower().startswith(("usage", "options", "fetching", "error"))]
            if name == "ollama":
                lines = [ln.split()[0] for ln in lines if not ln.upper().startswith("NAME")]
            elif name == "opencode":
                lines = [ln for ln in lines if "/" in ln and not ln.startswith((">", "ERROR", " "))]
            elif name == "hermes":
                m = re.search(r"Model:\s+(\S+)", text)
                lines = [m.group(1)] if m else []
            elif name == "llm":
                lines = [ln.split(":", 1)[1].strip().split()[0] if ":" in ln else ln.split()[0] for ln in lines]
            if lines:
                return lines[:60]
    return []

# ---------------------------------------------------------------- output
def print_result(res: dict, show_header: bool = True, header_stream=None) -> None:
    label = res["agent"]
    if show_header:
        status = green("✓") if res["ok"] else red("✗")
        secs = res.get("seconds", 0)
        print(f"{status} {bold(label)} {dim('(' + str(secs) + 's)')}", file=(header_stream or sys.stderr))
    if res["ok"]:
        if res["output"]:
            print(res["output"])
    else:
        if res["output"]:
            print(res["output"])
        err = res.get("error") or f"failed (rc={res.get('returncode','?')})"
        print(red(err), file=sys.stderr)

def agent_table(cfg: dict, cwd: str, env: dict) -> None:
    print(bold("INSTALLED AI AGENTS") + dim("   (use `ai use <name>` to set default, `ai` to open Nexus Terminal)\n"))
    for name, a in cfg["agents"].items():
        bp = find_bin(a)
        mark = green("●") if bp else red("○")
        kind = dim(f"[{a.get('kind','agent')}]")
        star = yellow(" ★ default") if name == cfg["default_agent"] else ""
        pad = " " * max(1, 12 - len(name))
        print(f"  {mark} {bold(name)}{pad}{kind} {a.get('label','')}{star}")
        print(dim(f"      {bp or a.get('bin','')}"))
        if a.get("note"):
            print(dim(f"      {a['note']}"))
    print()

def cmd_clis(cfg: dict, env: dict) -> int:
    catalog = discover_all_clis(cfg, env)
    sections = [
        ("AI AGENTS & MODEL CLIs", catalog["ai"]),
        ("GITHUB & DEV CLIs", catalog["dev"]),
        ("USER SCRIPTS (~/bin)", catalog["scripts"]),
    ]
    for title, items in sections:
        ready = sum(1 for i in items if i["installed"])
        print(bold(title) + dim(f"  ({ready}/{len(items)} ready)"))
        for it in items:
            mark = green("●") if it["installed"] else red("○")
            star = yellow(" ★") if it.get("default") else ""
            pad = " " * max(1, 22 - len(it["name"]))
            print(f"  {mark} {bold(it['name'])}{pad}{dim(it['label'])}{star}")
        print()
    return 0

# ---------------------------------------------------------------- commands
def cmd_doctor(cfg: dict, targets: list[str], cwd: str, env: dict) -> int:
    print(bold(f"ai doctor — {APP} v{VERSION}\n"))
    names = targets or list(cfg["agents"])
    rc = 0
    for name in names:
        a = cfg["agents"].get(name)
        if not a:
            print(red(f"✗ {name}: unknown agent")); rc = 1; continue
        bp = find_bin(a)
        print(f"{bold(name)} {dim(a.get('label',''))}")
        print(f"  binary : {green(bp) if bp else red('NOT FOUND: ' + str(a.get('bin','')))}")
        if not bp:
            rc = 1; print(); continue
        ver = None
        for flag in ("--version", "-v"):
            try:
                r = subprocess.run([bp, flag], capture_output=True, text=True, timeout=15, cwd=cwd, env=env)
                t = clean((r.stdout or "") + (r.stderr or ""))
                if r.returncode == 0 and t:
                    ver = t.splitlines()[0][:80]; break
            except Exception:
                pass
        print(f"  version: {ver or dim('unable to check')}")
        if not targets:
            print(dim("  smoke  : testing 'ok'..."), end="", flush=True)
            res = run_one(name, a, "reply with only the word ok", "", False, cwd, env, 90)
            print("\r" + " " * 40 + "\r", end="")
            print(f"  smoke  : {green('OK') if res['ok'] else red('FAIL')}"
                  + ("" if res['ok'] else dim(f" — {(res.get('error') or res['output'])[:200]}")))
            if not res["ok"]:
                rc = 1
                if a.get("note"):
                    print(dim(f"  info   : {a['note']}"))
        print()
    cfg_exists = False
    try:
        cfg_exists = CONFIG_PATH.exists()
    except OSError:
        pass
    print(f"config   : {CONFIG_PATH}{'' if cfg_exists else dim(' (not created yet — run `ai config` to inspect)')}")
    print(f"tui      : {green(str(TUI_SCRIPT)) if TUI_SCRIPT.exists() and VENV_PYTHON.exists() else yellow('fallback text REPL')}")
    print(f"default  : {cfg['default_agent']}")
    print(f"cwd      : {cwd}")
    return rc

def cmd_models(cfg: dict, name: str, cwd: str, env: dict) -> int:
    a = cfg["agents"].get(name)
    if not a: die(f"unknown agent: {name}")
    models = list_models(name, a, cwd, env)
    print(bold(f"MODELS {name}") + dim(f"  ({len(models)} found)"))
    if not models:
        print(dim("could not fetch model list; set manually with `ai -a NAME -m MODEL ...`"))
        cur = a.get("default_model")
        if cur: print(f"default_model: {cur}")
        return 1
    for m in models: print(f"  {m}")
    if a.get("default_model"):
        print(dim(f"\ncurrent default_model: {a['default_model']}"))
    return 0

def cmd_use(cfg: dict, name: str) -> int:
    if name not in cfg["agents"]: die(f"unknown agent: {name}. See `ai agents`.")
    cfg["default_agent"] = name
    save_config(cfg)
    print(green(f"✓ default agent is now: {name}"))
    return 0

def cmd_config(cfg: dict, edit: bool) -> int:
    if not CONFIG_PATH.exists():
        save_config(cfg)
    print(f"config file: {CONFIG_PATH}\n")
    print(json.dumps(json.loads(CONFIG_PATH.read_text()), indent=2, ensure_ascii=False))
    if edit:
        ed = os.environ.get("EDITOR", "open")
        subprocess.run([ed, str(CONFIG_PATH)])
    return 0

def cmd_setup(cfg: dict, env: dict) -> int:
    """Auto-wire local Ollama & refresh config for all installed AI CLIs."""
    home = Path.home()
    print(bold("nexus setup — auto-configuring AI CLIs & local providers\n"))

    # Detect local Ollama models
    ollama_models: list[str] = []
    ol_bin = shutil.which("ollama", path=env.get("PATH"))
    if ol_bin:
        try:
            r = subprocess.run([ol_bin, "list"], capture_output=True, text=True, timeout=10, env=env)
            for ln in (r.stdout or "").splitlines()[1:]:
                if ln.strip():
                    ollama_models.append(ln.split()[0])
        except Exception:
            pass
    pref_model = "llama3.2:latest" if "llama3.2:latest" in ollama_models else (ollama_models[0] if ollama_models else "llama3.2:latest")
    print(f"  Ollama : {green(', '.join(ollama_models)) if ollama_models else yellow('no local models found (`ollama pull llama3.2`)')}")

    # 1. Crush (~/.config/crush/crush.json)
    if find_bin(cfg["agents"]["crush"]):
        crush_dir = home / ".config" / "crush"
        crush_dir.mkdir(parents=True, exist_ok=True)
        crush_models = ollama_models or [pref_model]
        crush_cfg = {
            "$schema": "https://charm.land/crush.json",
            "providers": {
                "ollama": {
                    "name": "Ollama Local",
                    "type": "openai-compat",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "models": [
                        {"id": m, "name": m, "context_window": 32768, "default_max_tokens": 4096}
                        for m in crush_models
                    ],
                }
            },
            "models": {
                "large": {"model": pref_model, "provider": "ollama"},
                "small": {"model": pref_model, "provider": "ollama"},
            },
        }
        (crush_dir / "crush.json").write_text(json.dumps(crush_cfg, indent=2) + "\n")
        print(f"  crush  : {green('configured')} -> {crush_dir / 'crush.json'} ({pref_model})")

    # 2. llm (extra-openai-models.yaml + key + default)
    if find_bin(cfg["agents"]["llm"]):
        llm_dir = home / ("Library/Application Support/io.datasette.llm" if sys.platform == "darwin" else ".config/io.datasette.llm")
        llm_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for m in (ollama_models or [pref_model]):
            slug = "ollama-" + m.split(":")[0]
            lines.append(f'- model_id: {slug}\n  model_name: {m}\n  api_base: "http://127.0.0.1:11434/v1"\n  api_key_name: ollama')
        (llm_dir / "extra-openai-models.yaml").write_text("\n".join(lines) + "\n")
        kf = llm_dir / "keys.json"
        keys = _load_json(kf, {})
        keys.setdefault("ollama", "ollama")
        kf.write_text(json.dumps(keys, indent=2) + "\n")
        def_slug = "ollama-" + pref_model.split(":")[0]
        (llm_dir / "default_model.txt").write_text(def_slug + "\n")
        print(f"  llm    : {green('configured')} -> default={def_slug}")

    # 3. mods (mods.yml)
    if find_bin(cfg["agents"]["mods"]):
        mods_dir = home / ("Library/Application Support/mods" if sys.platform == "darwin" else ".config/mods")
        mods_yml = mods_dir / "mods.yml"
        if mods_yml.exists():
            txt = mods_yml.read_text()
            txt = re.sub(r"^default-api:.*$", "default-api: local", txt, count=1, flags=re.M)
            txt = re.sub(r"^default-model:.*$", f"default-model: {pref_model}", txt, count=1, flags=re.M)
            if "  local:" not in txt and "apis:\n" in txt:
                txt = txt.replace("apis:\n", (
                    "apis:\n"
                    "  local:\n"
                    "    base-url: http://127.0.0.1:11434/v1\n"
                    "    api-key: ollama\n"
                    "    models:\n"
                    f"      \"{pref_model}\":\n"
                    "        max-input-chars: 128000\n"
                ), 1)
            mods_yml.write_text(txt)
            print(f"  mods   : {green('configured')} -> {mods_yml} ({pref_model})")

    # 4. aider (~/.aider.conf.yml)
    if find_bin(cfg["agents"]["aider"]):
        aider_conf = home / ".aider.conf.yml"
        if not aider_conf.exists():
            aider_conf.write_text(f"model: ollama_chat/{pref_model}\nauto-commits: false\nmap-tokens: 0\n")
        print(f"  aider  : {green('configured')} -> {aider_conf}")

    # 5. Refresh ai-hub config.json with latest defaults while keeping user env/cwd
    fresh = {
        "default_agent": cfg.get("default_agent", "opencode"),
        "cwd": cfg.get("cwd"),
        "env": cfg.get("env", {}),
        "auto_switch_agent": cfg.get("auto_switch_agent", True),
        "fallback_agents": ["opencode", "mods", "ollama", "llm", "hermes", "aider", "crush", "codex"],
        "max_fallback_attempts": cfg.get("max_fallback_attempts", 8),
        "max_model_fallbacks": cfg.get("max_model_fallbacks", 3),
        "agents": default_agents(),
    }
    save_config(fresh)
    print(f"  ai-hub : {green('synced')} -> {CONFIG_PATH}")
    print(dim("\nCloud CLIs (optional): run `F2` in Nexus on gemini / codex / copilot / agy to sign in."))
    return 0

def cmd_update() -> int:
    """Update nexus-cli from its git remote."""
    if not (ROOT_DIR / ".git").exists():
        die(f"{ROOT_DIR} is not a git repository.")
    print(bold("Updating nexus-cli from GitHub..."))
    r = subprocess.run(["git", "-C", str(ROOT_DIR), "pull", "--ff-only"], text=True)
    if r.returncode != 0:
        return r.returncode
    inst = ROOT_DIR / "install.sh"
    if inst.exists() and VENV_PYTHON.exists():
        uv_bin = shutil.which("uv")
        req = ROOT_DIR / "requirements.txt"
        if uv_bin and req.exists():
            subprocess.run([uv_bin, "pip", "install", "--python", str(VENV_PYTHON), "-r", str(req)])
    print(green("✓ nexus-cli is up to date."))
    return 0

def get_auth_status(cfg: dict, env: dict) -> list[dict]:
    """Inspect free-tier availability and login sync status for all AI CLIs."""
    home = Path.home()
    ollama_models: list[str] = []
    ol_bin = shutil.which("ollama", path=env.get("PATH"))
    if ol_bin:
        try:
            r = subprocess.run([ol_bin, "list"], capture_output=True, text=True, timeout=5, env=env)
            ollama_models = [ln.split()[0] for ln in (r.stdout or "").splitlines()[1:] if ln.strip()]
        except Exception:
            pass
    has_ollama = bool(ollama_models)

    gemini_synced = bool(
        env.get("GEMINI_API_KEY")
        or env.get("GOOGLE_APPLICATION_CREDENTIALS")
        or (home / ".gemini" / "oauth_creds.json").exists()
        or (home / ".gemini" / "google_accounts.json").exists()
    )
    cop_cfg = _load_json(home / ".copilot" / "config.json", {})
    copilot_synced = bool(
        env.get("COPILOT_GITHUB_TOKEN")
        or env.get("GITHUB_TOKEN")
        or (isinstance(cop_cfg, dict) and (cop_cfg.get("logged_in_users") or cop_cfg.get("last_logged_in_user")))
    )
    codex_cloud = bool(env.get("OPENAI_API_KEY") or (home / ".codex" / "auth.json").exists())
    dsh_synced = bool(env.get("DEEPSEEK_API_KEY") or (home / ".dsh" / "credentials.json").exists())
    agy_synced = bool(env.get("ANTHROPIC_API_KEY") or (home / ".claude" / ".credentials.json").exists())

    specs = {
        "opencode": ("free-cloud", True, None, "Free cloud models + Ollama fallback"),
        "ollama": ("free-local", has_ollama, None, f"Local ({len(ollama_models)} models)" if has_ollama else "Run `ollama pull llama3.2`"),
        "mods": ("free-local", has_ollama, None, "Wired to local Ollama (no login needed)"),
        "llm": ("free-local", has_ollama, None, "Wired to local Ollama (no login needed)"),
        "crush": ("free-local", has_ollama, None, "Wired to local Ollama (no login needed)"),
        "aider": ("free-local", has_ollama, None, "Wired to local Ollama (no login needed)"),
        "hermes": ("free-local", has_ollama, None, "Local Ollama launch provider"),
        "codex": ("free-local", has_ollama or codex_cloud, ["login"], "Synced (ChatGPT/API)" if codex_cloud else "Free via Ollama (`codex login` optional)"),
        "gemini": ("free-login", gemini_synced, [], "Google Free Tier (synced)" if gemini_synced else "Google Free Tier — sign in with Google"),
        "copilot": ("free-login", copilot_synced, ["login"], "Copilot Free (synced)" if copilot_synced else "Copilot Free — sign in with GitHub"),
        "dsh": ("account", dsh_synced, ["tui"], "Synced" if dsh_synced else "Requires DeepSeek account or DEEPSEEK_API_KEY"),
        "agy": ("account", agy_synced, [], "Synced" if agy_synced else "Sign in via interactive `agy` session"),
    }

    rows = []
    for name, a in cfg["agents"].items():
        bp = find_bin(a)
        tier, synced, login_args, detail = specs.get(name, ("account", False, [], a.get("note", "")))
        if not bp:
            status = "missing"
        elif synced:
            status = "ready"
        else:
            status = "login-needed"
        rows.append({
            "name": name,
            "installed": bool(bp),
            "tier": tier,
            "synced": bool(bp and synced),
            "status": status,
            "detail": detail if bp else f"Not installed ({a.get('bin')})",
            "login_args": login_args,
        })
    return rows

def cmd_auth(cfg: dict, env: dict) -> int:
    rows = get_auth_status(cfg, env)
    print(bold("NEXUS AI AUTH & FREE TIERS\n"))
    for title, pred in (
        ("READY NOW (Free Cloud / Local Ollama)", lambda r: r["status"] == "ready"),
        ("LOGIN TO SYNC (Free Tier / Account)", lambda r: r["status"] == "login-needed"),
        ("NOT INSTALLED", lambda r: r["status"] == "missing"),
    ):
        grp = [r for r in rows if pred(r)]
        if not grp:
            continue
        print(bold(title))
        for r in grp:
            mark = green("●") if r["status"] == "ready" else (yellow("◐") if r["status"] == "login-needed" else red("○"))
            tag = dim(f"[{r['tier']}]")
            hint = cyan(f"  → ai login {r['name']}") if r["status"] == "login-needed" and r["login_args"] is not None else ""
            print(f"  {mark} {bold(r['name']):<12} {tag:<14} {r['detail']}{hint}")
        print()
    return 0

def cmd_login(cfg: dict, name: str, cwd: str, env: dict) -> int:
    a = cfg["agents"].get(name)
    if not a:
        die(f"unknown agent: {name}")
    bp = find_bin(a)
    if not bp:
        die(f"{name} binary not found")
    rows = {r["name"]: r for r in get_auth_status(cfg, env)}
    login_args = rows.get(name, {}).get("login_args")
    if login_args is None:
        print(green(f"✓ {name} uses local Ollama / free models and needs no login."))
        return 0
    print(cyan(f"◈ Launching {name} login — once signed in, Nexus will use it automatically...\n"))
    rc = subprocess.call([bp, *login_args], cwd=cwd, env=env)
    if rc == 0:
        print(green(f"\n✓ {name} session finished. Run `ai auth` to verify sync status."))
    return rc

# ---------------------------------------------------------------- ask
def ask(cfg: dict, name: str, prompt: str, model: str, cont: bool,
        cwd: str, env: dict, timeout: int | None,
        on_chunk=None, cancel_event=None, messages: list[dict] | None = None) -> dict:
    a = cfg["agents"].get(name)
    if not a: raise RuntimeError(f"unknown agent: {name}")
    return run_one(name, a, prompt, model, cont, cwd, env,
                   timeout if timeout is not None else a.get("timeout", 300),
                   on_chunk=on_chunk, cancel_event=cancel_event, messages=messages)

# ---------------------------------------------------------------- fallback
MODEL_SWITCH = {"rate_limit", "credits", "quota", "model", "overloaded", "timeout"}
AGENT_SWITCH = MODEL_SWITCH | {"auth", "unknown"}

LIMIT_PATTERNS = [
    (re.compile(r"rate.?limit|too many requests|\b429\b|resource_exhausted|usage.?limit|requests per|quota.*exceed|exceed.*quota", re.I), "rate_limit"),
    (re.compile(r"\b402\b|credits?|billing|insufficient|no credits|out of credits|not have access|entitlement|payment required|add usage credits", re.I), "credits"),
    (re.compile(r"not recognized|unknown model|model not found|invalid model|no such model|does not exist|not a known model|model.*unavailable|unknown model key", re.I), "model"),
    (re.compile(r"overloaded|\b503\b|\b529\b|\b500\b|\b502\b|temporarily unavailable|server error|capacity|try again later", re.I), "overloaded"),
    (re.compile(r"timed? out|timeout|deadline exceeded", re.I), "timeout"),
    (re.compile(r"authentication|unauthorized|\b401\b|not logged in|please.*log in|oauth|permission denied|auth failed|api key|login required", re.I), "auth"),
    (re.compile(r"gateway disconnected|service_start_failed|gateway inaccessible", re.I), "auth"),
]

COOLDOWN_SEC = {"rate_limit": 60, "overloaded": 30, "timeout": 15, "credits": 3600, "quota": 300, "model": 0, "auth": 0, "unknown": 0}

def classify(text: str) -> str:
    t = text or ""
    for rx, cat in LIMIT_PATTERNS:
        if rx.search(t):
            return cat
    return "unknown"

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def load_limits() -> dict:
    return _load_json(LIMITS_PATH, {})

def save_limits(lim: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LIMITS_PATH.write_text(json.dumps(lim, indent=2) + "\n")
    except Exception:
        pass

def record_limit(name: str, res: dict) -> str:
    text = (res.get("error") or "") + "\n" + (res.get("output") or "")
    cat = classify(text) if not res.get("ok") else ""
    lim = load_limits()
    ent = lim.get(name, {"count": 0})
    if res.get("ok"):
        ent["last_ok"] = time.time()
    else:
        ent["count"] = ent.get("count", 0) + 1
        ent["last_error_at"] = time.time()
        ent["last_error"] = (res.get("error") or res.get("output") or "")[:300]
        ent["category"] = cat
        ent["cooldown_until"] = time.time() + COOLDOWN_SEC.get(cat, 0)
    lim[name] = ent
    save_limits(lim)
    return cat

def agent_ready(name: str, a: dict, now: float) -> bool:
    if not find_bin(a):
        return False
    ent = load_limits().get(name) or {}
    cd = ent.get("cooldown_until", 0)
    return not (cd and cd > now)

def fallback_order(cfg: dict, name: str) -> list[str]:
    order = [name]
    for n in (cfg.get("fallback_agents") or []):
        if n in cfg["agents"] and n not in order:
            order.append(n)
    for n, a in cfg["agents"].items():
        if n not in order and a.get("kind", "agent") in ("agent", "provider"):
            order.append(n)
    now = time.time()
    head, tail = order[:1], order[1:]
    tail.sort(key=lambda n: 0 if agent_ready(n, cfg["agents"][n], now) else 1)
    return head + tail

def agent_fallback_models(agent: dict) -> list[str]:
    return list(agent.get("fallback_models") or [])

def discovered_models(name: str, agent: dict, cwd: str, env: dict) -> list[str]:
    try:
        return list_models(name, agent, cwd, env)
    except Exception:
        return []

def ask_with_fallback(cfg: dict, name: str, prompt: str, model: str, cont: bool,
                      cwd: str, env: dict, timeout: int | None,
                      allow_agent_switch: bool | None = None,
                      quiet_notice: bool = False,
                      on_chunk=None, cancel_event=None,
                      on_attempt=None, messages: list[dict] | None = None) -> dict:
    """Try (agent, model); auto-switch models then agents on limit/error."""
    if allow_agent_switch is None:
        allow_agent_switch = bool(cfg.get("auto_switch_agent", True))
    order = fallback_order(cfg, name)
    tried: set[tuple[str, str]] = set()
    attempts: list[dict] = []
    last: dict | None = None
    max_attempts = int(cfg.get("max_fallback_attempts", 8))

    for idx, ag_name in enumerate(order):
        if cancel_event is not None and cancel_event.is_set():
            break
        a = cfg["agents"].get(ag_name)
        if not a or not find_bin(a):
            continue
        is_primary = idx == 0 and ag_name == name
        base_model = (model or a.get("default_model") or "") if is_primary else (a.get("default_model") or "")
        cands = [base_model]
        cands += agent_fallback_models(a)
        disc = [] if a.get("no_discovery") else discovered_models(ag_name, a, cwd, env)
        if a.get("kind") == "provider":
            cands = ([base_model] if base_model else []) + agent_fallback_models(a) + disc
        else:
            cands += disc
        seen = set(); models = []
        for m in cands:
            m = (m or "").strip()
            if m in seen: continue
            seen.add(m); models.append(m)
        if not a.get("kind") == "provider":
            models = models[: max(1, int(cfg.get("max_model_fallbacks", 3)))]

        for m in models:
            if cancel_event is not None and cancel_event.is_set():
                break
            key = (ag_name, m)
            if key in tried:
                continue
            tried.add(key)
            if on_attempt is not None:
                on_attempt(ag_name, m)
            res = run_one(ag_name, a, prompt, m, cont if is_primary else False, cwd, env,
                          timeout if timeout is not None else a.get("timeout", 300),
                          on_chunk=on_chunk, cancel_event=cancel_event, messages=messages)
            if cancel_event is not None and cancel_event.is_set():
                res["attempts"] = attempts
                return res
            cat = record_limit(ag_name, res)
            attempts.append({"agent": ag_name, "model": m, "ok": res["ok"], "category": cat, "error": (res.get("error") or "")[:160]})
            if res["ok"]:
                res["attempts"] = attempts
                res["switched"] = len(attempts) > 1
                if len(attempts) > 1 and not quiet_notice:
                    print(dim(f"  ↪ auto-switch: {attempts[-1]['agent']}/{attempts[-1]['model'] or 'default'} (attempt {len(attempts)})"), file=sys.stderr)
                return res
            last = res
            if cat not in MODEL_SWITCH:
                break
            if len(attempts) >= max_attempts:
                break
        if not allow_agent_switch or len(attempts) >= max_attempts:
            break

    if last is None:
        last = {"agent": name, "ok": False, "output": "", "error": "no ready agent/model found", "attempts": attempts}
    else:
        last["attempts"] = attempts
        last["switched"] = len(attempts) > 1
    return last

def cmd_limits(cfg: dict) -> int:
    lim = load_limits()
    print(bold("AGENT LIMIT STATUS") + dim(f"  ({LIMITS_PATH})"))
    if not lim:
        print(dim("no entries yet; entries are recorded after calls."))
    now = time.time()
    for name in cfg["agents"]:
        e = lim.get(name) or {}
        cat = e.get("category", "")
        cd = e.get("cooldown_until", 0)
        cd_s = dim(f" cooldown {int(cd-now)}s") if cd and cd > now else ""
        if not e:
            print(f"  {dim('·')} {name:<10} {dim('no history')}")
            continue
        mark = green("✓") if e.get("last_ok") and not cat else (yellow("⚠") if cat else dim("·"))
        print(f"  {mark} {name:<10} {cat or dim('ok')}{cd_s}  {dim('failed ' + str(e.get('count',0)) + 'x')}")
        if e.get("last_error"):
            print(dim(f"      {e['last_error'][:160]}"))
    print(dim(f"\nauto_switch_agent={cfg.get('auto_switch_agent')}  max_fallback_attempts={cfg.get('max_fallback_attempts')}  max_model_fallbacks={cfg.get('max_model_fallbacks')}"))
    print(dim("reset: delete " + str(LIMITS_PATH)))
    return 0

def cmd_fallback(cfg: dict, rest: list[str]) -> int:
    if not rest:
        order = fallback_order(cfg, cfg["default_agent"])
        print(bold("FALLBACK ORDER") + dim(f"  (default={cfg['default_agent']})"))
        print("  " + " → ".join(order))
        print(f"auto_switch_agent : {cfg.get('auto_switch_agent')}")
        print(f"fallback_agents   : {', '.join(cfg.get('fallback_agents') or []) or dim('(empty — uses remaining agents)')}")
        print(f"max_fallback_attempts : {cfg.get('max_fallback_attempts')}")
        print(f"max_model_fallbacks   : {cfg.get('max_model_fallbacks')}")
        print(dim("\nset: `ai fallback set opencode,mods,ollama,llm` | `ai fallback on|off` | `ai fallback max N`"))
        return 0
    sub = rest[0]
    if sub in ("on", "off"):
        cfg["auto_switch_agent"] = (sub == "on"); save_config(cfg); print(green(f"✓ auto_switch_agent={sub=='on'}")); return 0
    if sub == "set":
        names = [s.strip() for s in (rest[1].split(",") if len(rest) > 1 else []) if s.strip()]
        bad = [n for n in names if n not in cfg["agents"]]
        if bad: die(f"unknown agent: {', '.join(bad)}")
        cfg["fallback_agents"] = names; save_config(cfg); print(green(f"✓ fallback_agents={names or '[]'}")); return 0
    if sub == "max":
        n = int(rest[1]); cfg["max_fallback_attempts"] = n; save_config(cfg); print(green(f"✓ max_fallback_attempts={n}")); return 0
    if sub == "clear":
        cfg["fallback_agents"] = []; save_config(cfg); print(green("✓ fallback_agents=[]")); return 0
    die(f"fallback: unknown subcommand: {sub}")

def cmd_all(cfg: dict, prompt: str, model: str, cwd: str, env: dict,
            timeout: int | None, only: list[str] | None) -> int:
    names = only or [n for n, a in cfg["agents"].items()
                     if a.get("kind", "agent") == "agent" and find_bin(a)]
    if not names: die("no ready agents found.")
    print(dim(f"→ querying {len(names)} agents in parallel: {', '.join(names)}\n"))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as ex:
        futs = {ex.submit(ask, cfg, n, prompt, model, False, cwd, env, timeout): n for n in names}
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
    order = {n: i for i, n in enumerate(names)}
    results.sort(key=lambda r: order.get(r["agent"], 99))
    ok = 0
    for r in results:
        print_result(r, header_stream=sys.stdout); print(); ok += 1 if r["ok"] else 0
    print(dim(f"{ok}/{len(results)} succeeded"))
    return 0 if ok else 1

# ---------------------------------------------------------------- interactive & TUI
HELP_TXT = """
Commands:
  /agent [name]     show / switch active agent
  /agents           list AI agents
  /clis             list all discovered CLIs on system
  /all <prompt>     query all agents in parallel
  /model [name]     show / set session model
  /reset            reset conversation context
  /continue on|off  continue agent session (default on)
  /cwd [dir]        show / change working directory
  /doctor           run diagnostics on all agents
  /config           show config path
  /clear            clear screen
  /help             show this help
  /exit             quit (or Ctrl-D)
"""

def launch_tui(start_agent: str, model: str, cwd: str, timeout: int | None) -> int | None:
    """Launch Nexus Terminal TUI if venv & TTY are available."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    if os.environ.get("TERM", "") == "dumb":
        return None
    if not (VENV_PYTHON.exists() and TUI_SCRIPT.exists()):
        return None
    cmd = [str(VENV_PYTHON), str(TUI_SCRIPT), "--agent", start_agent, "--cwd", cwd]
    if model:
        cmd += ["--model", model]
    if timeout is not None:
        cmd += ["--timeout", str(timeout)]
    return subprocess.call(cmd)

def interactive(cfg: dict, start_agent: str, model: str, cwd: str, env: dict,
                timeout: int | None, simple: bool = False) -> int:
    if not simple:
        rc = launch_tui(start_agent, model, cwd, timeout)
        if rc is not None:
            return rc

    agent_name = start_agent
    cont = False
    hist_note = dim("type /help for commands, /exit to quit")
    print(bold("╭─ nexus") + dim(f"  agent={agent_name}  cwd={cwd}"))
    print(dim("│  one CLI hub for all AI agents and developer CLIs") + "\n" + hist_note)
    while True:
        try:
            prompt = input(f"\n{cyan(agent_name)} {bold('›')} ")
        except EOFError:
            print(); break
        except KeyboardInterrupt:
            print(); continue
        line = prompt.strip()
        if not line:
            continue
        if line in ("/exit", "/quit", "/q", "exit"):
            break
        if line == "/help":
            print(HELP_TXT); continue
        if line == "/clear":
            os.system("clear"); continue
        if line == "/agents":
            agent_table(cfg, cwd, env); continue
        if line == "/clis":
            cmd_clis(cfg, env); continue
        if line == "/config":
            print(f"config file: {CONFIG_PATH}"); continue
        if line == "/doctor":
            cmd_doctor(cfg, [], cwd, env); continue
        if line.startswith("/agent"):
            rest = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
            if not rest:
                agent_table(cfg, cwd, env); continue
            if rest not in cfg["agents"]:
                print(red(f"unknown agent: {rest}")); continue
            agent_name = rest
            print(green(f"✓ agent: {agent_name}")); continue
        if line.startswith("/model"):
            rest = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
            if not rest:
                print(f"session model: {model or dim('(agent default)')}"); continue
            model = rest
            print(green(f"✓ model: {model}")); continue
        if line == "/reset":
            cont = False
            print(dim("context reset for next message")); continue
        if line.startswith("/continue"):
            rest = line.split(None, 1)[1].strip().lower() if len(line.split()) > 1 else ""
            cont = rest != "off"
            print(f"continue: {cont}"); continue
        if line.startswith("/cwd"):
            rest = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
            if not rest:
                print(f"cwd: {cwd}"); continue
            p = Path(rest).expanduser()
            if not p.is_dir():
                print(red(f"not a directory: {p}")); continue
            cwd = str(p.resolve()); print(f"cwd: {cwd}"); continue
        if line.startswith("/all"):
            rest = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
            if not rest:
                print(red("usage: /all <prompt>")); continue
            cmd_all(cfg, rest, model, cwd, env, timeout, None); continue
        if line.startswith("!"):
            sh = line[1:].strip()
            if sh:
                subprocess.run(sh, shell=True, cwd=cwd, env=env)
            continue
        if line.startswith("/"):
            print(red(f"unknown command: {line}  (/help)")); continue
        try:
            res = ask_with_fallback(cfg, agent_name, line, model, cont, cwd, env, timeout)
        except KeyboardInterrupt:
            print(yellow("\n(cancelled)")); continue
        print()
        print_result(res, show_header=False)
        cont = True
    print(dim("bye"))
    return 0

# ---------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai",
        description="ai — Unified Terminal Hub for all AI and open-source developer CLIs.",
        epilog="examples:\n"
               "  ai                          open Nexus Terminal (animated TUI)\n"
               "  ai \"explain this repo\"      one-shot to default agent\n"
               "  ai gemini \"...\"             route directly to Gemini CLI\n"
               "  ai all \"...\"                query all agents in parallel\n"
               "  ai api weather London       query open-source APIs without keys\n"
               "  ai clis | ai agents | ai models NAME | ai use NAME | ai doctor\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"ai {VERSION}")
    sub = p.add_subparsers(dest="cmd")

    def ask_args(sp):
        sp.add_argument("-a", "--agent", help="agent name")
        sp.add_argument("-m", "--model", default="", help="model override")
        sp.add_argument("--continue", dest="cont", action="store_true", default=True, help="continue agent session")
        sp.add_argument("--no-continue", dest="cont", action="store_false", help="start fresh session")
        sp.add_argument("--cwd", default=None, help="working directory")
        sp.add_argument("--timeout", type=int, default=None, help="max seconds per call")

    sp = sub.add_parser("ask", help="query a single agent"); sp.add_argument("agent"); sp.add_argument("prompt", nargs="+"); ask_args(sp)
    sp = sub.add_parser("all", help="query all agents in parallel"); sp.add_argument("prompt", nargs="+")
    sp.add_argument("-m", "--model", default=""); sp.add_argument("--only", default="", help="comma-separated agents"); sp.add_argument("--cwd", default=None); sp.add_argument("--timeout", type=int, default=None)
    sp = sub.add_parser("chat", help="interactive chat / TUI mode"); sp.add_argument("-a", "--agent", default=None); sp.add_argument("-m", "--model", default=""); sp.add_argument("--cwd", default=None); sp.add_argument("--timeout", type=int, default=None); sp.add_argument("--simple", action="store_true")
    sub.add_parser("tui", help="launch Nexus Terminal TUI").add_argument("-a", "--agent", default=None)
    sub.add_parser("agents", help="list AI agents")
    sub.add_parser("clis", help="list all discovered CLIs")
    sub.add_parser("api", help="query & search open-source GitHub APIs").add_argument("rest", nargs="*")
    sp = sub.add_parser("models", help="list models for an agent"); sp.add_argument("agent", nargs="?", default=None)
    sp = sub.add_parser("use", help="set default agent"); sp.add_argument("agent")
    sp = sub.add_parser("doctor", help="check agent health"); sp.add_argument("agents", nargs="*")
    sub.add_parser("auth", help="show free tiers and login sync status")
    sub.add_parser("login", help="sign in to an AI CLI so it syncs with Nexus").add_argument("agent")
    sub.add_parser("setup", help="auto-configure local Ollama & refresh agent configs")
    sub.add_parser("update", help="update nexus-cli from GitHub")
    sp = sub.add_parser("config", help="show config"); sp.add_argument("--edit", action="store_true")
    sub.add_parser("limits", help="agent quota/cooldown status")
    sub.add_parser("status", help="agent quota/cooldown status")
    sub.add_parser("fallback", help="manage auto-switch fallback order").add_argument("rest", nargs="*")
    sub.add_parser("where", help="show config path")
    sub.add_parser("version", help="show version")
    return p

def main(argv: list[str]) -> int:
    cfg = load_config()
    base_env = build_env(cfg)
    cwd = cfg.get("cwd") or os.getcwd()

    parser = build_parser()
    known = {"ask","all","chat","tui","agents","clis","api","models","use","doctor","auth","login","setup","update","config","where","version","help","limits","status","fallback"}

    def norm_cwd(p):
        return str(Path(p or cwd).expanduser().resolve())

    if not argv:
        return interactive(cfg, cfg["default_agent"], "", norm_cwd(cwd), base_env, None)

    cmd = argv[0]

    if cmd in ("help", "-h", "--help"):
        parser.print_help(); return 0
    if cmd in ("-V", "--version"):
        print(f"ai {VERSION}"); return 0

    if cmd in known - {"help"}:
        ns, _unknown = parser.parse_known_args(argv)
        wcwd = norm_cwd(getattr(ns, "cwd", None) or cwd)
        timeout = getattr(ns, "timeout", None)
        if ns.cmd == "version":
            print(f"ai {VERSION}"); return 0
        if ns.cmd in ("limits", "status"):
            return cmd_limits(cfg)
        if ns.cmd == "fallback":
            return cmd_fallback(cfg, getattr(ns, "rest", []))
        if ns.cmd == "where":
            print(CONFIG_PATH); return 0
        if ns.cmd == "agents":
            agent_table(cfg, wcwd, base_env); return 0
        if ns.cmd == "clis":
            return cmd_clis(cfg, base_env)
        if ns.cmd == "api":
            import api_hub
            res = api_hub.run_api(" ".join(getattr(ns, "rest", [])))
            print(bold(res["title"]))
            print(res["markdown"])
            return 0 if res["ok"] else 1
        if ns.cmd == "models":
            return cmd_models(cfg, ns.agent or cfg["default_agent"], wcwd, base_env)
        if ns.cmd == "use":
            return cmd_use(cfg, ns.agent)
        if ns.cmd == "doctor":
            return cmd_doctor(cfg, ns.agents, wcwd, base_env)
        if ns.cmd == "auth":
            return cmd_auth(cfg, base_env)
        if ns.cmd == "login":
            return cmd_login(cfg, ns.agent, wcwd, base_env)
        if ns.cmd == "setup":
            return cmd_setup(cfg, base_env)
        if ns.cmd == "update":
            return cmd_update()
        if ns.cmd == "config":
            return cmd_config(cfg, ns.edit)
        if ns.cmd == "tui":
            rc = launch_tui(getattr(ns, "agent", None) or cfg["default_agent"], "", wcwd, None)
            return rc if rc is not None else interactive(cfg, cfg["default_agent"], "", wcwd, base_env, None, simple=True)
        if ns.cmd == "chat":
            return interactive(cfg, ns.agent or cfg["default_agent"], ns.model, wcwd, base_env, timeout, simple=ns.simple)
        if ns.cmd == "all":
            only = [s.strip() for s in ns.only.split(",") if s.strip()] or None
            return cmd_all(cfg, " ".join(ns.prompt), ns.model, wcwd, base_env, timeout, only)
        if ns.cmd == "ask":
            agent = ns.agent or cfg["default_agent"]
            try:
                res = ask_with_fallback(cfg, agent, " ".join(ns.prompt), ns.model, ns.cont, wcwd, base_env, timeout)
            except RuntimeError as e:
                die(str(e))
            print_result(res)
            return 0 if res["ok"] else 1

    args = list(argv)
    agent = None
    model = ""
    cont = True
    wcwd = cwd
    timeout = None
    simple = False
    prompt_parts: list[str] = []

    if args and args[0] in cfg["agents"]:
        agent = args.pop(0)

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-a", "--agent"):
            agent = args[i+1]; i += 2; continue
        if a in ("-m", "--model"):
            model = args[i+1]; i += 2; continue
        if a == "--cwd":
            wcwd = args[i+1]; i += 2; continue
        if a == "--timeout":
            timeout = int(args[i+1]); i += 2; continue
        if a == "--no-continue":
            cont = False; i += 1; continue
        if a == "--continue":
            cont = True; i += 1; continue
        if a == "--simple":
            simple = True; i += 1; continue
        if a == "--":
            prompt_parts += args[i+1:]; break
        prompt_parts.append(a); i += 1

    prompt = " ".join(prompt_parts).strip()
    agent = agent or cfg["default_agent"]
    if not prompt:
        return interactive(cfg, agent, model, norm_cwd(wcwd), base_env, timeout, simple=simple)
    try:
        res = ask_with_fallback(cfg, agent, prompt, model, cont, norm_cwd(wcwd), base_env, timeout)
    except RuntimeError as e:
        die(str(e))
    print_result(res)
    return 0 if res["ok"] else 1


def cli_main() -> None:
    signal.signal(signal.SIGINT, lambda _s, _f: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print(); sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
