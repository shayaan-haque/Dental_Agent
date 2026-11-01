"""Keep expected tool failures actionable without exposing database internals."""

import logging

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from dental_agent.services.booking import AppointmentError

logger = logging.getLogger(__name__)


def appointment_result(operation, **kwargs):
    try:
        return operation(**kwargs)
    except AppointmentError as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
    except ValueError as exc:
        return {"ok": False, "code": "invalid_request", "message": str(exc)}
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_booked_appointment_per_slot":
            return {"ok": False, "code": "slot_taken", "message": "That slot was just booked. Search again."}
        logger.exception("Appointment integrity error")
        return {"ok": False, "code": "database_error", "message": "Could not complete the request. Check your saved appointments before retrying."}
    except SQLAlchemyError:
        logger.exception("Appointment database error")
        return {"ok": False, "code": "database_error", "message": "Could not confirm the result. Check your saved appointments before retrying."}
