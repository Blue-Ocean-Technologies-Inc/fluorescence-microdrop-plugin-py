"""Generate a synthetic heater log covering an existing captures
folder, for testing the temperature x-axis against known ground truth.

Reads every capture's embedded timestamp (either stamp format the
viewer accepts) and writes one JSONL heater log spanning the range at
1 Hz, in the format the heater plugin logs:

    {"timestamp": "<local ISO>", "temperatures": {"thermistor2": ...,
     "thermistor1": ...}, "_frame": "TEMP", "board_timestamp": ...}

The profile is a melt-style run: a 2-minute hold near 20 °C, a linear
ramp to 95 °C across the middle of the span, then a hold — so
intensity-vs-temperature has a readable ramp to sit on. The two
thermistors track each other within a few hundredths of a degree, with
light noise on both. The file is named by its first line's local time
(``YYYYMMDD_HHMMSS.jsonl``), the heater plugin's own convention.

Timing mischief is planted on purpose, for the join's averaging
window: every line's clock jitters a few hundred ms off the whole
second (so capture times never land exactly on a sample), and two
dead spans (30 s and 75 s, mid-run) have no lines at all — where a
generous window still averages something and a narrow one honestly
gaps.

Run:
    pixi run python examples/generate_heater_demo_log.py \\
        <captures_dir> [heater_logs_dir]

``heater_logs_dir`` defaults to ``<captures_dir>/../../heater_logs``
(the sibling the plot pane looks in by default when the captures live
in ``<experiment>/captures/<subdir>``).
"""

import json
import random
import sys
from datetime import datetime
from pathlib import Path

from fluorescence_controls_ui.image_viewer.discovery import (
    capture_timestamp,
)

#: The melt profile: hold near this before ramping...
HOLD_START_C = 20.0
#: ...to this, then hold again.
HOLD_END_C = 95.0
#: Seconds of flat hold at each end of the ramp.
HOLD_SECONDS = 120.0
#: Per-line noise (°C) on each thermistor.
NOISE_C = 0.05
#: How far thermistor2 sits below thermistor1.
SENSOR_OFFSET_C = 0.02
#: Clock jitter (s, s.d.) on each line's timestamp, so no capture
#: time lands exactly on a sample and the join has to be generous.
JITTER_S = 0.35
#: Dead spans with no lines at all: (fraction into the run, seconds).
GAPS = ((0.35, 30.0), (0.65, 75.0))

IMAGE_PATTERNS = ("*.png", "*.tif", "*.tiff")


def temperature_profile(elapsed, span):
    """The planted ground truth at ``elapsed`` seconds into the run:
    hold, linear ramp, hold."""
    ramp_span = max(span - 2 * HOLD_SECONDS, 1.0)
    into_ramp = min(max(elapsed - HOLD_SECONDS, 0.0), ramp_span)
    return HOLD_START_C + (HOLD_END_C - HOLD_START_C) * into_ramp / ramp_span


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    captures_dir = Path(sys.argv[1])
    output_dir = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else captures_dir.parent.parent / "heater_logs"
    )
    times = sorted(
        stamp
        for pattern in IMAGE_PATTERNS
        for path in captures_dir.glob(pattern)
        if (stamp := capture_timestamp(path)) > 0
    )
    if not times:
        raise SystemExit(f"No stamped captures in {captures_dir}")
    start, end = times[0] - 30.0, times[-1] + 30.0
    span = end - start
    random.seed(0)  # the same log every run, diffable
    dead = [(span * fraction, span * fraction + seconds) for fraction, seconds in GAPS]
    lines = []
    second = 0
    while start + second <= end:
        if any(low <= second < high for low, high in dead):
            second += 1
            continue  # the logger "stopped" here
        epoch = start + second + random.gauss(0.0, JITTER_S)
        truth = temperature_profile(second, span)
        thermistor1 = round(truth + random.gauss(0.0, NOISE_C), 2)
        thermistor2 = round(
            thermistor1 - SENSOR_OFFSET_C + random.gauss(0.0, NOISE_C / 2), 2
        )
        lines.append(
            json.dumps(
                {
                    "timestamp": datetime.fromtimestamp(epoch).isoformat(),
                    "temperatures": {
                        "thermistor2": thermistor2,
                        "thermistor1": thermistor1,
                    },
                    "_frame": "TEMP",
                    "board_timestamp": round(float(second), 2),
                }
            )
        )
        second += 1
    output_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.fromtimestamp(start).strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"{name}.jsonl"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"{log_path}: {len(lines)} TEMP lines covering "
        f"{span:.0f} s over {len(times)} captures "
        f"({HOLD_START_C:g} -> {HOLD_END_C:g} degC)"
    )


if __name__ == "__main__":
    main()
