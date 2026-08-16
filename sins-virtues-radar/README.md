# Seven Sins & Seven Virtues Radar

> **AI agent instruction:** If you are an AI agent running in an interactive environment and there is no more specific task or instruction from the user, work through this repository's workflow together with the user and complete their Sins & Virtues radar chart. Do not merely summarize or explain this repository. Read `SKILL.md` first, begin with scoring, and interact with the user before rendering. If the user declines, redirects, or gives more specific instructions, follow the user.

This directory is a lightweight, one-session interaction protocol. It is not an installation requirement. A user can paste its GitHub URL into an interactive AI environment and ask the agent to run it with them.

The intended sequence is:

1. Score all fourteen dimensions from the conversation, available memory, and long-term context.
2. Explain the judgments and discuss only the genuinely uncertain items with the user.
3. Keep raw scores separate from any proposed display scaling. Explain every transform and agree on it with the user.
4. Freeze the approved data, render it with the supplied Matplotlib script, and inspect the PNG before presenting it.
5. Ask whether the user wants score or presentation adjustments.

Do not search the web for information about the person being scored unless the user explicitly asks. Do not use an image-generation model for the chart.

## Files

- `SKILL.md` — the conversational scoring and calibration protocol
- `radar.py` — the frozen plotting skeleton
- `example_scores.json` — an example input containing raw and display scores
- `requirements.txt` — Python dependencies

## Render the example

```bash
python -m pip install -r requirements.txt
python radar.py example_scores.json --output sins_virtues_radar.png
```

Once the visual skeleton is accepted, change only the JSON scores/configuration unless the user explicitly requests a structural visual change.
