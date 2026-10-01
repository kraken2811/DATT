"""Explicit idempotent import of existing Camera Management JSON; no runtime JSON registry."""
import argparse,json
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID,uuid5,NAMESPACE_URL
from pathlib import Path
from src.db.models import Camera
from .service import database,camera_fields,find


def import_file(path,legacy_timezone='UTC'):
    rows=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(rows,list): raise ValueError('INVALID_CAMERA_IMPORT')
    inserted=0
    with database() as db,db.transaction() as s:
        for row in rows:
            key=str(row['id']);values=camera_fields(row)
            current=find(s,key,True)
            if current:
                if any(getattr(current,k)!=v for k,v in values.items()): raise ValueError('IMPORT_CONFLICT')
                continue
            try: ident=UUID(key)
            except ValueError:ident=uuid5(NAMESPACE_URL,'datt-camera:'+key)
            dates={}
            for field in ('created_at','updated_at'):
                if row.get(field):
                    value=datetime.fromisoformat(row[field])
                    dates[field]=value if value.tzinfo else value.replace(tzinfo=ZoneInfo(legacy_timezone))
            s.add(Camera(id=ident,registry_key=key,**values,**dates));s.flush();inserted+=1
    return inserted


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('path');parser.add_argument('--legacy-timezone',default='UTC')
    args=parser.parse_args()
    print('imported='+str(import_file(args.path,args.legacy_timezone)))
