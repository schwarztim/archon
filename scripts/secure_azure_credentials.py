#!/usr/bin/env python3
"""Secure Azure OpenAI credential management using macOS Keychain."""

import os
import subprocess
import sys
from pathlib import Path


class AzureCredentialManager:
    """Manages Azure OpenAI credentials securely via macOS Keychain."""

    SERVICE_NAME = "archon-azure-openai"

    @classmethod
    def store_credentials(
        cls, endpoint: str, api_key: str, api_version: str = "2025-01-01-preview"
    ):
        """Store Azure OpenAI credentials in macOS Keychain."""
        try:
            # Store endpoint
            subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-s",
                    cls.SERVICE_NAME,
                    "-a",
                    "endpoint",
                    "-w",
                    endpoint,
                    "-U",  # Update if exists
                ],
                check=True,
                capture_output=True,
            )

            # Store API key
            subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-s",
                    cls.SERVICE_NAME,
                    "-a",
                    "api_key",
                    "-w",
                    api_key,
                    "-U",
                ],
                check=True,
                capture_output=True,
            )

            # Store API version
            subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-s",
                    cls.SERVICE_NAME,
                    "-a",
                    "api_version",
                    "-w",
                    api_version,
                    "-U",
                ],
                check=True,
                capture_output=True,
            )

            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to store credentials: {e}")
            return False

    @classmethod
    def get_credential(cls, account: str) -> str:
        """Retrieve a credential from macOS Keychain."""
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-s",
                    cls.SERVICE_NAME,
                    "-a",
                    account,
                    "-w",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""

    @classmethod
    def get_all_credentials(cls) -> dict:
        """Get all Azure OpenAI credentials."""
        return {
            "endpoint": cls.get_credential("endpoint"),
            "api_key": cls.get_credential("api_key"),
            "api_version": cls.get_credential("api_version") or "2025-01-01-preview",
        }

    @classmethod
    def migrate_from_env(cls) -> bool:
        """Migrate existing credentials from .env to Keychain."""
        from dotenv import load_dotenv

        # Load current .env
        env_path = Path(__file__).parent.parent / ".env"
        load_dotenv(env_path)

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

        if not endpoint or not api_key:
            print("No Azure OpenAI credentials found in .env")
            return False

        print(f"Migrating credentials to Keychain...")
        print(f"  Endpoint: {endpoint}")
        print(f"  API Key: {'*' * (len(api_key) - 8) + api_key[-8:]}")
        print(f"  API Version: {api_version}")

        success = cls.store_credentials(endpoint, api_key, api_version)
        if success:
            print("✓ Credentials stored in Keychain")
            return True
        else:
            print("✗ Failed to store credentials")
            return False

    @classmethod
    def create_env_template(cls) -> None:
        """Create secure .env template that references Keychain."""
        env_path = Path(__file__).parent.parent / ".env"
        template_lines = []

        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("AZURE_OPENAI_"):
                    # Comment out direct credentials
                    template_lines.append(f"# {line}")
                    if "ENDPOINT" in line:
                        template_lines.append(
                            "# Azure credentials now managed via macOS Keychain\n"
                        )
                        template_lines.append(
                            "# Use scripts/secure_azure_credentials.py to manage\n"
                        )
                else:
                    template_lines.append(line)

        with open(env_path, "w") as f:
            f.writelines(template_lines)

        print(f"✓ Updated {env_path} to reference Keychain")


def main():
    """CLI for credential management."""
    if len(sys.argv) < 2:
        print("Usage:")
        print(
            "  python3 secure_azure_credentials.py migrate    # Migrate from .env to Keychain"
        )
        print(
            "  python3 secure_azure_credentials.py test       # Test credential retrieval"
        )
        print(
            "  python3 secure_azure_credentials.py store <endpoint> <api_key> [api_version]"
        )
        sys.exit(1)

    manager = AzureCredentialManager()
    command = sys.argv[1]

    if command == "migrate":
        if manager.migrate_from_env():
            manager.create_env_template()
            print("\n✓ Migration complete. Credentials now secure in Keychain.")
        else:
            print("\n✗ Migration failed.")

    elif command == "test":
        creds = manager.get_all_credentials()
        if creds["endpoint"] and creds["api_key"]:
            print("✓ Credentials found in Keychain:")
            print(f"  Endpoint: {creds['endpoint']}")
            print(
                f"  API Key: {'*' * (len(creds['api_key']) - 8) + creds['api_key'][-8:]}"
            )
            print(f"  API Version: {creds['api_version']}")
        else:
            print("✗ No credentials found in Keychain")

    elif command == "store":
        if len(sys.argv) < 4:
            print("Usage: store <endpoint> <api_key> [api_version]")
            sys.exit(1)

        endpoint = sys.argv[2]
        api_key = sys.argv[3]
        api_version = sys.argv[4] if len(sys.argv) > 4 else "2025-01-01-preview"

        if manager.store_credentials(endpoint, api_key, api_version):
            print("✓ Credentials stored successfully")
        else:
            print("✗ Failed to store credentials")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
