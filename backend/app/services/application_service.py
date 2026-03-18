from fastapi import HTTPException

from app.models.application import ApplicationStatus

# Valid system-triggered transitions only
VALID_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.IN_PROGRESS: {ApplicationStatus.APPLIED},
    ApplicationStatus.APPLIED: {ApplicationStatus.INTERVIEW, ApplicationStatus.REJECTED},
    ApplicationStatus.INTERVIEW: {ApplicationStatus.OFFER, ApplicationStatus.REJECTED},
    ApplicationStatus.OFFER: set(),
    ApplicationStatus.REJECTED: set(),
}


def apply_status_transition(
    current_status: ApplicationStatus,
    new_status: ApplicationStatus,
    is_system_triggered: bool = True,
) -> None:
    """
    Validate a status transition.

    System-triggered (poll worker): enforces VALID_TRANSITIONS, raises 400 on invalid.
    Manual (user PATCH): allows any target except IN_PROGRESS, raises 400 if IN_PROGRESS.
    """
    if not is_system_triggered:
        if new_status == ApplicationStatus.IN_PROGRESS:
            raise HTTPException(
                status_code=400,
                detail="Cannot set status to IN_PROGRESS via manual update",
            )
        return  # manual override bypasses transition rules entirely

    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition: {current_status.value} → {new_status.value}",
        )
