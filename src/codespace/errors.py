"""Expected resource errors shared by control-plane operations."""


class ResourceNotFound(Exception):
    """The requested resource or configured placement does not exist."""


class ResourceConflict(Exception):
    """The resource state prevents the requested operation."""
