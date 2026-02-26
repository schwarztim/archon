#!/usr/bin/env python3
"""Azure OpenAI health check and monitoring script."""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple
import httpx

# Add backend to path
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.config import azure_settings
from app.features.azure_flags import AzureFeatureFlags


class AzureHealthChecker:
    """Comprehensive health checking for Azure OpenAI deployments."""

    def __init__(self):
        self.credentials = azure_settings.get_secure_credentials()
        self.timeout = AzureFeatureFlags.get_timeout_ms() / 1000  # Convert to seconds
        self.max_retries = AzureFeatureFlags.get_max_retries()

    async def check_endpoint_reachability(self) -> Tuple[bool, str, float]:
        """Check if Azure OpenAI endpoint is reachable."""
        if not self.credentials["endpoint"] or not self.credentials["api_key"]:
            return False, "Missing credentials", 0.0

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.credentials['endpoint'].rstrip('/')}/openai/models",
                    params={"api-version": self.credentials["api_version"]},
                    headers={"api-key": self.credentials["api_key"]},
                )
                latency = (time.time() - start_time) * 1000  # Convert to ms

                if response.status_code == 200:
                    return True, "Endpoint healthy", latency
                elif response.status_code in (401, 403):
                    return (
                        False,
                        f"Authentication failed (HTTP {response.status_code})",
                        latency,
                    )
                else:
                    return False, f"Unexpected status: {response.status_code}", latency

        except httpx.TimeoutException:
            latency = (time.time() - start_time) * 1000
            return False, f"Timeout after {self.timeout}s", latency
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return False, f"Connection error: {str(e)}", latency

    async def check_model_availability(
        self, deployment_name: str
    ) -> Tuple[bool, str, float]:
        """Check if a specific model deployment is available."""
        if not self.credentials["endpoint"] or not self.credentials["api_key"]:
            return False, "Missing credentials", 0.0

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Test with a minimal completion request
                response = await client.post(
                    f"{self.credentials['endpoint'].rstrip('/')}/openai/deployments/{deployment_name}/chat/completions",
                    params={"api-version": self.credentials["api_version"]},
                    headers={
                        "api-key": self.credentials["api_key"],
                        "Content-Type": "application/json",
                    },
                    json={
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 1,
                        "temperature": 0,
                    },
                )
                latency = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    return True, "Model available", latency
                elif response.status_code == 404:
                    return False, "Model deployment not found", latency
                elif response.status_code == 429:
                    return False, "Rate limited", latency
                elif response.status_code in (401, 403):
                    return False, "Authentication failed", latency
                else:
                    return False, f"HTTP {response.status_code}", latency

        except httpx.TimeoutException:
            latency = (time.time() - start_time) * 1000
            return False, f"Timeout after {self.timeout}s", latency
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return False, f"Error: {str(e)}", latency

    async def check_all_models(self) -> Dict[str, Tuple[bool, str, float]]:
        """Check health of all Azure model deployments."""
        seed_file = Path(__file__).parent.parent / "data" / "azure_models_seed.json"

        try:
            with open(seed_file) as f:
                seed_data = json.load(f)
        except FileNotFoundError:
            return {"seed_file_error": (False, "azure_models_seed.json not found", 0.0)}

        models = seed_data.get("models", [])
        results = {}

        # Check models in batches to avoid overwhelming the service
        batch_size = 5
        for i in range(0, len(models), batch_size):
            batch = models[i : i + batch_size]
            tasks = []

            for model in batch:
                deployment_name = model.get("config", {}).get(
                    "azure_deployment", model["name"]
                )
                task = self.check_model_availability(deployment_name)
                tasks.append((model["name"], task))

            # Execute batch
            for model_name, task in tasks:
                try:
                    result = await task
                    results[model_name] = result
                except Exception as e:
                    results[model_name] = (False, f"Health check failed: {e}", 0.0)

            # Small delay between batches
            await asyncio.sleep(0.5)

        return results

    async def generate_health_report(self) -> Dict:
        """Generate comprehensive health report."""
        print("🔍 Starting Azure OpenAI health check...")

        # Basic connectivity check
        (
            endpoint_healthy,
            endpoint_msg,
            endpoint_latency,
        ) = await self.check_endpoint_reachability()

        print(
            f"🌐 Endpoint: {'✅' if endpoint_healthy else '❌'} {endpoint_msg} ({endpoint_latency:.1f}ms)"
        )

        # Feature flags status
        feature_config = AzureFeatureFlags.get_feature_config()
        print(
            f"🚩 Azure provider enabled: {'✅' if feature_config['provider_enabled'] else '❌'}"
        )
        print(
            f"🚩 Cost tracking enabled: {'✅' if feature_config['cost_tracking'] else '❌'}"
        )
        print(
            f"🚩 Fallback enabled: {'✅' if feature_config['fallback_enabled'] else '❌'}"
        )

        # Model availability check (if endpoint is healthy)
        model_results = {}
        if endpoint_healthy and AzureFeatureFlags.is_health_check_enabled():
            print("\n📋 Checking model deployments...")
            model_results = await self.check_all_models()

            healthy_count = sum(
                1 for healthy, _, _ in model_results.values() if healthy
            )
            total_count = len(model_results)

            print(f"📊 Model health: {healthy_count}/{total_count} deployments healthy")

            # Show unhealthy models
            unhealthy = [
                (name, msg)
                for name, (healthy, msg, _) in model_results.items()
                if not healthy
            ]
            if unhealthy:
                print("❌ Unhealthy deployments:")
                for name, msg in unhealthy[:5]:  # Show first 5
                    print(f"   • {name}: {msg}")
                if len(unhealthy) > 5:
                    print(f"   ... and {len(unhealthy) - 5} more")

        # Credential source info
        creds_source = self.credentials.get("source", "unknown")
        print(f"🔐 Credentials from: {creds_source}")

        # Generate JSON report
        report = {
            "timestamp": time.time(),
            "endpoint": {
                "healthy": endpoint_healthy,
                "message": endpoint_msg,
                "latency_ms": endpoint_latency,
                "url": self.credentials["endpoint"],
            },
            "credentials": {
                "source": creds_source,
                "has_endpoint": bool(self.credentials["endpoint"]),
                "has_api_key": bool(self.credentials["api_key"]),
            },
            "feature_flags": feature_config,
            "models": {
                name: {"healthy": healthy, "message": msg, "latency_ms": latency}
                for name, (healthy, msg, latency) in model_results.items()
            },
            "summary": {
                "endpoint_healthy": endpoint_healthy,
                "models_checked": len(model_results),
                "models_healthy": sum(
                    1 for healthy, _, _ in model_results.values() if healthy
                ),
                "overall_health": endpoint_healthy
                and (
                    len(model_results) == 0
                    or sum(1 for healthy, _, _ in model_results.values() if healthy) > 0
                ),
            },
        }

        return report


async def main():
    """Main health check execution."""
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        # JSON output mode for integration
        checker = AzureHealthChecker()
        report = await checker.generate_health_report()
        print(json.dumps(report, indent=2))
    else:
        # Human-readable output
        print("=" * 60)
        print("Azure OpenAI Health Check")
        print("=" * 60)

        checker = AzureHealthChecker()
        report = await checker.generate_health_report()

        print("\n" + "=" * 60)
        if report["summary"]["overall_health"]:
            print("🎉 Overall Status: HEALTHY")
        else:
            print("⚠️ Overall Status: DEGRADED")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
