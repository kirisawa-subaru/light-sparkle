---
name: sins-virtues-radar
description: Score a person on the Seven Sins and Seven Virtues from available conversation and long-term context, calibrate uncertain judgments with the user, agree on any display scaling, then render the approved values as a single red-left/blue-right radar chart using the supplied Matplotlib template.
---

# Sins & Virtues Radar

Complete the reasoning and calibration before plotting. Treat the result as an evidence-based reflective profile, not an objective measurement.

## Non-negotiable rules

- Use Chinese by default for all interaction and explanation unless the user requests another language.
- Treat this repository as remote text context. Do not clone, install, or check it out. Read `README.md`, `SKILL.md`, and `radar.py` directly from GitHub as text; if a clone attempt fails, ignore the failure and continue reading the files.
- Use the current conversation, available memory, and established long-term context. Do not browse the web for facts about the user unless they explicitly request it.
- Score before asking the user to score themselves.
- Do not treat a sin and its paired virtue as complements. Pride and Humility, for example, can both be high because they describe different mechanisms.
- Keep `raw_scores` and `display_scores` separate. Never normalize or rebalance scores silently.
- Do not call an image-generation model. Copy and execute the repository's provided `radar.py` verbatim. Never recreate, approximate, replace, or independently reimplement it.
- After the user accepts the chart geometry, change only score/config values unless they explicitly request a structural visual change.

## Dimensions

Score each dimension from 0 to 100.

### Seven Sins

- **Pride** — superiority, self-importance, or insistence on sovereign judgment
- **Greed** — acquisitiveness and unwillingness to release resources or advantage
- **Lust** — the degree to which desire gains disproportionate authority over action or other people
- **Envy** — pain at another person's advantage, including comparative or acquisitive envy
- **Gluttony** — overconsumption and difficulty stopping after sufficiency
- **Wrath** — anger, punitive drive, aggression, or norm-enforcing hostility
- **Sloth** — avoidant withdrawal from a valued good despite available capacity, not exhaustion or incapacity

### Seven Virtues

- **Humility** — accurate self-limitation, corrigibility, and willingness to yield to evidence
- **Charity** — generosity and giving that is not secretly maintained as a debt ledger
- **Chastity** — governance and integration of sexual desire, not absence of fantasy
- **Kindness** — stable preference for humane treatment when one has the power to be harsher
- **Temperance** — regulation of appetite, pressure, effort, and self-expenditure
- **Patience** — capacity to tolerate necessary friction without premature retaliation or abandonment
- **Diligence** — sustained pursuit, maintenance, and return to important goals

## Phase 1: Independent scoring

1. Assign a raw 0–100 score to every dimension.
2. For each score, distinguish observation from inference and identify the strongest supporting evidence.
3. State important ambiguities. Do not invent confidence merely to fill the table.
4. Present all fourteen raw scores and concise reasons before plotting.

## Phase 2: Calibration with the user

1. Ask only about dimensions whose score could materially change with first-person information.
2. Prefer concrete, situational questions over labels such as "Are you envious?"
3. Revise scores when the answer changes the underlying model, and explain the revision.
4. Let the user challenge the construct itself. A disagreement about what a dimension measures is not just a numeric adjustment.

## Phase 3: Display scaling

1. Compute and report the raw mean and maximum for each side.
2. Propose one shared radial maximum (`rmax`) so the two sides remain directly comparable. Rounding just above the largest display score to a multiple of five is a reasonable default.
3. If proposing any score transform, show the rule, the before/after values, and why it improves interpretation.
4. Do not automatically equalize means, equalize maxima, or impose a preferred virtue-to-sin ratio. These are substantive claims, not neutral formatting.
5. Obtain the user's agreement before writing transformed values to `display_scores`.

If no transform is agreed, copy `raw_scores` to `display_scores` unchanged.

## Phase 4: Freeze and render

1. Read the repository's `radar.py` directly as remote text and copy it verbatim into the execution environment. Do not reconstruct it from memory or write an equivalent replacement.
2. Write the agreed data using the schema in `example_scores.json`.
3. Run:

   ```bash
   python radar.py scores.json --output sins_virtues_radar.png
   ```

4. Open the rendered PNG and check it visually. Do not rely only on a successful exit code.
5. Reject and rerender the image unless every item below passes:

   - one complete fourteen-axis circle
   - all seven sins on the left in red
   - all seven virtues on the right in blue
   - the top boundary changes cleanly from Pride/red to Diligence/blue
   - the bottom boundary changes cleanly from Sloth/red to Humility/blue
   - no stray line closes either half through the center
   - labels, displayed scores, and `rmax` match the approved data
   - no text or chart element is clipped

## Phase 5: Present and adjust

Show the checked chart together with the final raw/display distinction and any scaling rule. Ask whether the user wants numeric or visual adjustments. Preserve the frozen plotting skeleton unless they explicitly request a geometry change.
