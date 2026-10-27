# Reliability Monitor SDK

```python
from reliability_monitor_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor('http://localhost:8000', model_name='Checkout risk')
monitor.log(features_df, predictions, labels=labels, confidences=confidences)
```

The SDK is intentionally failure-tolerant: telemetry errors return `False` and never interrupt a user's model code.
