"""Tiny, failure-tolerant SDK for sending model observations to the monitor."""
from __future__ import annotations

from typing import Any, Optional
import time

import pandas as pd
import requests


class ReliabilityMonitor:
    """Send feature batches without allowing observability failures to break inference."""

    def __init__(self, api_url: str, api_key: str = '', model_name: str = 'Connected model') -> None:
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.model_name = model_name

    def log(self, features_df: pd.DataFrame, predictions: Any, labels: Optional[Any] = None, confidences: Optional[Any] = None) -> bool:
        payload = {
            'model_name': self.model_name,
            'features': features_df.head(500).to_dict(orient='records'),
            'predictions': list(predictions)[:500] if hasattr(predictions, '__iter__') and not isinstance(predictions, str) else [predictions],
            'labels': list(labels)[:500] if labels is not None and hasattr(labels, '__iter__') and not isinstance(labels, str) else labels,
            'confidences': list(confidences)[:500] if confidences is not None and hasattr(confidences, '__iter__') and not isinstance(confidences, str) else confidences,
        }
        try:
            response = requests.post(self.api_url + '/api/ingest', json=payload, headers={'X-API-Key': self.api_key} if self.api_key else {}, timeout=4)
            return response.ok
        except Exception:
            return False

