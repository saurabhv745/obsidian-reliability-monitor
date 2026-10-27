"""SQLAlchemy persistence with SQLite local fallback and PostgreSQL support."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

LOCAL_DB = Path(__file__).with_name('reliability_monitor.db')
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{LOCAL_DB.as_posix()}')
ENGINE = create_engine(DATABASE_URL, connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {})


def connection(): return ENGINE.connect()


def init_storage() -> None:
    with ENGINE.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS models (id TEXT PRIMARY KEY, payload TEXT NOT NULL)'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, model_id TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_snapshots_model_time ON snapshots(model_id, timestamp)'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS app_records (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (kind, id))'))


def has_models() -> bool:
    with ENGINE.connect() as conn: return conn.execute(text('SELECT 1 FROM models LIMIT 1')).first() is not None


def healthcheck() -> bool:
    with ENGINE.connect() as conn:
        conn.execute(text('SELECT 1'))
    return True


def _upsert(table: str, key: str, payload: dict[str, Any]) -> None:
    with ENGINE.begin() as conn:
        if DATABASE_URL.startswith('sqlite'):
            if table == 'models': sql = 'INSERT OR REPLACE INTO models(id, payload) VALUES (:id, :payload)'; params = {'id': key, 'payload': json.dumps(payload)}
            elif table == 'alerts': sql = 'INSERT OR REPLACE INTO alerts(id, payload) VALUES (:id, :payload)'; params = {'id': key, 'payload': json.dumps(payload)}
            else: sql = 'INSERT OR REPLACE INTO snapshots(id, model_id, timestamp, payload) VALUES (:id, :model_id, :timestamp, :payload)'; params = {**payload, 'payload': json.dumps(payload)}
        elif table == 'models': sql = 'INSERT INTO models(id, payload) VALUES (:id, :payload) ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload'; params = {'id': key, 'payload': json.dumps(payload)}
        elif table == 'alerts': sql = 'INSERT INTO alerts(id, payload) VALUES (:id, :payload) ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload'; params = {'id': key, 'payload': json.dumps(payload)}
        else: sql = 'INSERT INTO snapshots(id, model_id, timestamp, payload) VALUES (:id, :model_id, :timestamp, :payload) ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload'; params = {**payload, 'payload': json.dumps(payload)}
        conn.execute(text(sql), params)


def save_model(model: dict[str, Any]) -> None: _upsert('models', model['id'], model)
def save_snapshot(snapshot: dict[str, Any]) -> None: _upsert('snapshots', snapshot['id'], snapshot)
def save_alert(alert: dict[str, Any]) -> None: _upsert('alerts', alert['id'], alert)

def save_record(kind: str, record: dict[str, Any]) -> None:
    with ENGINE.begin() as conn:
        if DATABASE_URL.startswith('sqlite'):
            sql = 'INSERT OR REPLACE INTO app_records(kind, id, payload) VALUES (:kind, :id, :payload)'
        else:
            sql = 'INSERT INTO app_records(kind, id, payload) VALUES (:kind, :id, :payload) ON CONFLICT (kind, id) DO UPDATE SET payload = EXCLUDED.payload'
        conn.execute(text(sql), {'kind': kind, 'id': str(record['id']), 'payload': json.dumps(record)})

def load_records(kind: str) -> list[dict[str, Any]]:
    with ENGINE.connect() as conn:
        return [json.loads(row[0]) for row in conn.execute(text('SELECT payload FROM app_records WHERE kind = :kind ORDER BY id'), {'kind': kind})]


def load_state() -> dict[str, list[dict[str, Any]]]:
    with ENGINE.connect() as conn:
        models = [json.loads(row[0]) for row in conn.execute(text('SELECT payload FROM models'))]
        snapshots = [json.loads(row[0]) for row in conn.execute(text('SELECT payload FROM snapshots ORDER BY timestamp'))]
        alerts = [json.loads(row[0]) for row in conn.execute(text('SELECT payload FROM alerts'))]
    return {'models': models, 'snapshots': snapshots, 'alerts': alerts}
