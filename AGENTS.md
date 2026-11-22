# AGENTS.md

Brazilian Portuguese (pt-BR) dub, translation and visual mod for Legacy of Kain: Soul Reaver (classic PC), with a Rust core, a Tauri 2 installer and a Python/Qwen3-TTS audio pipeline.
Priorities: preserve the original game and its saves. Keep observed facts, proposals and runtime validation separate. Never declare the mod working based only on a build or on demos with simulated data.

## Stack

- Rust core `crates/mod-core` (strict SHA-256 checks, atomic journal `.soul-reaver-ptbr`, process locks via `fs2`, safe restore). CLI binary `srmod`.
- Desktop installer `installer/`: Tauri 2 (`installer/src-tauri`), React 19, TypeScript, Vite, Tailwind CSS 4.
- Audio and voice: Python 3 with a local Qwen3-TTS model on CUDA BF16 (`tools/generate_voices.py`), and `tools/audio_pipeline.py` for slot extraction and packaging. Players receive only the finished audio packages.

## Commands

```bash
cargo test -p soul-reaver-mod-core                 # core integrity and transaction tests (isolated fixtures)
cargo fmt --check -p soul-reaver-mod-core          # CI
cargo clippy --locked -p soul-reaver-mod-core --all-targets -- -D warnings   # CI
cargo run -p soul-reaver-mod-core --bin srmod -- inspect|apply|restore <game> [...]
pnpm --dir installer build                         # installer frontend: tsc + vite build
node tools/verify_installer_ui.mjs                 # UI regression with simulated IPC (see docs/INSTALADOR-NOSGOTH.md)
tools/verify_installer_native.sh                   # real installer smoke on Linux (Xvfb, no package, no game)
python tools/audio_pipeline.py catalogue --game <game-dir> --output <out-dir>
python tools/audio_pipeline.py package --game <game-dir> --plan <plan.json> --output <pkg-dir>
python tools/generate_voices.py --plan <plan.json> --model <model-dir> --model-revision <rev> --output <out-dir> [--benchmark]
cargo test --release -p soul-reaver-mod-core -- --ignored bench_ --nocapture --test-threads 1   # ~1 GB temp fixtures
```

## Structure

- `Cargo.toml`: Rust workspace (`crates/mod-core`, `installer/src-tauri`).
- `crates/mod-core/`: library and `srmod` CLI. One module per component (`voices`, `assets`, `external`, `graphics`); `fsx` holds protected I/O, streaming SHA-256, atomic writes and the operation lock; `operation` and `process` cover progress and game-running detection.
- `installer/src/`: frontend (`app`, `screens`, `dialogs`, `components`, `installer`, `styles`). `installer/src-tauri/src/`: backend (`commands`, `transactions`, `diagnostics`, `operation`, `bundle`, `detect`, `controller`, `game_launch`, `cli`, `paths`).
- `tools/`: catalogue, packaging, TTS and verification scripts.
- `content/`: translation, campaign, voice and UI review data.
- `docs/`: plans and validation notes (`PLANO-MOD-4K-PTBR.md`, `VALIDACAO-REINSERCAO-VOZ.md`).
- `REFERENCES.md`: tools, repositories and documents cited.
- `validate/` and `staging/`: git-ignored work areas for human review material, benchmarks, catalogues and test packages.

## Conventions

- Work offline by default. Do not open the game, not even through capture scripts or automated tests, without explicit user authorization for the next run. When authorized, open it in windowed mode if possible.
- Prepare adjustments, builds and tests offline first, then ask for an in-game validation round. Put material that needs human review in `validate/`.
- Language: all translations, subtitles, menus and speech-synthesis text in pt-BR, with natural Brazilian vocabulary and constructions. Keep each character's register and personality. Keep each character's voice consistent and preserve approved lines.
- Accent: prefer a light, natural São Paulo and/or Minas Gerais accent when possible. The Qwen3-TTS `Portuguese` option does not guarantee the Brazilian variant or the regional accent. Confirm pronunciation and performance by listening. Do not declare an accent validated from the selected language or from ASR.
- Subagents: to save tokens, delegate to GPT-6 Luna subagents, with short tasks and separate responsibilities.
- Read the current git state before changing branches. Preserve work that is not yours.
- GitHub Actions: <!-- base-actions-main-policy -->
  - Reference internal actions by branch, never by SHA: `uses: juninmd/base-actions/<action>@main` and `uses: juninmd/base-actions/.github/workflows/<file>.yml@main`.
  - Do not pin `@<sha>` for `juninmd/base-actions`; updates are centralized on `main`.
  - PRs whose checks do not start because of billing or spending limits are auto-merged by `juninmd/base-actions/.github/workflows/auto-merge-billing-blocked.yml`. Apply the `do-not-merge` label to block that.

## Gotchas

- Never commit game executables, DAT/BIG/BIK files, saves, extractions, AI weights, third-party voice references or keys. `.gitignore` covers most of them; check `git diff --cached --name-only` before every commit.
- Keep backups, staging and test installs outside the original Steam copy. Do not overwrite other mods' DLLs. Do not restore files that were changed later without checking hashes and ownership.
- Do not embed GitHub tokens in the installer to reach private releases.
- Creating this repo does not authorize publishing the game or publishing mod releases.
- `ci.yml` runs fmt, clippy and core tests on PRs and pushes to `master`. Every push to `master` also runs `release.yml`: version bump commit, tag, and installer build. Do not push to `master` casually.
