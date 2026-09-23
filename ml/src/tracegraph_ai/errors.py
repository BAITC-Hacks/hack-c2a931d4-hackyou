"""Stable public exceptions for SDK consumers."""


class TraceGraphError(ValueError):
    """Base for actionable input/state errors."""


class InputValidationError(TraceGraphError):
    pass


class AnalysisNotReadyError(TraceGraphError):
    pass


class UnknownNodeError(TraceGraphError):
    pass


class InvestigationStateError(TraceGraphError):
    pass
