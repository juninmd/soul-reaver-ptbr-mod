#!/usr/bin/env bash
# One-time setup: creates the updater signing key, stores the private half as a GitHub secret
# and writes the public half into tauri.conf.json. Needs: pnpm, gh (authenticated).
set -euo pipefail
cd "$(dirname "$0")/.."
dir=$(mktemp -d); trap 'rm -rf "$dir"' EXIT
pnpm --dir installer tauri signer generate --ci -w "$dir/updater.key" >/dev/null
gh secret set TAURI_SIGNING_PRIVATE_KEY < "$dir/updater.key"
python3 - "$(cat "$dir/updater.key.pub")" <<'PY'
import json, sys
p = 'installer/src-tauri/tauri.conf.json'
c = json.load(open(p)); c['plugins']['updater']['pubkey'] = sys.argv[1]
json.dump(c, open(p, 'w'), indent=2, ensure_ascii=False); open(p, 'a').write('\n')
PY
echo "Pronto. Faça commit de installer/src-tauri/tauri.conf.json (chave pública) e envie para master."
