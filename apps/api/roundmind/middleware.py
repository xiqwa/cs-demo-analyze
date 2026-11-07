import logging
from time import monotonic
from uuid import uuid4
from fastapi.responses import JSONResponse
from .logging import request_id_var


class RequestContextMiddleware:
    """Pure ASGI: correlation survives 500 handling and concurrent requests."""
    def __init__(self, app, owner):
        self.app = app
        self.owner = owner

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        token = request_id_var.set(request_id)
        scope.setdefault('state', {})['request_id'] = request_id
        started = monotonic()
        status = 500
        response_started = False
        error_code = None

        async def correlated_send(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                response_started = True
                status = message['status']
                headers = [(key, value) for key, value in message.get('headers', []) if key.lower() != b'x-request-id']
                headers.append((b'x-request-id', request_id.encode('ascii')))
                message = {**message, 'headers':headers}
            await send(message)

        try:
            try:
                await self.app(scope, receive, correlated_send)
            except Exception:
                error_code = 'internal_error'
                status = 500
                if response_started:
                    raise  # Cannot replace a partially streamed response.
                response = JSONResponse(status_code=500, content={
                    'error':{'code':'internal_error','message':'Internal server error','details':{},'retryable':False},
                    'request_id':request_id})
                await response(scope, receive, correlated_send)
        finally:
            try:
                logs = getattr(self.owner.state, 'logs', None)
                if logs is not None:
                    route = scope.get('route')
                    fields = {'method':scope.get('method'), 'route':getattr(route, 'path', '<unmatched>'),
                              'status_code':status, 'duration_ms':round((monotonic() - started) * 1000, 3)}
                    if error_code:
                        fields['error_code'] = error_code
                    level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
                    logs.emit('request_completed', level=level, **fields)
            finally:
                request_id_var.reset(token)
