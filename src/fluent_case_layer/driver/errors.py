"""Driver-specific exceptions with actionable failure messages."""


class DriverError(RuntimeError):
    """Base class for execution-layer failures."""


class CaseValidationError(DriverError):
    """Raised when case intent cannot be compiled into a safe plan."""


class PlanConflictError(DriverError):
    """Raised when a run directory is reused with a different plan."""


class ExecutionFailedError(DriverError):
    """Raised after an action exhausts its retry policy."""


class OptionalDependencyError(DriverError):
    """Raised when an explicitly selected optional runtime is unavailable."""


class AdapterMappingError(DriverError):
    """Raised when semantic intent has no safe implementation in an adapter."""
