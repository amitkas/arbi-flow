Run the Arbi video pipeline in pick mode: the Scout finds 3 trending events and you choose which one Arbi re-enacts.

Takes ~5 minutes total (~30s for scouting + ~5min for video), costs ~$0.77 per run.

Execute the pipeline by running:

```bash
python3 main.py --pick
```

The pipeline will:
1. Scout and display 3 trending event options with Arbi comedy angles
2. Wait for you to type a number (1, 2, or 3)
3. Run the full video pipeline with your chosen event

When the 3 options appear in the terminal output, show them to the user and ask which they'd like. Then type the number into the terminal to continue. After the run completes, report the results: event title, final video path (in the `output/` directory), and any errors.
