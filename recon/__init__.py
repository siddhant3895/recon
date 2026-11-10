from .engine import run_matching
from .models import Candidate, Line, RunResult
from .normalizer import NORMALIZER_VERSION, NormalizationError, normalize_record

__all__ = [
    "Candidate",
    "Line",
    "RunResult",
    "NORMALIZER_VERSION",
    "NormalizationError",
    "normalize_record",
    "run_matching",
]
