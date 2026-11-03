from fastapi import APIRouter, FastAPI
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Scope

from ascend_python_common.route_lookup import resolve_route, resolve_route_handler


def _scope(path: str, method: str = "GET") -> Scope:
    return {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
    }


def _sample_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/api")

    @router.get("/limited")
    def limited() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/jobs/{job_id}")
    def read_job(job_id: str) -> dict[str, str]:
        return {"job_id": job_id}

    app.include_router(router)

    @app.get("/direct")
    def direct() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_a_direct_route_resolves_to_its_endpoint_and_template() -> None:
    # given
    app = _sample_app()
    # when
    endpoint, template = resolve_route(app.routes, _scope("/direct"))
    # then
    assert endpoint is not None
    assert endpoint.__name__ == "direct"
    assert template == "/direct"


def test_an_included_router_route_resolves_with_its_prefix() -> None:
    # given
    app = _sample_app()
    # when
    endpoint, template = resolve_route(app.routes, _scope("/api/limited"))
    # then
    assert endpoint is not None
    assert endpoint.__name__ == "limited"
    assert template == "/api/limited"


def test_a_path_parameter_resolves_to_the_template_not_the_raw_path() -> None:
    # given
    app = _sample_app()
    # when
    endpoint, template = resolve_route(app.routes, _scope("/api/jobs/some-id"))
    # then
    assert endpoint is not None
    assert endpoint.__name__ == "read_job"
    assert template == "/api/jobs/{job_id}"


def test_an_unknown_path_resolves_to_nothing() -> None:
    # given
    app = _sample_app()
    # when
    endpoint, template = resolve_route(app.routes, _scope("/api/missing"))
    # then
    assert endpoint is None
    assert template is None
    assert resolve_route_handler(app.routes, _scope("/api/missing")) is None


def test_a_method_the_route_does_not_support_resolves_to_nothing() -> None:
    # given
    app = _sample_app()
    # when
    endpoint, template = resolve_route(app.routes, _scope("/api/limited", method="POST"))
    # then
    assert endpoint is None
    assert template is None


def test_a_route_inside_a_mount_resolves_through_the_mount() -> None:
    # given
    async def inner(scope: Scope, receive: object, send: object) -> None:
        response = JSONResponse({"status": "ok"})
        await response(scope, receive, send)  # type: ignore[arg-type]

    routes = [Mount("/sub", routes=[Route("/inner", endpoint=inner)])]
    # when
    endpoint, template = resolve_route(routes, _scope("/sub/inner"))
    # then
    assert endpoint is inner
    assert template == "/sub/inner"


def test_a_mount_without_a_match_inside_resolves_to_nothing() -> None:
    # given
    async def inner(scope: Scope, receive: object, send: object) -> None:
        response = JSONResponse({"status": "ok"})
        await response(scope, receive, send)  # type: ignore[arg-type]

    routes = [Mount("/sub", routes=[Route("/inner", endpoint=inner)])]
    # when
    endpoint, template = resolve_route(routes, _scope("/sub/elsewhere"))
    # then
    assert endpoint is None
    assert template is None
