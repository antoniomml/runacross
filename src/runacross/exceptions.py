"""Public exception types for configuration and discovery failures."""


class RunAcrossError(Exception):
    """Base for RunAcross-specific configuration/discovery errors.

    Built-in ``TypeError`` and ``ValueError`` validation failures do not
    inherit from this class.
    Per-target authentication and callback exceptions stay on result objects
    and are not wrapped in this hierarchy.
    """


class ConfigError(RunAcrossError):
    """Configuration or discovery cannot proceed.

    Raised by account and Region discovery helpers when arguments, local
    profile data, or inventory responses are unusable. ``TypeError`` remains
    the type-check failure. AWS ``ClientError`` responses are not wrapped.
    """
