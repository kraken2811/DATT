from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse,Response
from sqlalchemy.exc import SQLAlchemyError
from src.cameras.service import database
from src.storage import get_storage,validate_key
from .service import query

router=APIRouter()


def execute(params,ident=None,evidence=False):
    try:
        with database() as db,db.transaction() as s: result=query(s,params,ident)
        if evidence:
            ref=result.get('evidence')
            if not ref: raise LookupError()
            key=validate_key(ref['key'])
            with get_storage().open(key) as stream: content=stream.read(10*1024*1024+1)
            if len(content)>10*1024*1024: return JSONResponse({'detail':'EVIDENCE_TOO_LARGE'},status_code=413)
            # Only known image formats; never render arbitrary stored HTML/SVG.
            import io
            from PIL import Image
            image=Image.open(io.BytesIO(content));image.verify()
            kind={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}.get(image.format)
            if not kind: raise ValueError('UNSUPPORTED_EVIDENCE')
            return Response(content,media_type=kind,headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store'})
        return dict(status='ok',event=result) if ident else result
    except LookupError: return JSONResponse({'detail':'EVENT_OR_EVIDENCE_NOT_FOUND'},status_code=404)
    except (FileNotFoundError,OSError): return JSONResponse({'detail':'EVIDENCE_UNAVAILABLE'},status_code=404)
    except ValueError as exc: return JSONResponse({'detail':str(exc) if not evidence else 'INVALID_EVIDENCE'},status_code=400)
    except SQLAlchemyError: return JSONResponse({'detail':'DATABASE_UNAVAILABLE'},status_code=503)
    except Exception: return JSONResponse({'detail':'EVIDENCE_UNAVAILABLE' if evidence else 'EVENT_CENTER_UNAVAILABLE'},status_code=503)


@router.get('/api/event_center/events')
def events(request:Request): return execute(dict(request.query_params))
@router.get('/api/event_center/events/{event_id}')
def event(event_id:str): return execute({},event_id)
@router.get('/api/event_center/events/{event_id}/evidence')
def evidence(event_id:str): return execute({},event_id,True)
