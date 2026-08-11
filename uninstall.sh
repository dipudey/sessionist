#!/usr/bin/env bash
# ccsessions uninstaller — removes the install dir and the shell alias block.
set -euo pipefail

APP="ccsessions"
INSTALL_DIR="$HOME/.$APP"
marker="# >>> $APP alias >>>"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m ok\033[0m %s\n' "$*"; }

# Strip the marker + following alias line from every common rc file.
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" \
          "$HOME/.profile" "$HOME/.config/fish/config.fish"; do
    [ -f "$rc" ] || continue
    if grep -qF "$marker" "$rc"; then
        tmp="$(mktemp)"
        awk -v m="$marker" 'index($0,m){skip=2} skip>0{skip--;next} {print}' "$rc" > "$tmp"
        mv "$tmp" "$rc"
        ok "Removed alias from $rc"
    fi
done

if [ -d "$INSTALL_DIR" ]; then
    say "Removing $INSTALL_DIR …"
    rm -rf "$INSTALL_DIR"
    ok "Removed"
fi

echo
echo "Uninstalled. Restart your terminal (the alias is gone from new shells)."
