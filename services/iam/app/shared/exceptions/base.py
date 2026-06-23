"""The shared domain-error base classes every module's own exceptions.py
builds on — framework-free, translated to HTTP in app/main.py.

Only the base class plus the two genuinely cross-domain subclasses live
here (`ForbiddenError` is raised across nearly every module's authorization
checks; `AlreadyExistsError` is the 409 base every module's own
`XAlreadyExistsError` extends). Everything else — every `*NotFoundError`,
every concrete `*AlreadyExistsError`, and anything raised by exactly one
module's business logic — lives in that module's own `exceptions.py`.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error raised out of a module's service layer."""


class AlreadyExistsError(DomainError):
    """A create/rename operation collided with an existing unique value — 409."""


class ForbiddenError(DomainError):
    """The caller is authenticated but not allowed to perform this action — 403."""
