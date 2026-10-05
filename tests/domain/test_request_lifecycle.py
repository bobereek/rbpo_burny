from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from uuid import UUID

import pytest

from wildburny.domain import requests as domain_requests
from wildburny.domain.requests import (
    DomainError,
    HistoryEvent,
    InvalidActionData,
    InvalidTransition,
    PurchaseRequest,
    RequestAction,
    RequestStatus,
)

REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


class TimezoneWithoutOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None


INVALID_TIMES = [
    None,
    "2026-09-27T12:00:00Z",
    0,
    date(2026, 9, 27),
    datetime(2026, 9, 27, 12, 0),
    datetime(2026, 9, 27, 12, 0, tzinfo=TimezoneWithoutOffset()),
]
INVALID_IDS = [0, -1, True, False, 1.5, "10", None]
INVALID_TEXT = ["", "   ", "\t\n", None, 42, False, ["WB-42"]]
VALID_TRANSITIONS = [
    (RequestStatus.SUBMITTED, RequestAction.APPROVE, RequestStatus.APPROVED),
    (RequestStatus.SUBMITTED, RequestAction.REJECT, RequestStatus.REJECTED),
    (RequestStatus.APPROVED, RequestAction.PLACE_ORDER, RequestStatus.ORDERED),
    (RequestStatus.ORDERED, RequestAction.COMPLETE, RequestStatus.COMPLETED),
]
INVALID_TRANSITIONS = [
    (RequestStatus.APPROVED, RequestAction.APPROVE),
    (RequestStatus.REJECTED, RequestAction.APPROVE),
    (RequestStatus.ORDERED, RequestAction.APPROVE),
    (RequestStatus.COMPLETED, RequestAction.APPROVE),
    (RequestStatus.APPROVED, RequestAction.REJECT),
    (RequestStatus.REJECTED, RequestAction.REJECT),
    (RequestStatus.ORDERED, RequestAction.REJECT),
    (RequestStatus.COMPLETED, RequestAction.REJECT),
    (RequestStatus.SUBMITTED, RequestAction.PLACE_ORDER),
    (RequestStatus.REJECTED, RequestAction.PLACE_ORDER),
    (RequestStatus.ORDERED, RequestAction.PLACE_ORDER),
    (RequestStatus.COMPLETED, RequestAction.PLACE_ORDER),
    (RequestStatus.SUBMITTED, RequestAction.COMPLETE),
    (RequestStatus.APPROVED, RequestAction.COMPLETE),
    (RequestStatus.REJECTED, RequestAction.COMPLETE),
    (RequestStatus.COMPLETED, RequestAction.COMPLETE),
]


def restored_request(status: RequestStatus) -> PurchaseRequest:
    order_number = "WB-42" if status in {RequestStatus.ORDERED, RequestStatus.COMPLETED} else None
    return PurchaseRequest.restore(
        request_id=REQUEST_ID,
        author_id=10,
        department_id=20,
        status=status,
        order_number=order_number,
    )


def request_snapshot(request: PurchaseRequest) -> tuple:
    return (
        request.id,
        request.author_id,
        request.department_id,
        request.status,
        request.order_number,
    )


def perform_action(
    request: PurchaseRequest,
    action: RequestAction,
    *,
    actor_id: object = 30,
    occurred_at: object = NOW,
) -> HistoryEvent:
    match action:
        case RequestAction.APPROVE:
            return request.approve(actor_id=actor_id, occurred_at=occurred_at)
        case RequestAction.REJECT:
            return request.reject(
                actor_id=actor_id, reason="  Over budget  ", occurred_at=occurred_at
            )
        case RequestAction.PLACE_ORDER:
            return request.place_order(
                actor_id=actor_id, order_number="  WB-43  ", occurred_at=occurred_at
            )
        case RequestAction.COMPLETE:
            return request.complete(actor_id=actor_id, occurred_at=occurred_at)
        case _:
            raise AssertionError(f"Unsupported test action: {action}")


def test_statuses_and_actions_match_public_contract() -> None:
    assert {status.name for status in RequestStatus} == {
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "ORDERED",
        "COMPLETED",
    }
    assert {action.name for action in RequestAction} == {
        "SUBMIT",
        "APPROVE",
        "REJECT",
        "PLACE_ORDER",
        "COMPLETE",
    }


def test_submit_creates_submitted_request_and_complete_history_event() -> None:
    request, event = PurchaseRequest.submit(
        request_id=REQUEST_ID,
        author_id=10,
        department_id=20,
        occurred_at=NOW,
    )

    assert request_snapshot(request) == (REQUEST_ID, 10, 20, RequestStatus.SUBMITTED, None)
    assert event == HistoryEvent(
        request_id=REQUEST_ID,
        actor_id=10,
        action=RequestAction.SUBMIT,
        from_status=None,
        to_status=RequestStatus.SUBMITTED,
        occurred_at=NOW,
        reason=None,
        order_number=None,
    )


@pytest.mark.parametrize("status", list(RequestStatus))
def test_restore_returns_only_a_request_for_every_consistent_state(status: RequestStatus) -> None:
    request = restored_request(status)
    expected_order = "WB-42" if status in {RequestStatus.ORDERED, RequestStatus.COMPLETED} else None

    assert isinstance(request, PurchaseRequest)
    assert request_snapshot(request) == (REQUEST_ID, 10, 20, status, expected_order)


@pytest.mark.parametrize("status", [RequestStatus.ORDERED, RequestStatus.COMPLETED])
def test_restore_normalizes_saved_order_number(status: RequestStatus) -> None:
    request = PurchaseRequest.restore(
        request_id=REQUEST_ID,
        author_id=10,
        department_id=20,
        status=status,
        order_number=" \tWB-42\n ",
    )

    assert request.status is status
    assert request.order_number == "WB-42"


@pytest.mark.parametrize(
    "status", [RequestStatus.SUBMITTED, RequestStatus.APPROVED, RequestStatus.REJECTED]
)
@pytest.mark.parametrize("order_number", ["WB-42", "", "   ", 42, False])
def test_restore_rejects_any_order_number_before_ordering(
    status: RequestStatus, order_number: object
) -> None:
    with pytest.raises(InvalidActionData) as error:
        PurchaseRequest.restore(
            request_id=REQUEST_ID,
            author_id=10,
            department_id=20,
            status=status,
            order_number=order_number,
        )

    assert error.value.field == "order_number"


@pytest.mark.parametrize("status", [RequestStatus.ORDERED, RequestStatus.COMPLETED])
@pytest.mark.parametrize("order_number", INVALID_TEXT)
def test_restore_requires_valid_order_number_after_ordering(
    status: RequestStatus, order_number: object
) -> None:
    with pytest.raises(InvalidActionData) as error:
        PurchaseRequest.restore(
            request_id=REQUEST_ID,
            author_id=10,
            department_id=20,
            status=status,
            order_number=order_number,
        )

    assert error.value.field == "order_number"


@pytest.mark.parametrize("status", ["SUBMITTED", "UNKNOWN", None, 0, RequestAction.SUBMIT])
def test_restore_rejects_status_that_is_not_a_request_status(status: object) -> None:
    with pytest.raises(InvalidActionData) as error:
        PurchaseRequest.restore(
            request_id=REQUEST_ID,
            author_id=10,
            department_id=20,
            status=status,
            order_number=None,
        )

    assert error.value.field == "status"


@pytest.mark.parametrize("factory_name", ["submit", "restore"])
@pytest.mark.parametrize("field", ["author_id", "department_id"])
@pytest.mark.parametrize("invalid_id", INVALID_IDS)
def test_factories_reject_invalid_integer_ids(
    factory_name: str, field: str, invalid_id: object
) -> None:
    kwargs = {"request_id": REQUEST_ID, "author_id": 10, "department_id": 20}
    kwargs.update(
        {"occurred_at": NOW}
        if factory_name == "submit"
        else {"status": RequestStatus.SUBMITTED, "order_number": None}
    )
    kwargs[field] = invalid_id

    with pytest.raises(InvalidActionData) as error:
        getattr(PurchaseRequest, factory_name)(**kwargs)

    assert error.value.field == field
    assert str(error.value)


@pytest.mark.parametrize("factory_name", ["submit", "restore"])
@pytest.mark.parametrize("request_id", [str(REQUEST_ID), 1, True, None])
def test_factories_require_uuid_objects(factory_name: str, request_id: object) -> None:
    kwargs = {"request_id": request_id, "author_id": 10, "department_id": 20}
    kwargs.update(
        {"occurred_at": NOW}
        if factory_name == "submit"
        else {"status": RequestStatus.SUBMITTED, "order_number": None}
    )

    with pytest.raises(InvalidActionData) as error:
        getattr(PurchaseRequest, factory_name)(**kwargs)

    assert error.value.field == "request_id"


@pytest.mark.parametrize("occurred_at", INVALID_TIMES)
def test_submit_requires_aware_datetime(occurred_at: object) -> None:
    with pytest.raises(InvalidActionData) as error:
        PurchaseRequest.submit(
            request_id=REQUEST_ID,
            author_id=10,
            department_id=20,
            occurred_at=occurred_at,
        )

    assert error.value.field == "occurred_at"


@pytest.mark.parametrize(("status", "action", "target"), VALID_TRANSITIONS)
def test_allowed_transition_returns_one_complete_event(
    status: RequestStatus, action: RequestAction, target: RequestStatus
) -> None:
    request = restored_request(status)
    expected_order = {
        RequestAction.APPROVE: None,
        RequestAction.REJECT: None,
        RequestAction.PLACE_ORDER: "WB-43",
        RequestAction.COMPLETE: "WB-42",
    }[action]

    event = perform_action(request, action)

    assert isinstance(event, HistoryEvent)
    assert event == HistoryEvent(
        request_id=REQUEST_ID,
        actor_id=30,
        action=action,
        from_status=status,
        to_status=target,
        occurred_at=NOW,
        reason="Over budget" if action is RequestAction.REJECT else None,
        order_number=expected_order,
    )
    assert request_snapshot(request) == (REQUEST_ID, 10, 20, target, expected_order)


@pytest.mark.parametrize(("status", "action"), INVALID_TRANSITIONS)
def test_forbidden_transition_does_not_change_request(
    status: RequestStatus, action: RequestAction
) -> None:
    request = restored_request(status)
    before = request_snapshot(request)

    with pytest.raises(InvalidTransition) as error:
        perform_action(request, action)

    assert error.value.status is status
    assert error.value.action is action
    assert request_snapshot(request) == before


@pytest.mark.parametrize(("status", "action", "target"), VALID_TRANSITIONS)
@pytest.mark.parametrize("actor_id", INVALID_IDS)
def test_invalid_actor_does_not_change_request_for_any_action(
    status: RequestStatus, action: RequestAction, target: RequestStatus, actor_id: object
) -> None:
    request = restored_request(status)
    before = request_snapshot(request)

    with pytest.raises(InvalidActionData) as error:
        perform_action(request, action, actor_id=actor_id)

    assert error.value.field == "actor_id"
    assert request_snapshot(request) == before


@pytest.mark.parametrize(("status", "action", "target"), VALID_TRANSITIONS)
@pytest.mark.parametrize("occurred_at", INVALID_TIMES)
def test_invalid_time_does_not_change_request_for_any_action(
    status: RequestStatus, action: RequestAction, target: RequestStatus, occurred_at: object
) -> None:
    request = restored_request(status)
    before = request_snapshot(request)

    with pytest.raises(InvalidActionData) as error:
        perform_action(request, action, occurred_at=occurred_at)

    assert error.value.field == "occurred_at"
    assert request_snapshot(request) == before


@pytest.mark.parametrize("reason", INVALID_TEXT)
def test_invalid_rejection_reason_does_not_change_request(reason: object) -> None:
    request = restored_request(RequestStatus.SUBMITTED)
    before = request_snapshot(request)

    with pytest.raises(InvalidActionData) as error:
        request.reject(actor_id=30, reason=reason, occurred_at=NOW)

    assert error.value.field == "reason"
    assert request_snapshot(request) == before


@pytest.mark.parametrize("order_number", INVALID_TEXT)
def test_invalid_order_number_does_not_change_request(order_number: object) -> None:
    request = restored_request(RequestStatus.APPROVED)
    before = request_snapshot(request)

    with pytest.raises(InvalidActionData) as error:
        request.place_order(actor_id=40, order_number=order_number, occurred_at=NOW)

    assert error.value.field == "order_number"
    assert request_snapshot(request) == before


@pytest.mark.parametrize(("status", "action", "target"), VALID_TRANSITIONS)
def test_repeated_action_is_rejected_without_changing_request(
    status: RequestStatus, action: RequestAction, target: RequestStatus
) -> None:
    request = restored_request(status)
    perform_action(request, action)
    before = request_snapshot(request)

    with pytest.raises(InvalidTransition) as error:
        perform_action(request, action)

    assert error.value.status is target
    assert error.value.action is action
    assert request_snapshot(request) == before


def test_complete_lifecycle_preserves_each_event_and_supplied_time() -> None:
    local_time = datetime(2026, 9, 27, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    times = [local_time + timedelta(minutes=step) for step in range(4)]
    request, submitted = PurchaseRequest.submit(
        request_id=REQUEST_ID, author_id=10, department_id=20, occurred_at=times[0]
    )
    approved = request.approve(actor_id=30, occurred_at=times[1])
    ordered = request.place_order(actor_id=40, order_number=" \tWB 42\n", occurred_at=times[2])
    completed = request.complete(actor_id=50, occurred_at=times[3])

    assert [submitted, approved, ordered, completed] == [
        HistoryEvent(REQUEST_ID, 10, RequestAction.SUBMIT, None, RequestStatus.SUBMITTED, times[0]),
        HistoryEvent(
            REQUEST_ID,
            30,
            RequestAction.APPROVE,
            RequestStatus.SUBMITTED,
            RequestStatus.APPROVED,
            times[1],
        ),
        HistoryEvent(
            REQUEST_ID,
            40,
            RequestAction.PLACE_ORDER,
            RequestStatus.APPROVED,
            RequestStatus.ORDERED,
            times[2],
            order_number="WB 42",
        ),
        HistoryEvent(
            REQUEST_ID,
            50,
            RequestAction.COMPLETE,
            RequestStatus.ORDERED,
            RequestStatus.COMPLETED,
            times[3],
            order_number="WB 42",
        ),
    ]
    assert [event.occurred_at for event in [submitted, approved, ordered, completed]] == times
    assert submitted.occurred_at.tzinfo is local_time.tzinfo
    assert request_snapshot(request) == (REQUEST_ID, 10, 20, RequestStatus.COMPLETED, "WB 42")


def test_rejection_lifecycle_preserves_initial_history() -> None:
    request, submitted = PurchaseRequest.submit(
        request_id=REQUEST_ID, author_id=10, department_id=20, occurred_at=NOW
    )
    rejected = request.reject(actor_id=30, reason="\tNeeds a  new budget\n", occurred_at=NOW)

    assert rejected == HistoryEvent(
        REQUEST_ID,
        30,
        RequestAction.REJECT,
        RequestStatus.SUBMITTED,
        RequestStatus.REJECTED,
        NOW,
        reason="Needs a  new budget",
    )
    assert submitted.to_status is RequestStatus.SUBMITTED
    assert submitted.reason is None
    assert submitted.order_number is None
    assert request_snapshot(request) == (REQUEST_ID, 10, 20, RequestStatus.REJECTED, None)


@pytest.mark.parametrize(
    ("field", "value"), [("status", RequestStatus.COMPLETED), ("order_number", "forged")]
)
def test_state_and_order_number_have_no_public_setters(field: str, value: object) -> None:
    request = restored_request(RequestStatus.SUBMITTED)
    before = request_snapshot(request)

    with pytest.raises(AttributeError):
        setattr(request, field, value)

    assert request_snapshot(request) == before


def test_plain_constructor_is_not_public() -> None:
    with pytest.raises(TypeError, match="submit.*restore"):
        PurchaseRequest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", UUID("22222222-2222-4222-8222-222222222222")),
        ("actor_id", 99),
        ("action", RequestAction.COMPLETE),
        ("from_status", RequestStatus.ORDERED),
        ("to_status", RequestStatus.COMPLETED),
        ("occurred_at", NOW + timedelta(days=1)),
        ("reason", "forged"),
        ("order_number", "forged"),
    ],
)
def test_all_history_event_fields_are_frozen(field: str, value: object) -> None:
    _, event = PurchaseRequest.submit(
        request_id=REQUEST_ID, author_id=10, department_id=20, occurred_at=NOW
    )

    with pytest.raises(FrozenInstanceError):
        setattr(event, field, value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        *[("request_id", value) for value in [str(REQUEST_ID), 1, True, None]],
        *[("actor_id", value) for value in INVALID_IDS],
        *[("occurred_at", value) for value in INVALID_TIMES],
        ("action", "SUBMIT"),
        ("action", None),
        ("action", RequestStatus.SUBMITTED),
        ("from_status", "SUBMITTED"),
        ("from_status", RequestAction.SUBMIT),
        ("to_status", "SUBMITTED"),
        ("to_status", None),
        ("to_status", RequestAction.SUBMIT),
    ],
)
def test_history_event_validates_required_typed_fields(field: str, value: object) -> None:
    kwargs = {
        "request_id": REQUEST_ID,
        "actor_id": 10,
        "action": RequestAction.SUBMIT,
        "from_status": None,
        "to_status": RequestStatus.SUBMITTED,
        "occurred_at": NOW,
    }
    kwargs[field] = value

    with pytest.raises(InvalidActionData) as error:
        HistoryEvent(**kwargs)

    assert error.value.field == field
    assert str(error.value)


def test_factories_require_keyword_arguments() -> None:
    with pytest.raises(TypeError):
        PurchaseRequest.submit(REQUEST_ID, 10, 20, NOW)

    with pytest.raises(TypeError):
        PurchaseRequest.restore(REQUEST_ID, 10, 20, RequestStatus.SUBMITTED, None)


@pytest.mark.parametrize(
    ("status", "method_name", "args"),
    [
        (RequestStatus.SUBMITTED, "approve", (30, NOW)),
        (RequestStatus.SUBMITTED, "reject", (30, "Over budget", NOW)),
        (RequestStatus.APPROVED, "place_order", (40, "WB-43", NOW)),
        (RequestStatus.ORDERED, "complete", (40, NOW)),
    ],
)
def test_actions_require_keyword_arguments_without_changing_request(
    status: RequestStatus, method_name: str, args: tuple
) -> None:
    request = restored_request(status)
    before = request_snapshot(request)

    with pytest.raises(TypeError):
        getattr(request, method_name)(*args)

    assert request_snapshot(request) == before


@pytest.mark.parametrize(
    "name",
    [
        "DomainError",
        "HistoryEvent",
        "InvalidActionData",
        "InvalidTransition",
        "PurchaseRequest",
        "RequestAction",
        "RequestStatus",
    ],
)
def test_domain_package_exports_public_api(name: str) -> None:
    import wildburny.domain

    assert getattr(wildburny.domain, name) is getattr(domain_requests, name)
    assert name in wildburny.domain.__all__


def test_domain_errors_share_a_base_exception() -> None:
    assert issubclass(DomainError, Exception)
    assert issubclass(InvalidActionData, DomainError)
    assert issubclass(InvalidTransition, DomainError)
