"""Voice query prompt builder."""
from typing import List, Optional

from fitness.analysis.run_report import RunReport
from fitness.prompts.debrief import build_debrief_prompt


def build_voice_query_prompt(
    transcript: str,
    report: Optional[RunReport] = None,
) -> str:
    """
    Build prompt for a voice/text query about a recent run.

    If a RunReport is provided, the data context is prepended so Claude
    can ground its answer in objective evidence.
    """
    lines = []
    if report:
        lines.append(build_debrief_prompt(report, reflection=transcript))
    else:
        lines.append(f'Runner says: "{transcript}"')
        lines.append(
            "\nNo run data available for this session. "
            "Respond as a running coach based on the runner's description alone."
        )
    return "\n".join(lines)


def build_whisper_prompt() -> str:
    """Prompt hint for OpenAI Whisper to improve transcription of running terms."""
    return (
        "Running workout reflection. May mention: Galloway, pace, mile splits, "
        "heart rate, bpm, cadence, bonk, tempo, easy run, long run, strides, "
        "zone 2, zone 4, cardiac drift, grade-adjusted pace, GAP, elevation, "
        "Forerunner, Garmin, 10k, half marathon."
    )
