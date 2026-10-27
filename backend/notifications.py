"""Server-side Telegram and Twilio notification delivery."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _load_local_env() -> None:
    """Load simple KEY=value files for local development without exposing them to Vite."""
    for path in (Path(__file__).with_name('.env'), Path(__file__).parent.parent / '.env'):
        if not path.exists(): continue
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()


def _post(url: str, data: dict[str, str], headers: dict[str, str] | None = None) -> dict:
    request = Request(url, data=urlencode(data).encode(), headers=headers or {}, method='POST')
    with urlopen(request, timeout=10) as response:
        import json
        return json.loads(response.read().decode() or '{}')


def status() -> dict:
    return {
        'telegram': bool(os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID')),
        'sms': bool(os.getenv('TWILIO_ACCOUNT_SID') and os.getenv('TWILIO_AUTH_TOKEN') and os.getenv('TWILIO_FROM_NUMBER') and os.getenv('ALERT_SMS_TO')),
        'sms_provider': 'twilio',
    }


def send_telegram(message: str) -> dict:
    token, chat_id = os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id: return {'sent': False, 'reason': 'Telegram credentials are not configured.'}
    result = _post(f'https://api.telegram.org/bot{token}/sendMessage', {'chat_id': chat_id, 'text': message})
    if not result.get('ok'): raise RuntimeError(result.get('description', 'Telegram delivery failed.'))
    return {'sent': True, 'channel': 'telegram'}


def send_sms(message: str) -> dict:
    sid, auth, sender, recipient = (os.getenv(key) for key in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER', 'ALERT_SMS_TO'))
    if not all((sid, auth, sender, recipient)): return {'sent': False, 'reason': 'Twilio SMS credentials are not configured.'}
    encoded = base64.b64encode(f'{sid}:{auth}'.encode()).decode()
    recipients = [item.strip() for item in recipient.split(',') if item.strip()]
    results = []
    for number in recipients:
        _post(f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json', {'To': number, 'From': sender, 'Body': message}, {'Authorization': f'Basic {encoded}'})
        results.append(number)
    return {'sent': True, 'channel': 'sms', 'recipients': results}


def dispatch(alert: dict) -> dict:
    message = f"{alert.get('type', 'ALERT')}: {alert.get('title', 'Reliability alert')} — {alert.get('text', '')}"
    results = []
    for sender in (send_telegram, send_sms):
        try: results.append(sender(message))
        except Exception as error: results.append({'sent': False, 'reason': str(error)})
    return {'results': results}
