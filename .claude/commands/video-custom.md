Run the Arbi video pipeline with a specific event you choose, instead of letting the Scout auto-discover a trending one.

Takes ~5 minutes, costs ~$0.77 per run.

**Step 1 — Ask the user for the event.**

Ask: "What event or topic should Arbi re-enact? Be specific (e.g. 'Beyoncé Grammy 2026 opening performance' or 'SpaceX Starship landing March 2026')."

Wait for their answer. Store it as EVENT.

**Step 2 — Ask for an optional description.**

Ask: "Got a short description to help find the right video? (optional — just press Enter to skip)"

If they provide one, store it as DESC. If they skip, leave it empty.

**Step 3 — Run the pipeline.**

If DESC was provided:
```bash
python3 main.py --event "EVENT" --description "DESC"
```

If DESC was skipped:
```bash
python3 main.py --event "EVENT"
```

Replace EVENT and DESC with the actual values the user provided. Make sure to quote them properly.

**Step 4 — Report results.**

After the run completes, report: the event title used, the final video path (in the `output/` directory), and any errors. Check the `logs/` directory for the JSON summary if needed.
