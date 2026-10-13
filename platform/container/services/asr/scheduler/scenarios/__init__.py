from collections.abc import Awaitable, Callable
from pathlib import Path

from scheduler.inference import Inference
from scheduler.options import Options
from scheduler.scenarios.conversation import moss_joint as conversation_moss
from scheduler.scenarios.conversation import qwen_pyannote
from scheduler.scenarios.conversation import vibevoice as conversation_vibe
from scheduler.scenarios.conversation_tracks import firered as tracks_firered
from scheduler.scenarios.conversation_tracks import qwen as tracks_qwen
from scheduler.scenarios.meeting import moss_joint as meeting_moss
from scheduler.scenarios.meeting import qwen_nemotron
from scheduler.scenarios.meeting import vibevoice as meeting_vibe
from scheduler.scenarios.narration import firered as narration_firered
from scheduler.scenarios.narration import qwen as narration_qwen
from scheduler.transcript import Transcript

type Recipe = Callable[[Inference, Path, int, Options], Awaitable[Transcript]]

RECIPES: dict[str, dict[str, Recipe]] = {
    "narration": {"qwen": narration_qwen.transcribe, "firered": narration_firered.transcribe},
    "conversation_tracks": {"qwen": tracks_qwen.transcribe, "firered": tracks_firered.transcribe},
    "conversation": {
        "moss_joint": conversation_moss.transcribe,
        "qwen_pyannote": qwen_pyannote.transcribe,
        "vibevoice": conversation_vibe.transcribe,
    },
    "meeting": {
        "moss_joint": meeting_moss.transcribe,
        "qwen_nemotron": qwen_nemotron.transcribe,
        "vibevoice": meeting_vibe.transcribe,
    },
}
