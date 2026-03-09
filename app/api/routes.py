from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Проверяет доступность сервиса и возвращает технический статус."""
    return {"status": "UP"}


# @router.post("/dispatch/convert")
# def dispatch_convert(request: Request) -> dict[str, int | str]:
#     """Принудительно запускает один цикл диспетчеризации конвертации файлов."""
#     dispatched = request.app.state.dispatcher.run_once()
#     return {"status": "OK", "dispatched": dispatched}
