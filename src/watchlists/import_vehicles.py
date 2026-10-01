"""One-time, transactional JSON import. Never reads JSON during API requests."""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from src.db.database import Database
from src.db.models import VehicleWatchlist
from .vehicles import fields


def import_file(db, path, legacy_timezone='UTC'):
    records = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(records,list): raise ValueError('Expected a JSON list')
    count=0
    with db.transaction() as session:
        for record in records:
            values=fields(record)
            ident=UUID(record['id'])
            existing=session.scalar(select(VehicleWatchlist).where(VehicleWatchlist.plate_number==values['plate_number']))
            by_id=session.get(VehicleWatchlist,ident)
            if existing or by_id:
                if not existing or existing.id!=ident or any(getattr(existing,k)!=v for k,v in values.items()):
                    raise ValueError('Import conflict; no rows imported; original JSON retained')
                continue
            dates={}
            for name in ('created_at','updated_at'):
                if record.get(name):
                    value=datetime.fromisoformat(record[name])
                    # Legacy Colab timestamps are UTC; override for imports from other hosts.
                    if value.tzinfo is None: value=value.replace(tzinfo=ZoneInfo(legacy_timezone))
                    dates[name]=value
            session.add(VehicleWatchlist(id=ident,**values,**dates)); session.flush(); count+=1
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--legacy-timezone', default='UTC')
    args=parser.parse_args()
    db=Database()
    try: print('imported='+str(import_file(db,args.path,args.legacy_timezone)))
    finally: db.dispose()


if __name__=='__main__': main()
