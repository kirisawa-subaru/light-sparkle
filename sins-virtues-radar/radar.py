#!/usr/bin/env python3
"""Render one fourteen-axis Seven Sins / Seven Virtues radar chart."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle


SINS = ["Pride", "Greed", "Lust", "Envy", "Gluttony", "Wrath", "Sloth"]
VIRTUES = [
    "Humility",
    "Charity",
    "Chastity",
    "Kindness",
    "Temperance",
    "Patience",
    "Diligence",
]

SIN_COLOR = "#C73A45"
VIRTUE_COLOR = "#2878B5"
GRID_COLOR = "#AEB4BD"
TEXT_COLOR = "#242832"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a red-left / blue-right Seven Sins and Virtues radar chart."
    )
    parser.add_argument("input", type=Path, help="JSON score file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sins_virtues_radar.png"),
        help="PNG output path (default: sins_virtues_radar.png)",
    )
    parser.add_argument("--dpi", type=int, default=220, help="output resolution")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    scores = config.get("display_scores") or config.get("raw_scores")
    if not isinstance(scores, dict):
        raise ValueError("input must contain a display_scores or raw_scores object")

    required = SINS + VIRTUES
    missing = [name for name in required if name not in scores]
    extra = [name for name in scores if name not in required]
    if missing or extra:
        messages = []
        if missing:
            messages.append(f"missing scores: {', '.join(missing)}")
        if extra:
            messages.append(f"unknown scores: {', '.join(extra)}")
        raise ValueError("; ".join(messages))

    normalized: dict[str, float] = {}
    for name in required:
        value = scores[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"score for {name} must be numeric")
        if not 0 <= float(value) <= 100:
            raise ValueError(f"score for {name} must be between 0 and 100")
        normalized[name] = float(value)

    rmax = config.get("rmax", math.ceil(max(normalized.values()) / 5) * 5)
    if not isinstance(rmax, (int, float)) or isinstance(rmax, bool):
        raise ValueError("rmax must be numeric")
    if float(rmax) < max(normalized.values()):
        raise ValueError("rmax must be at least the largest display score")

    config["display_scores"] = normalized
    config["rmax"] = float(rmax)
    return config


def radial_ticks(rmax: float) -> list[float]:
    step = 20 if rmax >= 80 else 10
    ticks = [float(value) for value in range(step, int(rmax), step)]
    if not ticks or not math.isclose(ticks[-1], rmax):
        ticks.append(rmax)
    return ticks


def format_score(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def render(config: dict[str, Any], output: Path, dpi: int) -> None:
    scores: dict[str, float] = config["display_scores"]
    rmax: float = config["rmax"]

    # Clockwise from the top seam: virtues occupy the right half from top to
    # bottom, then sins occupy the left half from bottom to top.
    right_names = list(reversed(VIRTUES))
    left_names = list(reversed(SINS))
    names = right_names + left_names
    values = np.array([scores[name] for name in names], dtype=float)
    angles = np.arange(1, 28, 2, dtype=float) * np.pi / 14

    fig = plt.figure(figsize=(11, 11), facecolor="#FAFAF8")
    ax = fig.add_subplot(111, polar=True, facecolor="#FAFAF8")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_ylim(0, rmax)
    ax.set_axisbelow(True)

    ax.spines["polar"].set_color("#7D838C")
    ax.spines["polar"].set_linewidth(1.1)
    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.75, alpha=0.72)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.75, alpha=0.72)

    ticks = radial_ticks(rmax)
    ax.set_yticks(ticks)
    ax.set_yticklabels([format_score(value) for value in ticks], color="#6F7580")
    ax.set_rlabel_position(0)

    labels = [f"{name}\n{format_score(scores[name])}" for name in names]
    ax.set_thetagrids(np.degrees(angles), labels)
    ax.tick_params(axis="x", pad=17, labelsize=10)
    for index, label in enumerate(ax.get_xticklabels()):
        label.set_color(VIRTUE_COLOR if index < 7 else SIN_COLOR)
        label.set_fontweight("bold")
        theta = angles[index] % (2 * np.pi)
        if 0.08 < theta < np.pi - 0.08:
            label.set_horizontalalignment("left")
        elif np.pi + 0.08 < theta < 2 * np.pi - 0.08:
            label.set_horizontalalignment("right")
        else:
            label.set_horizontalalignment("center")

    closed_angles = np.concatenate([angles, [angles[0] + 2 * np.pi]])
    closed_values = np.concatenate([values, [values[0]]])

    # Fill the same complete polygon twice and clip it into two half-planes.
    # This preserves a single honest outline without introducing a fake radial
    # closure line through the center.
    left_fill = ax.fill(closed_angles, closed_values, color=SIN_COLOR, alpha=0.19)[0]
    left_fill.set_clip_path(Rectangle((0, 0), 0.5, 1, transform=ax.transAxes))
    right_fill = ax.fill(
        closed_angles, closed_values, color=VIRTUE_COLOR, alpha=0.19
    )[0]
    right_fill.set_clip_path(Rectangle((0.5, 0), 0.5, 1, transform=ax.transAxes))

    right_angles = angles[:7]
    right_values = values[:7]
    left_angles = angles[7:]
    left_values = values[7:]

    top_seam = (scores["Pride"] + scores["Diligence"]) / 2
    bottom_seam = (scores["Sloth"] + scores["Humility"]) / 2

    ax.plot(
        np.concatenate([[0.0], right_angles, [np.pi]]),
        np.concatenate([[top_seam], right_values, [bottom_seam]]),
        color=VIRTUE_COLOR,
        linewidth=2.8,
        solid_capstyle="round",
        zorder=4,
    )
    ax.plot(
        np.concatenate([[np.pi], left_angles, [2 * np.pi]]),
        np.concatenate([[bottom_seam], left_values, [top_seam]]),
        color=SIN_COLOR,
        linewidth=2.8,
        solid_capstyle="round",
        zorder=4,
    )
    ax.scatter(right_angles, right_values, color=VIRTUE_COLOR, s=28, zorder=5)
    ax.scatter(left_angles, left_values, color=SIN_COLOR, s=28, zorder=5)

    title = str(config.get("title", "Seven Sins & Seven Virtues"))
    subject = str(config.get("subject", "")).strip()
    fig.suptitle(
        f"{subject} — {title}" if subject else title,
        y=0.965,
        fontsize=20,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    fig.text(
        0.19,
        0.89,
        "SEVEN SINS",
        ha="center",
        color=SIN_COLOR,
        fontsize=12,
        fontweight="bold",
    )
    fig.text(
        0.81,
        0.89,
        "SEVEN VIRTUES",
        ha="center",
        color=VIRTUE_COLOR,
        fontsize=12,
        fontweight="bold",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    args = parse_args()
    config = load_config(args.input)
    render(config, args.output, args.dpi)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
