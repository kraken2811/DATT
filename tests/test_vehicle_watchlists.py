import json
from uuid import uuid4, UUID
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from src.db.database import Database
from src.db.models import PlateEvent, VehicleEvent, VehicleWatchlistResult, utc_now
from src.watchlists.vehicle_api import router
from src.watchlists.vehicles import normalize_plate, record_plate_result
from src.watchlists.import_vehicles import import_file


@pytest.fixture
def env(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'vehicles.db').as_posix()
    monkeypatch.setenv('DATT_DATABASE_URL',url)
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE','0')
    monkeypatch.delenv('DATT_EMAIL_PASSWORD',raising=False)
    command.upgrade(Config('src/db/alembic.ini'),'head')
    db=Database(url); app=FastAPI(); app.include_router(router)
    with TestClient(app) as client: yield client,db,tmp_path,url
    db.dispose()


def create(env,plate='29a-123.45',**kwargs):
    return env[0].post('/api/watchlist/vehicles',json=dict(plate_number=plate,name='Test vehicle',**kwargs))


def plate(env,value):
    with env[1].transaction() as s:
        vehicle=VehicleEvent(vehicle_class='car',track_id=1); s.add(vehicle); s.flush()
        event=PlateEvent(vehicle_event_id=vehicle.id,plate_text=value,created_at=utc_now()); s.add(event); s.flush()
        result=record_plate_result(s,event,'gate-test')
        assert record_plate_result(s,event,'gate-test').id==result.id
        return event.id,result.id


def test_crud_contract(env):
    c=env[0]; response=create(env); assert response.status_code==201
    item=response.json()['vehicle']; ident=item['id']
    assert item['plate_number']==item['normalized_plate']=='29A12345'
    assert item['name']==item['display_name']=='Test vehicle'
    assert c.get('/watchlist/vehicles').json()['total']==1
    assert c.get('/api/watchlist/vehicles',params={'search':'29A-123'}).json()['total']==1
    assert c.get('/api/watchlist/vehicles',params={'status':'disabled'}).json()['total']==0
    assert c.patch('/api/watchlist/vehicles/'+ident,json={'name':'Edited','status':'disabled'}).json()['vehicle']['name']=='Edited'
    assert c.get('/api/watchlist/vehicles/'+ident).json()['vehicle']['status']=='disabled'
    assert c.delete('/api/watchlist/vehicles/'+ident).status_code==200
    assert c.get('/api/watchlist/vehicles/'+ident).status_code==404
    assert c.delete('/api/watchlist/vehicles/nope').status_code==404


def test_duplicates_and_update(env):
    create(env)
    response=create(env,'29 A 12345'); assert response.status_code==400
    assert response.json()['code']=='DUPLICATE_PLATE'
    second=create(env,'51F99999').json()['vehicle']
    assert env[0].patch('/api/watchlist/vehicles/'+second['id'],json={'plate_number':'29A12345'}).status_code==400


@pytest.mark.parametrize('value,expected',[(' 29a-123.45 ','29A12345'),('51F 999-99','51F99999'),('', ''),('abc_123','ABC123')])
def test_normalization(value,expected):
    assert normalize_plate(value)==expected


@pytest.mark.parametrize('body',[{'plate_number':'!'},{'plate_number':'abc','status':'bad'}, {'plate_number':'abc','vehicle_type':'bad'},[],{'plate_number':None}])
def test_invalid_fields(env,body):
    assert env[0].post('/api/watchlist/vehicles',json=body).status_code==400


def test_match_nonmatch_disabled_history_and_delete(env):
    c,db,_,_=env
    ident=create(env).json()['vehicle']['id']
    eid,rid=plate(env,'29a 123.45')
    plate(env,'X29A12345')
    with db.transaction() as s:
        assert s.get(VehicleWatchlistResult,rid).decision=='MATCH'
        assert list(s.scalars(select(VehicleWatchlistResult.decision)))==['MATCH','NO_MATCH']
    c.patch('/api/watchlist/vehicles/'+ident,json={'status':'disabled'})
    _,disabled=plate(env,'29A12345')
    with db.transaction() as s: assert s.get(VehicleWatchlistResult,disabled).decision=='NO_MATCH'
    history=c.get('/api/watchlist/vehicles/'+ident+'/detections').json()
    assert history['total_detections']==2 and len(history['detections'])==2
    assert all(i['camera_id']=='gate-test' for i in history['detections'])
    assert c.get('/api/watchlist/vehicles/'+ident).json()['vehicle']['detection_count']==2
    c.delete('/api/watchlist/vehicles/'+ident)
    with db.transaction() as s:
        assert s.get(PlateEvent,eid) is not None
        result=s.get(VehicleWatchlistResult,rid)
        assert result.watchlist_id is None and result.decision=='MATCH' and result.display_name=='Test vehicle'


def test_persistence_new_database_and_app(env):
    item=create(env).json()['vehicle']; plate(env,item['plate_number'])
    env[1].dispose()
    app=FastAPI(); app.include_router(router)
    with TestClient(app) as fresh:
        assert fresh.get('/api/watchlist/vehicles/'+item['id']).json()['vehicle']['detection_count']==1
        assert fresh.get('/api/watchlist/vehicles/'+item['id']+'/detections').json()['detections'][0]['watchlist_decision']=='MATCH'


def test_json_import_idempotent_no_deletion_and_conflict_rollback(env):
    _,db,tmp,_=env; path=tmp/'legacy.json'
    records=[dict(id=str(uuid4()),plate_number='30a-11111',name='Legacy')]
    path.write_text(json.dumps(records))
    assert import_file(db,path)==1 and import_file(db,path)==0 and path.exists()
    records.insert(0,dict(id=str(uuid4()),plate_number='30a-22222'))
    records[1]['name']='conflict'; path.write_text(json.dumps(records))
    with pytest.raises(ValueError): import_file(db,path)
    assert env[0].get('/api/watchlist/vehicles').json()['total']==1


def test_db_worker_plate_event_integration(env):
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import VehiclePassageDTO
    create(env); now=utc_now()
    dto=VehiclePassageDTO(id=uuid4(),session_key='vehicle-test',camera_id='gate-test',track_id=7,
        first_seen_at=now,last_seen_at=now,plate_text='29a-123.45',vehicle_type='car',is_final=True,
        created_at=now,updated_at=now,finalized_at=now)
    worker=DatabaseWorker(env[3],snapshot_dir=env[2]/'evidence')
    try:
        assert worker._persist_batch([('PASSAGE',dto,None)])
        with env[1].transaction() as s:
            results=list(s.scalars(select(VehicleWatchlistResult)))
            assert len(results)==1 and results[0].decision=='MATCH'
            assert s.get(PlateEvent,results[0].plate_event_id).plate_text=='29a-123.45'
    finally: worker.stop()


def test_migration_backfills_existing_plate_history(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'old.db').as_posix(); monkeypatch.setenv('DATT_DATABASE_URL',url)
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE','0'); cfg=Config('src/db/alembic.ini'); command.upgrade(cfg,'0008')
    db=Database(url)
    with db.engine.begin() as conn:
        vid,eid=uuid4().hex,uuid4().hex
        conn.execute(text("INSERT INTO vehicle_events (id,vehicle_class,track_id,first_seen,last_seen) VALUES (:id,'car',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),{'id':vid})
        conn.execute(text("INSERT INTO plate_events (id,vehicle_event_id,plate_text,status,created_at) VALUES (:id,:vid,'29a-123.45','confirmed',CURRENT_TIMESTAMP)"),{'id':eid,'vid':vid})
    command.upgrade(cfg,'head')
    with db.engine.connect() as conn: assert conn.scalar(text('SELECT normalized_plate FROM plate_events'))=='29A12345'
    db.dispose()
