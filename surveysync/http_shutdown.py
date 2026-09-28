"""Deliver the complete HTTP exit acknowledgement before stopping the service."""
from __future__ import annotations

from typing import Callable
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.concurrency import run_in_threadpool

EXIT_REQUESTED = 'surveysync.exit_after_response'


class ExitAfterResponseMiddleware:
    """Outer ASGI middleware: BaseHTTPMiddleware can buffer inner responses.

    A route-level background task or a fixed delay cannot guarantee that the
    final outer transport send has happened. Only the
    local exit route sets this internal scope marker; request data cannot set it.
    This changes no endpoint access policy and does not force-kill the app.
    """

    def __init__(self, app: ASGIApp, callback: Callable[[], None]) -> None:
        self.app = app
        self.callback = callback

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope.get('method') != 'POST' or scope.get('path') != '/api/application/exit':
            await self.app(scope, receive, send)
            return
        status = 0
        body_sent = False

        async def deliver(message: Message) -> None:
            nonlocal status, body_sent
            await send(message)
            if message['type'] == 'http.response.start':
                status = int(message['status'])
            elif message['type'] == 'http.response.body' and not message.get('more_body', False):
                body_sent = True

        await self.app(scope, receive, deliver)
        if body_sent and 200 <= status < 300 and scope.pop(EXIT_REQUESTED, False):
            await run_in_threadpool(self.callback)
