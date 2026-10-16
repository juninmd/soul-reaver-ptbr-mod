"""Inventory DAT slots, movie-local dialogue and UI separately, without approval inference."""
import argparse
import hashlib
import json
from pathlib import Path

from audio_pipeline import atomic_json, read_json, validate_voice_namespace
import localize_ui


def audit(root, output):
    coverage_path = root / "staging/localization-v6/coverage.json"
    plan_path = root / "staging/campaign-assembly/selection-v6/plan.json"
    catalogue_path = root / "staging/catalogue-v1/catalogue.json"
    coverage, plan, catalogue = map(read_json, (coverage_path, plan_path, catalogue_path))
    validate_voice_namespace(plan)
    selected = {v["id"]: v for v in plan["voices"]}
    pending = {v["id"]: v for v in coverage["pending"]}
    base = {v["id"]: v for v in catalogue["voices"]}
    if set(base) != set(range(479)) or set(selected) & set(pending) or set(selected) | set(pending) != set(base):
        raise ValueError("The DAT inventory does not reconcile to 479 distinct slots")
    translations = {}
    movie_rows = []
    for path in sorted((root / "content").glob("*.json")):
        data = read_json(path)
        for voice in data.get("voices", []):
            if "fmv" in voice:
                movie_rows.append(dict(voice, key=f'fmv:{voice["fmv"]}:{voice["id"]}', source=str(path.relative_to(root))))
            elif path.name.startswith(("campaign-", "tutorial-", "cast-preview-")):
                translations.setdefault(voice["id"], []).append(dict(source=str(path.relative_to(root)),
                    text_ptbr=voice.get("text_ptbr"), speaker=voice.get("speaker")))
    intro_plan = root / "staging/fmv-dub-v1/timing.json"
    for voice in read_json(intro_plan)["voices"]:
        movie_rows.append(dict(voice, key=f'fmv:{voice["fmv"]}:{voice["id"]}', source=str(intro_plan.relative_to(root))))
    movie_keys = [r["key"] for r in movie_rows]
    if len(movie_keys) != len(set(movie_keys)):
        raise ValueError("Duplicate movie-local dialogue keys require reconciliation")
    approved = {v["id"]: v for v in read_json(root / "content/dialogue-review.json")["voices"]}
    observed = set()
    event_path = root / "staging/render4k-v1/run-10/events.jsonl"
    for line in event_path.read_text(encoding="utf-8").splitlines():
        p = json.loads(line).get("payload", {})
        if p.get("event") == "natural_voice":
            observed.add(p["id"])
    rows = []
    for index in range(479):
        voice = selected.get(index, {})
        old = pending.get(index, {})
        reviewed = approved.get(index, {})
        row = dict(key=f"voices.dat:{index}", id=index,
            offset=base[index]["offset"], length=base[index]["length"],
            replacement_present=index in selected,
            classification="replaced_verbal_candidate" if index in selected else "pending_classification",
            source_asr_en=voice.get("source_asr_en", old.get("source_asr_en")),
            asr_is_not_classification_or_cast_proof=True,
            speaker=voice.get("speaker"),
            text_ptbr=voice.get("text_ptbr"),
            translation_candidates=translations.get(index, []),
            audio_sha256=voice.get("audio_sha256"),
            exact_take_listening_approval_record=bool(reviewed.get("human_listening_approved") and
                reviewed.get("audio_sha256") == voice.get("audio_sha256")),
            natural_event_observed_in_run10=index in observed,
            runtime_evidence=str(event_path.relative_to(root)) if index in observed else None,
            all_scene_contracts_verified=False,
            canonical_text_has_non_ascii=any(ord(c) > 127 for c in voice.get("text_ptbr", "")))
        if old.get("translated") and not translations.get(index):
            row["legacy_coverage_translation_claim_not_supported_by_dat_plans"] = True
        rows.append(row)
    original_ui = root / "staging/backups/steam-classic-en/locals.pc.original"
    strings = localize_ui.decode(original_ui.read_bytes())
    ui = [dict(key=f"locals.pc:{i}", id=i, source_display=''.join(chr(b) if b < 128 else f"[icon:0x{b:02X}]" for b in value),
               translated_by_current_tool=i in localize_ui.TEXT,
               translation_ascii=localize_ui.TEXT.get(i),
               special_character_runtime_verified=False,
               icons=[b for b in value if b >= 128]) for i, value in enumerate(strings)]
    movies = []
    game = Path(r"D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver")
    for movie in sorted(game.glob("*.bik")):
        lines = [r for r in movie_rows if r["fmv"] == movie.stem]
        movies.append(dict(key=f"movie:{movie.stem}", name=movie.name,
            mapped_dialogue_count=len(lines), mapped_dialogue_keys=[r["key"] for r in lines],
            full_text_cards_and_credits_audited=False, hd_runtime_verified=False,
            natural_full_playback_verified=False))
    summary = dict(dat_slots=len(rows), replacements=len(selected), pending_classification=len(pending),
        campaign_complete=False, campaign_percentage=None,
        named_movie_resources=len(movies), mapped_movie_dialogue_rows=len(movie_rows),
        mapped_story_movies=sum(m["mapped_dialogue_count"] > 0 for m in movies),
        ui_strings=len(ui), ui_substitutions=sum(r["translated_by_current_tool"] for r in ui),
        selected_captions_requiring_non_ascii=sum(r["canonical_text_has_non_ascii"] for r in rows),
        legacy_namespace_collisions=[r["id"] for r in rows if r.get("legacy_coverage_translation_claim_not_supported_by_dat_plans")])
    sources = [coverage_path, plan_path, catalogue_path, intro_plan, original_ui]
    report = dict(schema=1, summary=summary,
        limitations=["No speech/cut-content exclusion is inferred from ASR.",
                     "Natural events listed here cover run-10 only, not the historical runtime inventory.",
                     "FMV IDs are movie-local; they never establish a DAT translation or cast.",
                     "Replacement presence is not human listening approval or campaign completion."],
        sources=[dict(path=str(p.relative_to(root)), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources],
        voice_slots=rows, movie_dialogue=movie_rows, movies=movies, ui=ui)
    atomic_json(output, report)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.root.resolve(), args.output), indent=2))
