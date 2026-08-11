#!/usr/bin/env bash
#
# ccsessions installer — macOS & Linux.
#
#   - Requires Python 3.8+. If missing, prints how to get it and EXITS (installs nothing).
#   - Creates an isolated venv (no system pollution, dodges PEP-668 "externally-managed").
#   - Installs the `textual` dependency into that venv.
#   - Installs the script to ~/.ccsessions and adds a shell alias (default: ccs).
#   - The alias sets the terminal title to the project name on every run.
#
# Usage:  bash install.sh              (default alias: ccs; prompts if interactive)
#         bash install.sh myname       (custom alias name)
#         CCS_ALIAS=sess bash install.sh
#         curl -fsSL <url>/install.sh | bash
#
set -euo pipefail

APP="ccsessions"
DEFAULT_ALIAS="ccs"
ALIAS_NAME="${1:-${CCS_ALIAS:-}}"   # arg 1 wins, then env, else ask/ default
MIN_PY_MAJOR=3
MIN_PY_MINOR=8
INSTALL_DIR="$HOME/.$APP"
VENV_DIR="$INSTALL_DIR/venv"
SCRIPT_SRC=""   # resolved below
SCRIPT_DST="$INSTALL_DIR/$APP.py"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- locate the script source (next to this installer, else cwd) -------------
resolve_src() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
    if [ -f "$here/$APP.py" ]; then
        SCRIPT_SRC="$here/$APP.py"
    elif [ -f "./$APP.py" ]; then
        SCRIPT_SRC="$(pwd)/$APP.py"
    else
        die "$APP.py not found next to install.sh. Run from the project directory."
    fi
}

# --- find a python3 that meets the minimum version --------------------------
find_python() {
    local cand ver
    for cand in python3 python; do
        if command -v "$cand" >/dev/null 2>&1; then
            if "$cand" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($MIN_PY_MAJOR,$MIN_PY_MINOR) else 1)" 2>/dev/null; then
                ver="$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
                PY="$cand"
                ok "Found Python $ver ($(command -v "$cand"))"
                return 0
            fi
        fi
    done
    return 1
}

no_python() {
    cat >&2 <<EOF

$(printf '\033[1;31mNo suitable Python found.\033[0m') $APP needs Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+.

Nothing was installed. Install Python first, then re-run this script:

  macOS:   brew install python        # or download from https://www.python.org/downloads/
  Debian:  sudo apt install python3 python3-venv
  Fedora:  sudo dnf install python3
  Arch:    sudo pacman -S python

EOF
    exit 1
}

# --- shell rc file for the alias --------------------------------------------
detect_rc() {
    local shell_name
    shell_name="$(basename "${SHELL:-}")"
    case "$shell_name" in
        zsh)  echo "$HOME/.zshrc" ;;
        bash) if [ -f "$HOME/.bashrc" ]; then echo "$HOME/.bashrc"; else echo "$HOME/.bash_profile"; fi ;;
        fish) echo "$HOME/.config/fish/config.fish" ;;
        *)    echo "$HOME/.profile" ;;
    esac
}

# --- pick + validate the alias name -----------------------------------------
resolve_alias() {
    if [ -z "$ALIAS_NAME" ] && [ -t 0 ]; then
        printf 'Alias name to launch this tool [%s]: ' "$DEFAULT_ALIAS" >&2
        read -r ALIAS_NAME || true
    fi
    ALIAS_NAME="${ALIAS_NAME:-$DEFAULT_ALIAS}"
    # allow letters, digits, _, - ; must start with a letter
    if ! printf '%s' "$ALIAS_NAME" | grep -Eq '^[A-Za-z][A-Za-z0-9_-]*$'; then
        die "Invalid alias name '$ALIAS_NAME'. Use letters/digits/_/-, starting with a letter."
    fi
    if command -v "$ALIAS_NAME" >/dev/null 2>&1; then
        printf '\033[1;33mwarn\033[0m command "%s" already exists; the alias will shadow it.\n' "$ALIAS_NAME" >&2
    fi
}

main() {
    resolve_src
    resolve_alias

    say "Checking for Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ …"
    find_python || no_python

    say "Installing to $INSTALL_DIR …"
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_SRC" "$SCRIPT_DST"

    say "Creating virtualenv …"
    if ! "$PY" -m venv "$VENV_DIR" 2>/dev/null; then
        die "Could not create venv. On Debian/Ubuntu install it: sudo apt install python3-venv"
    fi

    say "Installing dependency (textual) …"
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null
    "$VENV_DIR/bin/python" -m pip install --quiet textual
    ok "Dependencies installed"

    # Wrapper sets the terminal title, then runs the script via the venv python.
    local rc alias_line marker
    rc="$(detect_rc)"
    marker="# >>> $APP alias >>>"
    if [ "$(basename "$rc")" = "config.fish" ]; then
        alias_line="function $ALIAS_NAME; printf '\\033]0;$APP\\007'; \"$VENV_DIR/bin/python\" \"$SCRIPT_DST\" \$argv; end"
    else
        alias_line="alias $ALIAS_NAME='printf \"\\033]0;$APP\\007\"; \"$VENV_DIR/bin/python\" \"$SCRIPT_DST\"'"
    fi

    say "Adding '$ALIAS_NAME' alias to $rc …"
    mkdir -p "$(dirname "$rc")"; touch "$rc"
    if grep -qF "$marker" "$rc"; then
        # replace the existing block (marker + next line)
        tmp="$(mktemp)"
        awk -v m="$marker" 'index($0,m){skip=2} skip>0{skip--;next} {print}' "$rc" > "$tmp"
        mv "$tmp" "$rc"
    fi
    { printf '%s\n' "$marker"; printf '%s\n' "$alias_line"; } >> "$rc"
    ok "Alias added"

    cat <<EOF

$(printf '\033[1;32mDone.\033[0m') $APP installed as '$ALIAS_NAME'.

  Restart your terminal, or run:   source "$rc"
  Then in any project dir:         $ALIAS_NAME

  $ALIAS_NAME        # sessions for the current project
  $ALIAS_NAME --all  # sessions across all projects

EOF
}

main "$@"
