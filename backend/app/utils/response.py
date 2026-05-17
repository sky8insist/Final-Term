def success(data=None, message: str = "ok") -> dict:
    return {
        "success": True,
        "message": message,
        "data": data,
    }
