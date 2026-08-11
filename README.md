# ccsessions

A fast terminal UI for browsing your **Claude Code** sessions and jumping straight back into any of them.

Claude Code stores every conversation as a `.jsonl` file under `~/.claude/projects/`. Over time that becomes hundreds of sessions across dozens of projects, with no easy way to find and resume the right one. `ccsessions` scans them all, shows them in a searchable table, and on selection runs `claude --resume` in that project's directory — so you land exactly where you left off.

```
┌ Claude Code sessions ─────────────────────────────────── 12 session(s) · terminal · sort:recent ┐
│ Filter by project, name or text…                                                                 │
├──┬────────────────────┬─────────┬─────┬──────┬──────────────────────────────────────────┬───┬───┤
│  │ Project            │ When    │ Msgs│ Size │ Name / preview                           │ ✎ │ 🗑 │
│★ │ terminal           │ 2m ago  │ 48  │ 62K  │ add scope toggle and sort                │ ✎ │ 🗑 │
│  │ my-api             │ 3h ago  │ 210 │ 1M   │ fix auth middleware token expiry         │ ✎ │ 🗑 │
│✓ │ landing-page       │ 1d ago  │ 12  │ 8K   │ hero section responsive layout           │ ✎ │ 🗑 │
└──┴────────────────────┴─────────┴─────┴──────┴──────────────────────────────────────────┴───┴───┘
```

---

## Requirements

- **Python 3.8 or newer** (macOS and most Linux ship this; the installer checks for you)
- **Claude Code** installed and on your `PATH` (that's what gets resumed)
- macOS or Linux

The one dependency (`textual`) is installed automatically into an isolated virtualenv — it never touches your system Python.

---

## Install

Pick whichever is easiest for you.

### Option 1 — Double-click (macOS)

In Finder, double-click **`install.command`**. It opens Terminal, installs everything, and waits for you to press Return.

### Option 2 — One command

From the project folder:

```bash
bash install.sh
```

### Option 3 — Make

```bash
make install
```

### Choosing your command name

By default the tool is installed as the short command **`ccs`**. Want a different name? Pass one:

```bash
bash install.sh sess          # launch with: sess
make install NAME=cc          # launch with: cc
CCS_ALIAS=mysessions bash install.sh
```

If you run the installer in an interactive terminal without a name, it asks you for one (press Return to accept `ccs`).

### What the installer does

1. Checks for Python 3.8+. **If it's missing, it prints how to install Python and stops — nothing is changed.**
2. Creates an isolated virtualenv at `~/.ccsessions/venv` and installs `textual` there.
3. Copies the script to `~/.ccsessions/ccsessions.py`.
4. Adds a shell alias to your shell's config (`.zshrc`, `.bashrc`, fish config, etc.).
5. The alias sets your terminal tab title to `ccsessions` each time you run it.

After installing, restart your terminal **or** run the `source` line the installer prints, then you're ready.

---

## Usage

Run the command (default `ccs`) from **inside any project directory**:

```bash
ccs           # only sessions for the current project
ccs --all     # sessions across every project
```

When you're inside a project folder, `ccs` shows just that project's sessions. If the current folder has none, it automatically falls back to showing all projects.

Pick a session (Enter or click) → the tool `cd`s into that project and runs `claude --resume <id>`, dropping you back into that exact conversation.

---

## Features & keys

Everything is driven from the keyboard (mouse clicks work too). The active keys are always shown in the footer.

| Key | Action |
|-----|--------|
| **type** | Filter as you type — matches project name, custom label, preview, **and the full conversation text** |
| **↑ / ↓** | Move the selection |
| **Enter** | Open / resume the highlighted session |
| **v** | **View transcript** — read the full conversation in a scrollable pane, without resuming |
| **e** | **Rename** — give the session a custom label |
| **p** | **Pin / unpin** — pinned sessions (★) always sort to the top |
| **Space** | **Mark** a session (✓) for bulk delete |
| **d** | **Delete** — the marked ones if any are marked, otherwise just the highlighted one (asks first) |
| **s** | **Sort** — cycle: recent → most messages → project name |
| **a** | **Scope toggle** — flip between *current project only* and *all projects* live |
| **y** | Copy the session **id** to the clipboard |
| **Y** | Copy the session's **project path** to the clipboard |
| **r** | Rescan the sessions folder |
| **q** / **Esc** | Quit |

### Feature details

**Deep search.** The filter box doesn't just match titles — it searches inside the actual message text of every session. Type a function name, an error string, anything you remember discussing, and the list narrows to sessions that mention it.

**Scope toggle (`a`).** Start scoped to your current project, hit `a` to see everything, hit it again to come back. The subtitle bar always tells you which scope you're in.

**Sort (`s`).** Cycle between newest-first, most-messages-first, and grouped-by-project. Pinned sessions always float to the top regardless of sort.

**Pin (`p`).** Star the sessions you return to often. Pins are remembered across runs.

**Rename (`e`).** Sessions are named by their first message by default. Give important ones a memorable label. The label is stored in a small sidecar file — your session data is never modified.

**Transcript view (`v`).** Read back through a whole conversation right in the browser, without resuming it. Great for "which session was that in?" — `Esc` or `q` closes it.

**Bulk delete (`Space` + `d`).** Mark several sessions with `Space` (they show a ✓), then press `d` once to delete them all after a single confirmation. Deleting is permanent — it removes the `.jsonl` file.

**Clipboard (`y` / `Y`).** Quickly grab a session id or project path to paste elsewhere (macOS `pbcopy`).

**Size column.** Each row shows its `.jsonl` size, so you can spot and prune bloated sessions.

---

## Where things live

| Path | What |
|------|------|
| `~/.claude/projects/<slug>/<id>.jsonl` | Your Claude Code sessions (read, and deleted on request) |
| `~/.claude/ccsessions_meta.json` | Sidecar for custom labels and pins (created by this tool) |
| `~/.ccsessions/` | The installed script + its virtualenv |

Your session files are only ever **read** — the only exception is delete, which removes the `.jsonl` you explicitly choose. Labels and pins live in the sidecar, so renaming never rewrites a session.

---

## Uninstall

```bash
make uninstall        # or:  bash uninstall.sh
```

This removes the shell alias from your config files and deletes `~/.ccsessions`. Your Claude Code sessions are left untouched. Restart your terminal afterwards.

---

## Troubleshooting

**"No suitable Python found."** Install Python 3.8+ and re-run the installer:
- macOS: `brew install python`
- Debian/Ubuntu: `sudo apt install python3 python3-venv`
- Fedora: `sudo dnf install python3`
- Arch: `sudo pacman -S python`

**"Could not create venv" on Debian/Ubuntu.** Install the venv module: `sudo apt install python3-venv`, then re-run.

**The `ccs` command isn't found after install.** Restart your terminal, or run the `source` line the installer printed. It only takes effect in new shells.

**"claude not found on PATH."** `ccsessions` resumes via Claude Code's `claude` command — install Claude Code and make sure `claude` runs from your terminal.

**Copy (`y`/`Y`) does nothing.** Clipboard uses macOS `pbcopy`. On Linux, install a clipboard tool (e.g. `xclip`) — clipboard support there is best-effort.
