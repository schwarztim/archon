#!/usr/bin/env python3
"""
Azure OpenAI Validation Script
Tests connectivity and configuration for Azure OpenAI service
"""

import argparse
import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
import urllib.request
import urllib.error
import urllib.parse
from dotenv import load_dotenv

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

try:
    from app.config import get_config
    from app.models.router import AIModelRouter, ModelRequest, ModelProvider
except ImportError as e:
    print(f"❌ Failed to import application modules: {e}")
    print("Make sure the backend application is properly structured")
    sys.exit(1)


class AzureOpenAIValidator:
    """Validator class for Azure OpenAI connectivity and configuration"""

    def __init__(self):
        # Load environment variables
        load_dotenv()
        self.config = get_config()
        self.router = AIModelRouter()

    def validate_environment(self) -> Dict[str, Any]:
        """Validate environment variables and configuration"""
        print("🔍 Validating environment configuration...")

        results = {"env_loaded": False, "config_valid": False, "required_vars": {}}

        # Check if .env file exists
        env_file = Path(".env")
        if env_file.exists():
            results["env_loaded"] = True
            print("✅ .env file found and loaded")
        else:
            print("❌ .env file not found")
            return results

        # Check required environment variables
        required_vars = [
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_API_VERSION",
        ]

        for var in required_vars:
            value = os.getenv(var)
            if value and value.strip():
                results["required_vars"][var] = "✅ Set"
                print(f"✅ {var}: Set")
            else:
                results["required_vars"][var] = "❌ Missing"
                print(f"❌ {var}: Missing or empty")

        # Validate configuration using the config class
        results["config_valid"] = self.config.validate_azure_config()
        if results["config_valid"]:
            print("✅ Azure OpenAI configuration is valid")
        else:
            print("❌ Azure OpenAI configuration is incomplete")

        return results

    def test_endpoint_reachability(self) -> Dict[str, Any]:
        """Test if the Azure OpenAI endpoint is reachable"""
        print("🔍 Testing endpoint reachability...")

        results = {"reachable": False, "status_code": None, "error": None}

        if not self.config.AZURE_OPENAI_ENDPOINT:
            results["error"] = "Endpoint not configured"
            print("❌ Endpoint not configured")
            return results

        # Test basic connectivity to the endpoint
        try:
            # Create a simple health check request
            health_url = f"{self.config.AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments?api-version={self.config.AZURE_OPENAI_API_VERSION}"

            req = urllib.request.Request(
                health_url,
                headers={
                    "api-key": self.config.AZURE_OPENAI_API_KEY,
                    "Content-Type": "application/json",
                },
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                results["status_code"] = response.status
                if response.status == 200:
                    results["reachable"] = True
                    print(f"✅ Endpoint is reachable (HTTP {response.status})")
                else:
                    print(f"⚠️ Endpoint responded with HTTP {response.status}")

        except urllib.error.HTTPError as e:
            results["status_code"] = e.code
            if e.code == 401:
                results["error"] = "Authentication failed - check API key"
                print("❌ Authentication failed - check your API key")
            elif e.code == 404:
                results["error"] = "Endpoint not found - check URL"
                print("❌ Endpoint not found - check your endpoint URL")
            else:
                results["error"] = f"HTTP {e.code}: {e.reason}"
                print(f"❌ HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            results["error"] = f"Network error: {e.reason}"
            print(f"❌ Network error: {e.reason}")
        except Exception as e:
            results["error"] = f"Unexpected error: {str(e)}"
            print(f"❌ Unexpected error: {str(e)}")

        return results

    async def test_model_completion(self) -> Dict[str, Any]:
        """Test a simple completion request using gpt-4o-mini"""
        print("🔍 Testing model completion...")

        results = {
            "completion_successful": False,
            "model_available": False,
            "response": None,
            "error": None,
        }

        try:
            # Create a test request
            test_request = ModelRequest(
                prompt="Hello, this is a test. Please respond with 'Test successful'.",
                model="gpt-4o-mini",
                max_tokens=50,
                temperature=0.1,
                provider=ModelProvider.AZURE_OPENAI,
            )

            # Use the router to handle the request
            response = await self.router.route_request(test_request)

            results["completion_successful"] = True
            results["model_available"] = True
            results["response"] = {
                "content": response.content,
                "model": response.model,
                "usage": response.usage,
                "metadata": response.metadata,
            }

            print("✅ Model completion test successful")
            print(f"Model: {response.model}")
            print(f"Response: {response.content[:100]}...")

        except Exception as e:
            results["error"] = str(e)
            print(f"❌ Model completion test failed: {str(e)}")

        return results

    def test_router_health(self) -> Dict[str, Any]:
        """Test the router health check functionality"""
        print("🔍 Testing router health check...")

        try:
            health_status = self.router.health_check()
            print("✅ Router health check completed")

            for provider, status in health_status.items():
                if status["healthy"]:
                    print(f"✅ {provider}: Healthy")
                else:
                    print(f"❌ {provider}: Unhealthy")

            return health_status

        except Exception as e:
            print(f"❌ Router health check failed: {str(e)}")
            return {"error": str(e)}

    async def run_full_validation(self) -> Dict[str, Any]:
        """Run complete validation suite"""
        print("🚀 Starting Azure OpenAI validation...")
        print("=" * 50)

        # Collect all test results
        results = {
            "timestamp": str(asyncio.get_event_loop().time()),
            "environment": self.validate_environment(),
            "endpoint_reachability": self.test_endpoint_reachability(),
            "router_health": self.test_router_health(),
            "model_completion": await self.test_model_completion(),
        }

        print("\n" + "=" * 50)
        print("📊 VALIDATION SUMMARY")
        print("=" * 50)

        # Overall status
        env_ok = results["environment"]["config_valid"]
        endpoint_ok = results["endpoint_reachability"]["reachable"]
        completion_ok = results["model_completion"]["completion_successful"]

        if env_ok and endpoint_ok and completion_ok:
            print("🎉 ALL TESTS PASSED - Azure OpenAI is properly configured!")
            results["overall_status"] = "PASS"
        else:
            print("❌ SOME TESTS FAILED - Check configuration and connectivity")
            results["overall_status"] = "FAIL"

        # Print summary details
        print(f"\n📋 Results:")
        print(f"  Environment Configuration: {'✅ PASS' if env_ok else '❌ FAIL'}")
        print(f"  Endpoint Reachability: {'✅ PASS' if endpoint_ok else '❌ FAIL'}")
        print(f"  Model Completion: {'✅ PASS' if completion_ok else '❌ FAIL'}")

        return results


def _run_pytest_suite() -> Dict[str, Any]:
    """Run pytest suite for Azure wiring tests."""
    results: Dict[str, Any] = {"ran": False, "passed": False, "exit_code": None}

    try:
        import pytest
    except ImportError as exc:
        results["error"] = f"pytest not available: {exc}"
        return results

    project_root = Path(__file__).resolve().parent.parent
    test_file = project_root / "tests" / "test_azure_wiring" / "test_models.py"
    if not test_file.exists():
        results["error"] = f"Test file not found: {test_file}"
        return results

    exit_code = pytest.main([str(test_file)])
    results["ran"] = True
    results["exit_code"] = exit_code
    results["passed"] = exit_code == 0
    return results


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Azure OpenAI wiring")
    parser.add_argument(
        "--pytest",
        action="store_true",
        help="Run pytest suite for Azure wiring tests",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None):
    """Main function to run the validation"""
    args = _parse_args(argv or [])
    try:
        validator = AzureOpenAIValidator()
        results = await validator.run_full_validation()

        if args.pytest:
            results["pytest"] = _run_pytest_suite()

        # Save results to a file
        results_file = Path("azure_validation_results.json")
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)

        print(f"\n📄 Detailed results saved to: {results_file}")

        # Exit with appropriate code
        if results["overall_status"] == "PASS":
            sys.exit(0)
        else:
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n❌ Validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during validation: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
