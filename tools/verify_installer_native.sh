#!/usr/bin/env bash
# Smoke test of the real installer binary on Linux: Rust backend, embedded
# frontend, WebKitGTK webview and the Content-Security-Policy of tauri.conf.json,
# under a virtual display. Synthetic clicks walk through the screens and the
# process must survive each one.
#
# What this proves: the application starts, the policy does not block its own
# assets or IPC, and navigation and dialogs do not crash the webview.
# What it does not prove: anything about Windows/WebView2, about a real game
# folder (none is selected, so no file is inspected or written) or about the
# game itself, which is never started.
#
# Requires: xvfb-run, xdotool, ImageMagick (import) and a built binary:
#   pnpm --dir installer build && cargo build -p soul-reaver-mod-installer
# Usage: tools/verify_installer_native.sh [output-dir] [binary]
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
output=${1:-"$root/validate/98-instalador-nativo-linux"}
binary=${2:-"$root/target/debug/soul-reaver-mod-installer"}
mkdir -p "$output"
[ -x "$binary" ] || { echo "Binário não encontrado: $binary" >&2; exit 2; }

# Each step: "<name>|<xdotool arguments>". Only the navigation bar is reached by
# coordinates (1240x800 window); everything inside a screen is reached by keyboard,
# from the heading that receives focus when the screen opens.
steps=(
  "01-jornada|mousemove 620 400"
  "02-componentes|mousemove 179 68 click 1"
  "03-restauracao|mousemove 299 68 click 1"
  "04-diagnostico|mousemove 443 68 click 1"
  "05-dialogo-local|key Tab Tab Return"
  "06-pasta-inexistente|type --delay 15 /caminho/inexistente"
  "07-erro-de-inspecao|key Return"
  "08-jornada-com-erro|mousemove 67 68 click 1"
  "09-sobre|mousemove 1080 68 click 1"
  "10-fechar-dialogo|key Escape"
)

# The binary runs from a scratch directory outside the repository, so the package
# lookup around the executable finds nothing: no package and no game is the one
# state every machine can reproduce, and the one the keyboard steps assume.
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
cp "$binary" "$scratch/installer"
export OUTPUT="$output" BINARY="$scratch/installer" SCRATCH="$scratch" STEPS="$(printf '%s\n' "${steps[@]}")"
# Isolated per-user directories: nothing is read from or written to the real profile.
export LOCALAPPDATA="$output/appdata" XDG_CONFIG_HOME="$output/config"
mkdir -p "$LOCALAPPDATA" "$XDG_CONFIG_HOME"
unset SRMOD_REPO SRMOD_MODULES SRMOD_BUNDLE

xvfb-run -a -s "-screen 0 1240x800x24" bash -c '
  export GDK_BACKEND=x11 LIBGL_ALWAYS_SOFTWARE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1
  # Containers run as root without user namespaces; the web process sandbox cannot start there.
  [ "$(id -u)" = 0 ] && export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
  cd "$SCRATCH"
  "$BINARY" > "$OUTPUT/installer.log" 2>&1 &
  app=$!
  sleep "${SRMOD_NATIVE_STARTUP:-10}"
  failed=0
  while IFS="|" read -r name action; do
    xdotool $action
    sleep 2
    if kill -0 "$app" 2>/dev/null; then
      import -window root "$OUTPUT/$name.png"
      echo "ok    $name"
    else
      wait "$app" && code=0 || code=$?
      echo "FALHA $name: o instalador encerrou (código $code)"
      failed=1
      break
    fi
  done <<< "$STEPS"
  kill "$app" 2>/dev/null || true
  exit $failed
'
echo "Capturas em $output"
