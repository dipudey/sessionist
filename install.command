#!/usr/bin/env bash
# Double-click this file in Finder (macOS) to install ccsessions.
# It just runs install.sh from this folder, then waits so you can read output.
cd "$(dirname "${BASH_SOURCE[0]:-$0}")" || exit 1
bash ./install.sh
echo
echo "Press Return to close…"
read -r _
