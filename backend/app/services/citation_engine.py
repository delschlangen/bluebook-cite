"""The shared citation engine, built once from the spec.

Importing the transforms module registers every transform the spec's templates call,
so this is the one place both are guaranteed to be loaded together.
"""

from ..utils.citation_spec import SPEC
from . import transforms  # noqa: F401  (registers the template transforms)
from .spec_engine import Engine

ENGINE = Engine(SPEC)
