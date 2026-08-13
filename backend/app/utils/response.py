def success(data=None, message: str = "ok") -> dict:
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def error(
    *,
    code: str,
    message: str,
    request_id: str,
    details=None,
) -> dict:
    payload = {
        "success": False,
        # Keep FastAPI's legacy `detail` field while clients migrate to the
        # structured error contract.
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "requestId": request_id,
        },
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload
