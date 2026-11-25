"""FastAPI 适配层：把 handlers 的 (status_code, body) 映射成 HTTP 响应。

本单只需要两个只读接口，无写操作、无权限码（读统计与知识管理员角色一致）。
用例层 handlers.py 不依赖框架，集成时可直接挂到既有 app 上。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from taxonomy_stats import handlers


def _reply(result: tuple[int, dict]) -> JSONResponse:
    status, body = result
    return JSONResponse(status_code=status, content=body)


def create_app(store) -> FastAPI:
    app = FastAPI(title="taxonomy-stats", version="1.0")
    app.state.store = store

    @app.get("/api/taxonomy/tags/{tag_id}/stats")
    async def tag_stats(tag_id: str, request: Request):
        return _reply(handlers.handle_tag_stats(request.app.state.store, tag_id))

    @app.get("/api/taxonomy/dicts/{dict_code}/stats")
    async def dict_stats(dict_code: str, request: Request, limit: int = 10):
        return _reply(handlers.handle_dict_stats(request.app.state.store, dict_code, limit))

    return app
