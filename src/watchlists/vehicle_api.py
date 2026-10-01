"""UI-compatible vehicle watchlist routes backed by the deployment database."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from src.db.database import Database
from .vehicles import operate

router = APIRouter()


def execute(action, **kwargs):
    db = None
    try:
        db = Database()
        return JSONResponse(operate(db,action,**kwargs),status_code=201 if action=='create' else 200)
    except LookupError:
        return JSONResponse(dict(status='error',message='Vehicle not found'),status_code=404)
    except ValueError as exc:
        return JSONResponse(dict(status='error',code=str(exc),message='Invalid vehicle fields'),status_code=400)
    except IntegrityError:
        return JSONResponse(dict(status='error',code='DUPLICATE_PLATE',message='Plate already registered'),status_code=400)
    except (SQLAlchemyError, RuntimeError):
        return JSONResponse(dict(status='error',code='DATABASE_UNAVAILABLE',message='Watchlist database unavailable; check migration'),status_code=503)
    finally:
        if db: db.dispose()


async def body(request):
    try:
        return await request.json() if 'application/json' in request.headers.get('content-type','') else dict(await request.form())
    except Exception:
        return None


@router.get('/api/watchlist/vehicles')
@router.get('/watchlist/vehicles')
def list_vehicles(request: Request):
    return execute('list',filters=dict(request.query_params))


@router.post('/api/watchlist/vehicles')
@router.post('/watchlist/vehicles')
async def create_vehicle(request: Request):
    return await run_in_threadpool(execute,'create',body=await body(request))


@router.get('/api/watchlist/vehicles/{vehicle_id}')
@router.get('/watchlist/vehicles/{vehicle_id}')
def get_vehicle(vehicle_id: str):
    return execute('get',ident=vehicle_id)


@router.patch('/api/watchlist/vehicles/{vehicle_id}')
@router.patch('/watchlist/vehicles/{vehicle_id}')
async def update_vehicle(vehicle_id: str, request: Request):
    return await run_in_threadpool(execute,'update',ident=vehicle_id,body=await body(request))


@router.delete('/api/watchlist/vehicles/{vehicle_id}')
@router.delete('/watchlist/vehicles/{vehicle_id}')
def delete_vehicle(vehicle_id: str):
    return execute('delete',ident=vehicle_id)


@router.get('/api/watchlist/vehicles/{vehicle_id}/detections')
@router.get('/watchlist/vehicles/{vehicle_id}/detections')
def vehicle_detections(vehicle_id: str):
    return execute('detections',ident=vehicle_id)
