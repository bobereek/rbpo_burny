"""Purchase request lifecycle; access checks and persistence belong to adapters.

Each successful action returns one event. The application must save the request
and its event in one transaction and guard against concurrent stale writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RequestStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"


class RequestAction(StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    PLACE_ORDER = "PLACE_ORDER"
    COMPLETE = "COMPLETE"


class DomainError(ValueError):
    """Base class for safe domain failures."""


class InvalidActionData(DomainError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


class InvalidTransition(DomainError):
    def __init__(self, status: RequestStatus, action: RequestAction) -> None:
        self.status = status
        self.action = action
        super().__init__(f"Action {action} is not allowed from {status}")


def _require_uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise InvalidActionData(field, f"{field} must be a UUID")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise InvalidActionData(field, f"{field} must be a positive integer")
    return value


def _require_aware_datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidActionData("occurred_at", "occurred_at must include a timezone")
    return value


def _normalize_nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidActionData(field, f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    """An immutable action result, created before changing the request."""

    request_id: UUID
    actor_id: int
    action: RequestAction
    from_status: RequestStatus | None
    to_status: RequestStatus
    occurred_at: datetime
    reason: str | None = None
    order_number: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.request_id, "request_id")
        _require_positive_int(self.actor_id, "actor_id")
        if not isinstance(self.action, RequestAction):
            raise InvalidActionData("action", "action must be a RequestAction")
        if self.from_status is not None and not isinstance(self.from_status, RequestStatus):
            raise InvalidActionData("from_status", "from_status must be a RequestStatus or None")
        if not isinstance(self.to_status, RequestStatus):
            raise InvalidActionData("to_status", "to_status must be a RequestStatus")
        _require_aware_datetime(self.occurred_at)


@dataclass(slots=True, init=False)
class PurchaseRequest:
    """Use submit for new requests and restore for validated persisted state."""

    _id: UUID
    _author_id: int
    _department_id: int
    _status: RequestStatus
    _order_number: str | None

    def __init__(self) -> None:
        raise TypeError("Use PurchaseRequest.submit() or PurchaseRequest.restore()")

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def author_id(self) -> int:
        return self._author_id

    @property
    def department_id(self) -> int:
        return self._department_id

    @property
    def status(self) -> RequestStatus:
        return self._status

    @property
    def order_number(self) -> str | None:
        return self._order_number

    @classmethod
    def _build(
        cls,
        *,
        request_id: UUID,
        author_id: int,
        department_id: int,
        status: RequestStatus,
        order_number: str | None,
    ) -> PurchaseRequest:
        request = object.__new__(cls)
        request._id = _require_uuid(request_id, "request_id")
        request._author_id = _require_positive_int(author_id, "author_id")
        request._department_id = _require_positive_int(department_id, "department_id")
        if not isinstance(status, RequestStatus):
            raise InvalidActionData("status", "status must be a RequestStatus")
        request._status = status
        if status in {RequestStatus.ORDERED, RequestStatus.COMPLETED}:
            request._order_number = _normalize_nonblank(order_number, "order_number")
        elif order_number is not None:
            raise InvalidActionData("order_number", "order_number is not allowed in this state")
        else:
            request._order_number = None
        return request

    @classmethod
    def submit(
        cls,
        *,
        request_id: UUID,
        author_id: int,
        department_id: int,
        occurred_at: datetime,
    ) -> tuple[PurchaseRequest, HistoryEvent]:
        request = cls._build(
            request_id=request_id,
            author_id=author_id,
            department_id=department_id,
            status=RequestStatus.SUBMITTED,
            order_number=None,
        )
        event = HistoryEvent(
            request_id=request.id,
            actor_id=request.author_id,
            action=RequestAction.SUBMIT,
            from_status=None,
            to_status=RequestStatus.SUBMITTED,
            occurred_at=occurred_at,
        )
        return request, event

    @classmethod
    def restore(
        cls,
        *,
        request_id: UUID,
        author_id: int,
        department_id: int,
        status: RequestStatus,
        order_number: str | None,
    ) -> PurchaseRequest:
        return cls._build(
            request_id=request_id,
            author_id=author_id,
            department_id=department_id,
            status=status,
            order_number=order_number,
        )

    def _ensure_transition(self, *, expected: RequestStatus, action: RequestAction) -> None:
        if self.status is not expected:
            raise InvalidTransition(self.status, action)

    def _new_event(
        self,
        *,
        actor_id: int,
        action: RequestAction,
        to_status: RequestStatus,
        occurred_at: datetime,
        reason: str | None = None,
        order_number: str | None = None,
    ) -> HistoryEvent:
        return HistoryEvent(
            request_id=self.id,
            actor_id=actor_id,
            action=action,
            from_status=self.status,
            to_status=to_status,
            occurred_at=occurred_at,
            reason=reason,
            order_number=order_number,
        )

    def approve(self, *, actor_id: int, occurred_at: datetime) -> HistoryEvent:
        self._ensure_transition(expected=RequestStatus.SUBMITTED, action=RequestAction.APPROVE)
        event = self._new_event(
            actor_id=actor_id,
            action=RequestAction.APPROVE,
            to_status=RequestStatus.APPROVED,
            occurred_at=occurred_at,
        )
        self._status = RequestStatus.APPROVED
        return event

    def reject(self, *, actor_id: int, reason: str, occurred_at: datetime) -> HistoryEvent:
        self._ensure_transition(expected=RequestStatus.SUBMITTED, action=RequestAction.REJECT)
        normalized_reason = _normalize_nonblank(reason, "reason")
        event = self._new_event(
            actor_id=actor_id,
            action=RequestAction.REJECT,
            to_status=RequestStatus.REJECTED,
            occurred_at=occurred_at,
            reason=normalized_reason,
        )
        self._status = RequestStatus.REJECTED
        return event

    def place_order(
        self, *, actor_id: int, order_number: str, occurred_at: datetime
    ) -> HistoryEvent:
        self._ensure_transition(expected=RequestStatus.APPROVED, action=RequestAction.PLACE_ORDER)
        normalized_order_number = _normalize_nonblank(order_number, "order_number")
        event = self._new_event(
            actor_id=actor_id,
            action=RequestAction.PLACE_ORDER,
            to_status=RequestStatus.ORDERED,
            occurred_at=occurred_at,
            order_number=normalized_order_number,
        )
        self._order_number = normalized_order_number
        self._status = RequestStatus.ORDERED
        return event

    def complete(self, *, actor_id: int, occurred_at: datetime) -> HistoryEvent:
        self._ensure_transition(expected=RequestStatus.ORDERED, action=RequestAction.COMPLETE)
        normalized_order_number = _normalize_nonblank(self.order_number, "order_number")
        event = self._new_event(
            actor_id=actor_id,
            action=RequestAction.COMPLETE,
            to_status=RequestStatus.COMPLETED,
            occurred_at=occurred_at,
            order_number=normalized_order_number,
        )
        self._status = RequestStatus.COMPLETED
        return event
