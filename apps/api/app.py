from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.concurrency import run_in_threadpool
from roundmind.config import Settings, VERSION
from roundmind.database import Database, MigrationError
from roundmind.logging import LogSession
from roundmind.middleware import RequestContextMiddleware
from roundmind.schemas import HealthResponse
from roundmind.imports import DemoService, router as demo_router


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        # Resolve configuration at startup, not import, so tests and CLI have
        # no import-time filesystem effects.
        configured = settings or Settings.from_env()
        logs = LogSession(configured)
        db = Database(configured)
        app.state.logs = logs
        app.state.database = db
        try:
            try:
                await run_in_threadpool(db.initialize)
            except Exception as exc:
                code = str(exc) if isinstance(exc, MigrationError) else 'migration_failed'
                logs.emit('startup_failed', level=logging.ERROR, error_code=code)
                raise RuntimeError(code) from None
            app.state.demos = DemoService(configured, db)
            logs.emit('startup_ready', revision='0001_initial')
            yield
        finally:
            if hasattr(app.state, 'demos'):
                await run_in_threadpool(app.state.demos.close)
            db.close()
            logs.emit('shutdown')
            logs.close()
            app.state.logs = None

    app = FastAPI(title='RoundMind Local API', version=VERSION, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[
        'http://localhost:5173', 'http://127.0.0.1:5173',
        'tauri://localhost', 'http://tauri.localhost'], allow_methods=['GET','POST'],
        allow_headers=['Content-Type','X-Demo-Filename'], expose_headers=['X-Request-ID'])
    app.add_middleware(RequestContextMiddleware, owner=app)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={
            'error':{'code':'invalid_request','message':'Invalid request parameters','details':{},'retryable':False},
            'request_id':request.state.request_id})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={
            'error':{'code':'not_found' if exc.status_code == 404 else 'http_error',
                     'message':'Not Found' if exc.status_code == 404 else 'Request failed',
                     'details':{},'retryable':False},
            'request_id':request.state.request_id})

    @app.get('/api/v1/health', response_model=HealthResponse,
             responses={503:{'model':HealthResponse, 'description':'Database unavailable or schema mismatch'}})
    async def health(request: Request, response: Response):
        state = await run_in_threadpool(request.app.state.database.health)
        ready = state['status'] == 'ready'
        response.status_code = 200 if ready else 503
        return {'data':{'status':'ok' if ready else 'degraded', 'service':'roundmind-api', 'database':state},
                'meta':{'request_id':request.state.request_id,'version':VERSION}}

    app.include_router(demo_router)
    return app


app = create_app()
