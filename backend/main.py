from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Header, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime, timedelta
import uuid
import math
import os
from typing import Any
try:
    from notifications import dispatch, status as notification_status, send_sms, send_telegram
except ImportError:
    from backend.notifications import dispatch, status as notification_status, send_sms, send_telegram

try:
    from storage import init_storage, has_models, healthcheck as storage_healthcheck, save_model, save_snapshot, save_alert, save_record, load_records, load_state
except ImportError:
    from backend.storage import init_storage, has_models, healthcheck as storage_healthcheck, save_model, save_snapshot, save_alert, save_record, load_records, load_state

app = FastAPI(title="Obsidian Labs Reliability API")
_cors_value = os.getenv('CORS_ORIGINS', '').strip() or 'http://localhost:5173,http://localhost:5174,https://obsidian-reliability-ui.onrender.com'
_cors_origins = [origin.strip() for origin in _cors_value.split(',') if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=['GET', 'POST', 'PUT', 'OPTIONS'], allow_headers=['*'])
app.add_middleware(GZipMiddleware, minimum_size=1000)
uploads = {}
alert_store = []
thresholds = {'low': 0.20, 'moderate': 0.50, 'high': 0.75}
monitoring_frequency = 'Every 6 hours'
model_registry = {
    'churn-v24': {'id': 'churn-v24', 'name': 'Customer Churn Model', 'description': 'Gradient boosting classifier for retention prioritisation.', 'status': 'REVIEW', 'version': 'v2.4', 'task_type': 'classification', 'accuracy': 94.2},
    'fraud-v18': {'id': 'fraud-v18', 'name': 'Fraud Detection Model', 'description': 'Fraud risk scoring for card transactions.', 'status': 'HEALTHY', 'version': 'v1.8', 'task_type': 'classification', 'accuracy': 97.1},
    'recommend-v31': {'id': 'recommend-v31', 'name': 'Recommendation Model', 'description': 'Personalised next-best-action ranking model.', 'status': 'WARNING', 'version': 'v3.1', 'task_type': 'regression', 'accuracy': 89.6},
}
snapshot_store = {}
feature_store = {}
version_store = {key: [{'version': value['version'], 'accuracy': value['accuracy'], 'f1': round(value['accuracy'] - 2.3, 1), 'trained_at': '2026-10-20', 'is_active': True}] for key, value in model_registry.items()}
healing_events = []
healing_state = {}
badge_store = {}
chat_store = {}
forecast_cache = {}
investigation_store = []
incident_store = []
API_KEY = os.getenv('API_KEY', '').strip()

def require_write_key(x_api_key: str | None = Header(default=None)):
    """Protect mutating endpoints when API_KEY is configured; stay open in offline demo mode."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, 'A valid X-API-Key header is required for this action.')

def _seed_history():
    """Create deterministic, offline demo monitoring history for the dashboard."""
    if snapshot_store:
        return
    for model_id, model in model_registry.items():
        rows = []
        for day in range(30):
            drift = max(0.02, min(0.72, 0.04 + max(0, day - 19) * (0.018 if model_id == 'churn-v24' else 0.012)))
            reliability = round(max(42, 96 - drift * 42 - max(0, day - 24) * 1.8), 1)
            rows.append({'id': str(uuid.uuid4()), 'model_id': model_id, 'timestamp': (datetime.now() - timedelta(days=29-day)).isoformat(), 'reliability_score': reliability, 'performance_score': round(max(72, 96 - max(0, day - 23) * 1.5), 1), 'drift_score': round(drift, 3), 'confidence_score': round(max(70, 96 - drift * 20), 1), 'quality_score': round(max(75, 94 - drift * 15), 1), 'accuracy': round(max(78, model['accuracy'] - drift * 8), 1), 'f1': round(max(72, model['accuracy'] - drift * 10), 1), 'avg_confidence': round(max(.68, .94 - drift * .25), 3), 'verdict': 'healthy' if reliability >= 80 else 'watch' if reliability >= 50 else 'retrain', 'window_size': 2400})
        snapshot_store[model_id] = rows
        feature_store[model_id] = [{'feature': name, 'psi': psi, 'ks_stat': round(psi * .8, 3), 'ks_pvalue': round(max(.001, 1 - psi), 3), 'js_divergence': round(psi * .6, 3), 'drift_level': 'critical' if psi > .25 else 'warn' if psi >= .1 else 'none'} for name, psi in [('income', .183), ('support_calls', .094), ('contract_type', .071), ('tenure', .036), ('region', .112)]]

init_storage()
investigation_store.extend(load_records('investigation'))
incident_store.extend(load_records('incident'))
_saved_settings = load_records('settings')
if _saved_settings:
    thresholds.update(_saved_settings[0].get('thresholds', {}))
    monitoring_frequency = _saved_settings[0].get('monitoring_frequency', monitoring_frequency)
if has_models():
    _stored = load_state()
    model_registry.clear()
    model_registry.update({_model['id']: _model for _model in _stored['models']})
    snapshot_store.clear()
    for _snapshot in _stored['snapshots']:
        snapshot_store.setdefault(_snapshot['model_id'], []).append(_snapshot)
    for _model_id in model_registry:
        if _model_id not in feature_store:
            feature_store[_model_id] = [{'feature': name, 'psi': psi, 'ks_stat': round(psi * .8, 3), 'ks_pvalue': round(max(.001, 1 - psi), 3), 'js_divergence': round(psi * .6, 3), 'drift_level': 'critical' if psi > .25 else 'warn' if psi >= .1 else 'none'} for name, psi in [('income', .183), ('support_calls', .094), ('contract_type', .071), ('tenure', .036), ('region', .112)]]
    alert_store.extend(_stored['alerts'])
else:
    _seed_history()
    for _model in model_registry.values():
        save_model(_model)
    for _rows in snapshot_store.values():
        for _snapshot in _rows:
            save_snapshot(_snapshot)

def read_csv(upload: UploadFile):
    filename = (upload.filename or '').lower()
    if not filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(400, 'Unsupported file type. Please upload CSV or Excel (.xlsx/.xls).')
    data = upload.file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, 'File is too large. Maximum size is 20 MB.')
    try:
        df = pd.read_csv(BytesIO(data)) if filename.endswith('.csv') else pd.read_excel(BytesIO(data))
    except Exception:
        raise HTTPException(400, 'Unable to read dataset. Check the file format and headers.')
    if df.empty or len(df.columns) == 0: raise HTTPException(400, 'Dataset is empty.')
    return df

def profile(df):
    numeric = df.select_dtypes(include=np.number).columns.tolist()
    categorical = [c for c in df.columns if c not in numeric]
    return {'rows': int(len(df)), 'columns': int(len(df.columns)), 'missing': int(df.isna().sum().sum()), 'numeric': numeric, 'categorical': categorical, 'duplicate_rows': int(df.duplicated().sum()), 'schema': list(df.columns)}

def js_divergence(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = a / max(a.sum(), 1), b / max(b.sum(), 1)
    m = (a + b) / 2
    def kl(x, y):
        positive = x > 0
        return np.sum(x[positive] * np.log2(x[positive] / np.maximum(y[positive], 1e-12)))
    return float(np.clip((kl(a, m) + kl(b, m)) / 2, 0, 1))

def compare_feature(base, current, col):
    b, c = base[col], current[col]
    miss_change = abs(float(b.isna().mean()) - float(c.isna().mean()))
    if pd.api.types.is_numeric_dtype(b):
        bn, cn = pd.to_numeric(b, errors='coerce').dropna(), pd.to_numeric(c, errors='coerce').dropna()
        if len(bn) == 0 or len(cn) == 0: score = miss_change
        else:
            lo, hi = min(bn.min(), cn.min()), max(bn.max(), cn.max())
            if lo == hi: score = miss_change
            else:
                hist_b, edges = np.histogram(bn, bins=10, range=(lo, hi)); hist_c, _ = np.histogram(cn, bins=edges)
                score = min(1, js_divergence(hist_b, hist_c) * 1.7 + miss_change)
        bv, cv = float(bn.mean()) if len(bn) else 0, float(cn.mean()) if len(cn) else 0
        change = ((cv - bv) / abs(bv) * 100) if bv else 0
        detail = {'baseline': round(bv, 2), 'current': round(cv, 2), 'change': round(change, 1)}
    else:
        bc, cc = b.fillna('__missing__').astype(str), c.fillna('__missing__').astype(str)
        cats = sorted(set(bc.unique()) | set(cc.unique()))
        score = min(1, js_divergence(bc.value_counts().reindex(cats, fill_value=0), cc.value_counts().reindex(cats, fill_value=0)) * 1.8 + miss_change)
        detail = {'baseline': int(bc.nunique()), 'current': int(cc.nunique()), 'change': 'New categories' if len(set(cc)-set(bc)) else 'Category mix shifted'}
    status = 'Critical' if score >= thresholds['high'] else 'High' if score >= thresholds['moderate'] else 'Warning' if score >= thresholds['low'] else 'Stable'
    return {'feature': col, 'score': round(float(score), 2), 'status': status, 'change': detail['change'], 'recommendation': 'Review immediately' if score >= .5 else 'Investigate' if score >= .2 else 'Continue monitoring', 'detail': detail, 'missing_baseline': round(float(b.isna().mean()*100), 1), 'missing_current': round(float(c.isna().mean()*100), 1)}

@app.get('/api/health')
def health(): return {'status': 'ok', 'service': 'drift-engine'}

@app.get('/api/health/live')
def liveness(): return {'status': 'alive', 'service': 'drift-engine'}

@app.get('/api/health/ready')
def readiness():
    try:
        storage_healthcheck()
        return {'status': 'ready', 'database': 'reachable', 'models': len(model_registry)}
    except Exception as error:
        raise HTTPException(503, f'Database is not ready: {error}')

@app.get('/api/notifications/status')
def notifications_status(): return notification_status()

@app.post('/api/notifications/test')
def notifications_test(payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    channel, message = str(payload.get('channel', '')).lower(), str(payload.get('message', 'Obsidian Labs notification test')).strip()
    if channel == 'telegram': return send_telegram(message)
    if channel in {'sms', 'twilio'}: return send_sms(message)
    raise HTTPException(400, 'Channel must be telegram or sms.')

@app.post('/api/datasets/upload')
async def upload_dataset(file: UploadFile = File(...), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    df = read_csv(file); key = str(uuid.uuid4()); uploads[key] = df
    return {'id': key, 'name': file.filename, 'profile': profile(df), 'preview': df.head(8).fillna('').to_dict(orient='records')}

@app.post('/api/drift/analyze')
async def analyze(baseline_id: str, current_id: str):
    if baseline_id not in uploads or current_id not in uploads: raise HTTPException(404, 'Dataset not found. Upload both datasets again.')
    base, cur = uploads[baseline_id], uploads[current_id]
    if set(base.columns) != set(cur.columns): raise HTTPException(400, 'Baseline and current datasets must contain compatible columns.')
    features = [compare_feature(base, cur, c) for c in base.columns]
    score = round(float(np.mean([f['score'] for f in features])), 2)
    status = 'CRITICAL' if score >= thresholds['high'] else 'HIGH' if score >= thresholds['moderate'] else 'REVIEW' if score >= thresholds['low'] else 'HEALTHY'
    alert_store.clear()
    if score >= thresholds['low']:
        worst = max(features, key=lambda item: item['score'])
        alert_store.append({'id': str(uuid.uuid4()), 'type': 'WARNING' if score < thresholds['high'] else 'HIGH', 'title': 'Potential drift detected', 'text': f"{worst['feature']} distribution has changed significantly.", 'recommendation': 'Investigate recent input changes and validate with outcomes.', 'time': 'Just now', 'open': True})
    alert_store.append({'id': str(uuid.uuid4()), 'type': 'INFO', 'title': 'Monitoring step completed', 'text': 'Dataset comparison completed successfully.', 'recommendation': 'Continue monitoring.', 'time': 'Just now', 'open': True})
    for _alert in alert_store:
        save_alert(_alert)
    for _alert in alert_store:
        if _alert['type'] in {'WARNING', 'HIGH'}: dispatch(_alert)
    return {'drift_score': score, 'status': status, 'features': features, 'baseline': profile(base), 'current': profile(cur), 'alerts': alert_store, 'created_at': datetime.now().isoformat()}

@app.get('/api/model/health')
def model_health(): return {'score': 86, 'data_stability': 88, 'drift_risk': 18, 'performance': 94, 'input_quality': 91, 'status': 'REVIEW'}

@app.get('/api/alerts')
def alerts(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    items = alert_store[offset:offset + limit]
    return {'alerts': items, 'total': len(alert_store), 'limit': limit, 'offset': offset}

@app.post('/api/alerts/{alert_id}/acknowledge')
def acknowledge(alert_id: str):
    for alert in alert_store:
        if alert['id'] == alert_id:
            alert['open'] = False
            save_alert(alert)
            return alert
    raise HTTPException(404, 'Alert not found.')

@app.get('/api/model/performance')
def performance():
    return {'available': False, 'message': 'Performance validation unavailable — labeled outcomes are required.', 'metrics': {}}

@app.post('/api/model/performance/validate')
async def validate_performance(file: UploadFile = File(...)):
    df = read_csv(file)
    columns = {str(c).strip().lower(): c for c in df.columns}
    actual_col = next((columns[k] for k in ('actual', 'y_true', 'label', 'ground_truth') if k in columns), None)
    predicted_col = next((columns[k] for k in ('predicted', 'prediction', 'y_pred') if k in columns), None)
    score_col = next((columns[k] for k in ('probability', 'score', 'positive_probability', 'y_score') if k in columns), None)
    if not actual_col or not predicted_col:
        raise HTTPException(400, 'Dataset must include actual/label and predicted/prediction columns.')
    rows = df[[actual_col, predicted_col] + ([score_col] if score_col else [])].dropna()
    if rows.empty: raise HTTPException(400, 'No complete labeled rows were found.')
    actual = rows[actual_col].astype(str).str.strip()
    predicted = rows[predicted_col].astype(str).str.strip()
    accuracy = float((actual == predicted).mean())
    labels = sorted(set(actual) | set(predicted))
    positive = labels[-1]
    tp = int(((actual == positive) & (predicted == positive)).sum())
    fp = int(((actual != positive) & (predicted == positive)).sum())
    fn = int(((actual == positive) & (predicted != positive)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    auc = None
    if score_col and len(set(actual)) == 2:
        y = (actual == positive).astype(int).to_numpy()
        scores = pd.to_numeric(rows[score_col], errors='coerce').to_numpy()
        valid = ~np.isnan(scores)
        y, scores = y[valid], scores[valid]
        pos, neg = scores[y == 1], scores[y == 0]
        if len(pos) and len(neg): auc = float(np.mean(pos[:, None] > neg[None, :]) + .5 * np.mean(pos[:, None] == neg[None, :]))
    metrics = {'accuracy': round(accuracy, 4), 'precision': round(precision, 4), 'recall': round(recall, 4), 'f1': round(f1, 4), 'roc_auc': round(auc, 4) if auc is not None else None}
    return {'rows': int(len(rows)), 'actual_column': str(actual_col), 'predicted_column': str(predicted_col), 'metrics': metrics, 'labels': labels}

@app.get('/api/models')
def models(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    items = [dict(model, last_checked='2 minutes ago') for model in model_registry.values()]
    return {'models': items[offset:offset + limit], 'total': len(items), 'limit': limit, 'offset': offset}

@app.post('/api/models')
def create_model(payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    name = str(payload.get('name', '')).strip()
    if not name: raise HTTPException(400, 'Model name is required.')
    if any(model['name'].lower() == name.lower() for model in model_registry.values()):
        raise HTTPException(409, 'A model with this name already exists.')
    base = ''.join(ch.lower() if ch.isalnum() else '-' for ch in name).strip('-') or 'model'
    model_id = base[:32]
    while model_id in model_registry: model_id = f'{base[:24]}-{uuid.uuid4().hex[:7]}'
    model = {'id': model_id, 'name': name, 'description': str(payload.get('description', 'Registered monitoring model.')), 'status': 'REVIEW', 'version': str(payload.get('version', 'v1.0')), 'task_type': str(payload.get('task_type', 'classification')), 'accuracy': float(payload.get('accuracy', 0))}
    model_registry[model_id] = model
    snapshot_store[model_id] = []
    feature_store[model_id] = []
    version_store[model_id] = [{'version': model['version'], 'accuracy': model['accuracy'], 'f1': 0, 'trained_at': datetime.now().isoformat(), 'is_active': True}]
    save_model(model)
    return model

@app.get('/api/models/{model_id}')
def model_detail(model_id: str):
    return {'id': model_id, 'health': model_health(), 'history': history()['events']}

@app.get('/api/history')
def history():
    return {'events': [
        {'date': 'Oct 25', 'label': 'Drift detected', 'type': 'warning'},
        {'date': 'Oct 24', 'label': 'Healthy', 'type': 'healthy'},
        {'date': 'Oct 23', 'label': 'Healthy', 'type': 'healthy'},
        {'date': 'Oct 22', 'label': 'Moderate drift', 'type': 'warning'},
        {'date': 'Oct 20', 'label': 'Model updated', 'type': 'info'}
    ]}

@app.post('/api/reports/generate')
def generate_report():
    return {'id': str(uuid.uuid4()), 'status': 'ready', 'format': 'json', 'created_at': datetime.now().isoformat(), 'model': 'Customer Churn Model', 'drift_score': .18, 'review_status': 'Open'}

@app.get('/api/settings')
def get_settings(): return {'thresholds': thresholds, 'monitoring_frequency': monitoring_frequency}

@app.put('/api/settings')
def update_settings(payload: dict, x_api_key: str | None = Header(default=None)):
    global monitoring_frequency
    require_write_key(x_api_key)
    updated = dict(thresholds)
    for key in ('low', 'moderate', 'high'):
        if key in payload: updated[key] = float(payload[key])
    if not (0 <= updated['low'] < updated['moderate'] < updated['high'] <= 1):
        raise HTTPException(400, 'Thresholds must be ordered between 0 and 1.')
    thresholds.update(updated)
    if payload.get('monitoring_frequency') in {'Every 6 hours', 'Daily', 'Weekly'}:
        monitoring_frequency = payload['monitoring_frequency']
    save_record('settings', {'id': 'global', 'thresholds': thresholds, 'monitoring_frequency': monitoring_frequency, 'updated_at': datetime.now().isoformat()})
    return {'thresholds': thresholds, 'monitoring_frequency': monitoring_frequency}

@app.get('/api/investigations')
def investigations():
    return {'investigations': investigation_store}

@app.post('/api/investigations')
def create_investigation(payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    item = {'id': str(uuid.uuid4()), 'title': str(payload.get('title', 'Reliability investigation')).strip() or 'Reliability investigation', 'status': 'OPEN', 'owner': str(payload.get('owner', 'Administrator')), 'notes': str(payload.get('notes', '')), 'model_id': str(payload.get('model_id', 'churn-v24')), 'created_at': datetime.now().isoformat(), 'updated_at': datetime.now().isoformat()}
    investigation_store.append(item); save_record('investigation', item)
    return item

@app.put('/api/investigations/{investigation_id}')
def update_investigation(investigation_id: str, payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    item = next((entry for entry in investigation_store if entry['id'] == investigation_id), None)
    if not item: raise HTTPException(404, 'Investigation not found.')
    item.update({key: payload[key] for key in ('status', 'notes', 'owner') if key in payload}); item['updated_at'] = datetime.now().isoformat(); save_record('investigation', item)
    return item

@app.get('/api/incidents')
def incidents():
    return {'incidents': incident_store}

@app.post('/api/incidents')
def create_incident(payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    item = {'id': str(uuid.uuid4()), 'title': str(payload.get('title', 'Monitoring incident')).strip() or 'Monitoring incident', 'severity': str(payload.get('severity', 'MEDIUM')).upper(), 'status': 'OPEN', 'assignee': str(payload.get('assignee', 'Unassigned')), 'description': str(payload.get('description', '')), 'created_at': datetime.now().isoformat(), 'updated_at': datetime.now().isoformat()}
    incident_store.append(item); save_record('incident', item)
    return item

@app.put('/api/incidents/{incident_id}')
def update_incident(incident_id: str, payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    item = next((entry for entry in incident_store if entry['id'] == incident_id), None)
    if not item: raise HTTPException(404, 'Incident not found.')
    item.update({key: payload[key] for key in ('status', 'severity', 'assignee', 'description') if key in payload}); item['updated_at'] = datetime.now().isoformat(); save_record('incident', item)
    return item

@app.get('/api/models/{model_id}/snapshots')
def model_snapshots(model_id: str, days: int = 30):
    if model_id not in snapshot_store: raise HTTPException(404, 'Model not found.')
    return {'model_id': model_id, 'snapshots': snapshot_store[model_id][-max(1, min(days, 90)):]} 

@app.get('/api/models/{model_id}/features')
def model_features(model_id: str):
    if model_id not in feature_store: raise HTTPException(404, 'Model not found.')
    return {'model_id': model_id, 'features': feature_store[model_id]}

@app.get('/api/models/{model_id}/forecast')
def model_forecast(model_id: str):
    if model_id not in snapshot_store: raise HTTPException(404, 'Model not found.')
    cached = forecast_cache.get(model_id)
    if cached and (datetime.now() - cached['created']).total_seconds() < 30:
        return cached['value']
    recent = snapshot_store[model_id][-7:]
    slope = (recent[-1]['reliability_score'] - recent[0]['reliability_score']) / max(1, len(recent)-1)
    current = recent[-1]['reliability_score']
    predicted = [{'day': i, 'score': round(max(0, min(100, current + slope * i)), 1)} for i in range(1, 15)]
    days_until = round((current - 50) / abs(slope), 1) if slope < 0 else None
    sentence = 'Reliability is stable over the observed window.' if slope >= 0 else f'At this pace, the score may cross 50 in about {days_until:.0f} days.'
    result = {'current_score': current, 'slope': round(slope, 3), 'predicted': predicted, 'days_until_50': days_until, 'confidence_band': 5.5, 'summary': sentence}
    forecast_cache[model_id] = {'created': datetime.now(), 'value': result}
    return result

@app.post('/api/models/{model_id}/monitor')
def monitor_model(model_id: str, payload: dict = Body(default={})): 
    if model_id not in model_registry: raise HTTPException(404, 'Model not found.')
    drift_score = float(payload.get('drift_score', .18))
    score = round(max(0, min(100, 96 - drift_score * 52)), 1)
    verdict = 'healthy' if score >= 80 else 'watch' if score >= 50 else 'retrain'
    snap = {'id': str(uuid.uuid4()), 'model_id': model_id, 'timestamp': datetime.now().isoformat(), 'reliability_score': score, 'performance_score': payload.get('performance_score', 94.2), 'drift_score': drift_score, 'confidence_score': payload.get('confidence_score', 91), 'quality_score': payload.get('quality_score', 92), 'accuracy': payload.get('accuracy'), 'f1': payload.get('f1'), 'avg_confidence': payload.get('avg_confidence', .91), 'verdict': verdict, 'window_size': payload.get('window_size', 1000)}
    snapshot_store[model_id].append(snap)
    save_snapshot(snap)
    forecast_cache.pop(model_id, None)
    model_registry[model_id]['status'] = verdict.upper()
    save_model(model_registry[model_id])
    return {'snapshot': snap, 'features': feature_store[model_id], 'verdict': verdict, 'forecast': model_forecast(model_id)}

@app.post('/api/simulator/run')
def simulator_run(payload: dict = Body(default={})): 
    model_id = payload.get('model_id', 'churn-v24')
    if model_id not in model_registry:
        raise HTTPException(404, 'Model not found.')
    drift = min(1, max(0, abs(float(payload.get('mean_shift', .18))) * .45 + max(0, float(payload.get('variance_multiplier', 1)) - 1) * .2 + float(payload.get('missing_rate', 0)) * .35 + float(payload.get('category_swap_rate', 0)) * .2 + float(payload.get('label_noise', 0)) * .2))
    drift = round(drift, 3)
    score = round(max(0, min(100, 96 - drift * 52)), 1)
    verdict = 'healthy' if score >= 80 else 'watch' if score >= 50 else 'retrain'
    persisted = bool(payload.get('persist', False))
    features = feature_store[model_id]
    if persisted:
        result = monitor_model(model_id, {'drift_score': drift, 'window_size': int(payload.get('batch_size', 1000))})
        score, verdict, features = result['snapshot']['reliability_score'], result['verdict'], result['features']
    return {'scenario': payload, 'drift_score': drift, 'reliability_score': score, 'verdict': verdict, 'features': features, 'persisted': persisted}

@app.post('/api/ingest')
def ingest(payload: dict = Body(default={}), x_api_key: str | None = Header(default=None)):
    require_write_key(x_api_key)
    name = str(payload.get('model_name', 'Connected model'))
    model_id = next((key for key, value in model_registry.items() if value['name'] == name), None)
    if model_id is None:
        model_id = 'custom-' + uuid.uuid4().hex[:8]
        model_registry[model_id] = {'id': model_id, 'name': name, 'description': 'SDK-connected model', 'status': 'HEALTHY', 'version': 'v1.0', 'task_type': 'classification', 'accuracy': 0}
        snapshot_store[model_id] = []
        feature_store[model_id] = []
        version_store[model_id] = [{'version': 'v1.0', 'accuracy': 0, 'f1': 0, 'trained_at': datetime.now().isoformat(), 'is_active': True}]
        save_model(model_registry[model_id])
    predictions = payload.get('predictions', [])
    labels = payload.get('labels')
    if not isinstance(predictions, list): predictions = [predictions]
    if labels is not None and not isinstance(labels, list): labels = [labels]
    accuracy = None
    if labels and predictions:
        pairs = list(zip(labels, predictions))
        accuracy = round(sum(str(actual) == str(predicted) for actual, predicted in pairs) / len(pairs) * 100, 2)
    confidences = payload.get('confidences')
    if confidences is not None and not isinstance(confidences, list): confidences = [confidences]
    avg_confidence = round(float(np.mean([float(value) for value in confidences])), 4) if confidences else .91
    return monitor_model(model_id, {'drift_score': float(payload.get('drift_score', .05)), 'window_size': len(payload.get('features', [])) or 1, 'accuracy': accuracy, 'performance_score': accuracy if accuracy is not None else 94.2, 'avg_confidence': avg_confidence, 'confidence_score': avg_confidence * 100})

@app.post('/api/models/{model_id}/retrain')
def retrain(model_id: str):
    if model_id not in model_registry: raise HTTPException(404, 'Model not found.')
    old = model_registry[model_id]['accuracy']; new = round(min(99.9, old + 1.7), 1); version = f"v{len(version_store.get(model_id, [])) + 2}.0"
    version_store.setdefault(model_id, []).append({'version': version, 'accuracy': new, 'f1': round(new - 2.1, 1), 'trained_at': datetime.now().isoformat(), 'is_active': True})
    model_registry[model_id].update({'accuracy': new, 'version': version, 'status': 'HEALTHY'})
    return {'before': {'accuracy': old}, 'after': {'accuracy': new}, 'version': version, 'verdict': 'healthy'}

@app.post('/api/models/{model_id}/rollback')
def rollback(model_id: str):
    versions = version_store.get(model_id, [])
    if len(versions) < 2: raise HTTPException(400, 'No previous version is available for rollback.')
    versions[-1]['is_active'] = False; previous = versions[-2]; previous['is_active'] = True
    model_registry[model_id].update({'version': previous['version'], 'accuracy': previous['accuracy']})
    return {'status': 'rolled_back', 'version': previous['version']}

@app.get('/api/models/{model_id}/versions')
def versions(model_id: str): return {'versions': version_store.get(model_id, [])}

@app.post('/api/models/{model_id}/healing')
def healing(model_id: str, payload: dict = Body(default={})):
    if model_id not in model_registry: raise HTTPException(404, 'Model not found.')
    state = {'model_id': model_id, 'enabled': bool(payload.get('enabled', True)), 'safe_margin': float(payload.get('safe_margin', .02))}
    if not 0 <= state['safe_margin'] <= 1: raise HTTPException(400, 'Safe margin must be between 0 and 1.')
    healing_state[model_id] = state
    healing_events.append({'model_id': model_id, 'timestamp': datetime.now().isoformat(), 'action': 'enabled' if state['enabled'] else 'disabled', 'safe_margin': state['safe_margin']})
    return state

@app.get('/api/models/{model_id}/healing/events')
def healing_history(model_id: str):
    if model_id not in model_registry: raise HTTPException(404, 'Model not found.')
    return {'state': healing_state.get(model_id, {'model_id': model_id, 'enabled': False, 'safe_margin': .02}), 'events': [event for event in healing_events if event['model_id'] == model_id]}

@app.post('/api/models/{model_id}/chat')
def model_chat(model_id: str, payload: dict = Body(default={})): 
    message = str(payload.get('message', '')).strip()
    if not message: raise HTTPException(422, 'Message is required.')
    snapshots = snapshot_store.get(model_id, [])
    latest = snapshots[-1] if snapshots else {'reliability_score': 86, 'drift_score': .18}
    answer = f"The latest reliability score is {latest['reliability_score']}/100 with drift at {latest['drift_score']}. Review the highest-drift features and validate against labeled outcomes before deciding on retraining."
    chat_store.setdefault(model_id, []).extend([{'role': 'user', 'content': message}, {'role': 'assistant', 'content': answer}])
    return {'role': 'assistant', 'content': answer, 'chart_hint': {'type': 'trend', 'date_range': '30d'}}

@app.get('/api/models/{model_id}/fairness')
def fairness(model_id: str): return {'model_id': model_id, 'groups': [{'feature': 'gender', 'group': 'Female', 'accuracy': 92.1, 'positive_rate': .41, 'disparity_ratio': .88, 'flagged': False}, {'feature': 'gender', 'group': 'Male', 'accuracy': 93.4, 'positive_rate': .47, 'disparity_ratio': 1.0, 'flagged': False}, {'feature': 'city_tier', 'group': 'Tier 3', 'accuracy': 81.2, 'positive_rate': .29, 'disparity_ratio': .74, 'flagged': True}]}

@app.get('/api/models/{model_id}/security')
def security(model_id: str): return {'events': [{'timestamp': '2026-10-25T10:42:00', 'event_type': 'Outlier batch', 'severity': 'WARNING', 'details': '12 inputs exceeded baseline range.'}]}

@app.post('/api/models/{model_id}/badge')
def create_badge(model_id: str):
    token = uuid.uuid4().hex; badge_store[token] = model_id; return {'token': token, 'url': f'/api/public/badge/{token}'}

@app.get('/api/public/badge/{token}')
def public_badge(token: str):
    model_id = badge_store.get(token)
    if not model_id: raise HTTPException(404, 'Badge not found.')
    latest = snapshot_store[model_id][-1]; return {'model': model_registry[model_id]['name'], 'score': latest['reliability_score'], 'verdict': latest['verdict'], 'svg': f'<svg xmlns="http://www.w3.org/2000/svg" width="220" height="48"><rect width="220" height="48" rx="8" fill="#111418"/><text x="14" y="21" fill="#9AA1AC" font-family="Arial" font-size="11">MODEL RELIABILITY</text><text x="14" y="38" fill="#34D399" font-family="Arial" font-size="13">{latest["reliability_score"]}/100 · {latest["verdict"].upper()}</text></svg>'}

@app.get('/api/models/{model_id}/report.pdf')
def report_pdf(model_id: str):
    if model_id not in model_registry: raise HTTPException(404, 'Model not found.')
    try:
        from reportlab.pdfgen import canvas
        stream = BytesIO(); pdf = canvas.Canvas(stream); pdf.setTitle('Model Reliability Report'); pdf.setFont('Helvetica-Bold', 18); pdf.drawString(54, 770, 'Obsidian Labs — Model Reliability Report'); pdf.setFont('Helvetica', 11); pdf.drawString(54, 742, model_registry[model_id]['name']); latest = snapshot_store[model_id][-1]; pdf.drawString(54, 710, f"Reliability score: {latest['reliability_score']}/100"); pdf.drawString(54, 690, f"Verdict: {latest['verdict'].upper()}"); pdf.drawString(54, 650, 'Monitoring provides an early warning, not proof that a model is wrong.'); pdf.save(); return Response(stream.getvalue(), media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename=reliability-report.pdf'})
    except ImportError:
        # Keep exports useful in minimal/offline environments without reportlab.
        latest = snapshot_store[model_id][-1]
        lines = ['Obsidian Labs - Model Reliability Report', model_registry[model_id]['name'], f"Reliability score: {latest['reliability_score']}/100", f"Verdict: {latest['verdict'].upper()}", 'Drift is an early warning, not proof that a model is wrong.']
        stream = BytesIO()
        objects = []
        body = 'BT /F1 12 Tf 54 760 Td (' + lines[0] + ') Tj 0 -24 Td (' + lines[1] + ') Tj 0 -24 Td (' + lines[2] + ') Tj 0 -24 Td (' + lines[3] + ') Tj 0 -24 Td (' + lines[4] + ') Tj ET'
        objects.append('1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj')
        objects.append('2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj')
        objects.append('3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>endobj')
        objects.append('4 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj')
        objects.append(f'5 0 obj<< /Length {len(body.encode())} >>stream\n{body}\nendstream endobj')
        pdf = '%PDF-1.4\n'; offsets = [0]
        for obj in objects: offsets.append(len(pdf.encode())); pdf += obj + '\n'
        xref = len(pdf.encode()); pdf += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n' + ''.join(f'{offset:010d} 00000 n \n' for offset in offsets[1:]) + f'trailer<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'
        return Response(pdf.encode(), media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename=reliability-report.pdf'})
