"""Camera FE compatibility aliases; all state comes from cameras/video_sources."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from .service import list_records,mutate
from .probe import probe

router=APIRouter()

def execute(action,ident=None,body=None,filters=None):
    try:
        result=list_records(filters) if action=='list' else mutate(action,ident,body)
        return JSONResponse(result,status_code=201 if action=='create' else 200)
    except LookupError: return JSONResponse({'status':'error','detail':'CAMERA_NOT_FOUND'},status_code=404)
    except ValueError as exc: return JSONResponse({'status':'error','detail':str(exc)},status_code=400)
    except RuntimeError: return JSONResponse({'status':'error','detail':'CAMERA_ACTIVE_STOP_FIRST'},status_code=409)
    except IntegrityError: return JSONResponse({'status':'error','detail':'CAMERA_REFERENCED_OR_CONFLICT'},status_code=409)
    except SQLAlchemyError: return JSONResponse({'status':'error','detail':'DATABASE_UNAVAILABLE'},status_code=503)

async def body(request):
    try:
        value=await request.json()
        return value if isinstance(value,dict) else {}
    except Exception: return {}


def listing(request:Request): return execute('list',filters=dict(request.query_params))
async def create(request:Request): return await run_in_threadpool(execute,'create',body=await body(request))
def detail(camera_id:str): return execute('get',camera_id)
async def edit(camera_id:str,request:Request): return await run_in_threadpool(execute,'update',camera_id,await body(request))
def remove(camera_id:str): return execute('delete',camera_id)
def enable(camera_id:str): return execute('enable',camera_id)
def disable(camera_id:str): return execute('disable',camera_id)
def test(camera_id:str):
    try:
        camera=mutate('get',camera_id)['camera']
        return probe(camera['source_type'],camera['source_url'])
    except LookupError: return JSONResponse({'status':'error','detail':'CAMERA_NOT_FOUND'},status_code=404)
    except SQLAlchemyError: return JSONResponse({'status':'error','detail':'DATABASE_UNAVAILABLE'},status_code=503)
async def test_input(request:Request):
    data=await body(request)
    return await run_in_threadpool(probe,data.get('source_type',''),data.get('source_url',data.get('url','')))

for prefix in ('/api/cameras','/api/camera_management/cameras','/api/manage/cameras'):
    for suffix,method,handler in (('', 'GET',listing),('', 'POST',create),('/{camera_id}','GET',detail),
        ('/{camera_id}','PATCH',edit),('/{camera_id}','PUT',edit),('/{camera_id}','DELETE',remove),
        ('/{camera_id}/enable','POST',enable),('/{camera_id}/disable','POST',disable),('/{camera_id}/test','POST',test)):
        router.add_api_route(prefix+suffix,handler,methods=[method])
router.add_api_route('/api/camera_management/test_connection',test_input,methods=['POST'])


@router.get('/api/cameras/{camera_id}/thumbnail')
def thumbnail(camera_id:str):
    from .thumbnails import thumbnail_bytes
    try:
        camera=mutate('get',camera_id)['camera']
        data,kind=thumbnail_bytes(camera)
        return Response(data,media_type=kind,headers={'Cache-Control':'private, max-age=90','X-Content-Type-Options':'nosniff'})
    except LookupError:return JSONResponse({'detail':'CAMERA_NOT_FOUND'},status_code=404)
    except Exception:return JSONResponse({'detail':'THUMBNAIL_UNAVAILABLE'},status_code=503)
