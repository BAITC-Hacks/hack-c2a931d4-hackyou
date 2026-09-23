"""TraceGraph public SDK."""

from .config import AnalysisConfig
from .serialization import ENGINE_VERSION as __version__

__all__ = ["TraceGraph", "AnalysisConfig", "__version__"]


def __getattr__(name):
    if name == "TraceGraph":
        from .engine import TraceGraph
        return TraceGraph
    raise AttributeError(name)
