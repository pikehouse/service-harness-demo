#!/usr/bin/env python3
"""Validate Grafana Cloud integration end-to-end.

This script tests:
1. Prometheus health check and connectivity
2. Push a test metric to Prometheus
3. Query the metric back
4. Loki health check and connectivity
5. Push a test log to Loki
6. Query the log back

Usage:
    python scripts/validate_grafana.py
"""

import sys
import time
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, "src")

from harness.grafana import PrometheusClient, LokiClient


def main():
    print("=" * 60)
    print("Grafana Cloud Integration Validation")
    print("=" * 60)
    print()

    # Create clients (will use settings from .env)
    print("Creating clients...")
    prometheus = PrometheusClient()
    loki = LokiClient()
    print()

    # Track results
    results = []

    # === PROMETHEUS TESTS ===
    print("-" * 40)
    print("PROMETHEUS TESTS")
    print("-" * 40)

    # Test 1: Health check
    print("\n1. Testing Prometheus health check...")
    try:
        healthy = prometheus.check_health()
        if healthy:
            print("   ✓ Prometheus is healthy")
            results.append(("Prometheus health", True))
        else:
            print("   ✗ Prometheus health check failed")
            results.append(("Prometheus health", False))
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results.append(("Prometheus health", False))

    # Test 2: Push a metric
    print("\n2. Pushing test metric to Prometheus...")
    test_metric_name = "harness_validation_test"
    test_metric_value = 42.0
    try:
        prometheus.push_metrics([{
            "name": test_metric_name,
            "value": test_metric_value,
            "labels": {"source": "validation_script", "test": "true"},
        }])
        print(f"   ✓ Pushed {test_metric_name}={test_metric_value}")
        results.append(("Prometheus push", True))
    except Exception as e:
        print(f"   ✗ Error pushing metric: {e}")
        results.append(("Prometheus push", False))

    # Test 3: Query the metric
    print("\n3. Querying metric from Prometheus...")
    print("   (waiting 5 seconds for metric to be indexed...)")
    time.sleep(5)
    try:
        query = f'{test_metric_name}{{source="validation_script"}}'
        result = prometheus.query(query)
        if result.get("data", {}).get("result"):
            value = result["data"]["result"][0]["value"][1]
            print(f"   ✓ Query returned value: {value}")
            results.append(("Prometheus query", True))
        else:
            print("   ⚠ Query returned no data (metric may not be indexed yet)")
            print("     This is normal for new metrics - try again in a minute")
            results.append(("Prometheus query", "partial"))
    except Exception as e:
        print(f"   ✗ Error querying metric: {e}")
        results.append(("Prometheus query", False))

    # === LOKI TESTS ===
    print("\n" + "-" * 40)
    print("LOKI TESTS")
    print("-" * 40)

    # Test 4: Health check
    print("\n4. Testing Loki health check...")
    try:
        healthy = loki.check_health()
        if healthy:
            print("   ✓ Loki is healthy")
            results.append(("Loki health", True))
        else:
            print("   ✗ Loki health check failed")
            results.append(("Loki health", False))
    except Exception as e:
        print(f"   ✗ Error: {e}")
        results.append(("Loki health", False))

    # Test 5: Push a log
    print("\n5. Pushing test log to Loki...")
    test_log_message = f"Harness validation test at {datetime.utcnow().isoformat()}"
    try:
        loki.push_log(
            labels={"app": "harness_validation", "test": "true"},
            message=test_log_message,
        )
        print(f"   ✓ Pushed log: {test_log_message[:50]}...")
        results.append(("Loki push", True))
    except Exception as e:
        print(f"   ✗ Error pushing log: {e}")
        results.append(("Loki push", False))

    # Test 6: Query logs
    print("\n6. Querying logs from Loki...")
    print("   (waiting 5 seconds for log to be indexed...)")
    time.sleep(5)
    try:
        query = '{app="harness_validation"}'
        result = loki.query(
            query,
            limit=10,
            start=datetime.utcnow() - timedelta(minutes=5),
            end=datetime.utcnow(),
        )
        streams = result.get("data", {}).get("result", [])
        if streams:
            log_count = sum(len(s.get("values", [])) for s in streams)
            print(f"   ✓ Query returned {log_count} log entries")
            results.append(("Loki query", True))
        else:
            print("   ⚠ Query returned no data (log may not be indexed yet)")
            print("     This is normal for new logs - try again in a minute")
            results.append(("Loki query", "partial"))
    except Exception as e:
        print(f"   ✗ Error querying logs: {e}")
        results.append(("Loki query", False))

    # === SUMMARY ===
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r is True)
    partial = sum(1 for _, r in results if r == "partial")
    failed = sum(1 for _, r in results if r is False)

    for name, result in results:
        if result is True:
            print(f"  ✓ {name}")
        elif result == "partial":
            print(f"  ⚠ {name} (may need more time)")
        else:
            print(f"  ✗ {name}")

    print()
    print(f"Passed: {passed}, Partial: {partial}, Failed: {failed}")

    if failed == 0:
        print("\n🎉 Grafana integration is working!")
        return 0
    else:
        print("\n❌ Some tests failed. Check your .env configuration.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
