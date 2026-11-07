"""Single-worker localhost launcher with sanitized Uvicorn logs."""
import uvicorn

LOG_CONFIG = {
    'version':1, 'disable_existing_loggers':False,
    'formatters':{'safe':{'()':'roundmind.logging.JsonFormatter'}},
    'handlers':{'safe':{'class':'logging.StreamHandler','formatter':'safe','stream':'ext://sys.stderr'}},
    'loggers':{
        'uvicorn':{'handlers':['safe'],'level':'INFO','propagate':False},
        'uvicorn.error':{'handlers':['safe'],'level':'INFO','propagate':False},
        'uvicorn.access':{'handlers':[],'level':'CRITICAL','propagate':False},
        'alembic':{'handlers':['safe'],'level':'WARNING','propagate':False},
        'sqlalchemy':{'handlers':['safe'],'level':'WARNING','propagate':False},
    },
}


def main():
    uvicorn.run('app:app', host='127.0.0.1', port=8765, workers=1,
                access_log=False, log_config=LOG_CONFIG)


if __name__ == '__main__':
    main()
