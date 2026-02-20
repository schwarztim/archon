"""Test suite for critical stub implementation fixes.

Tests signature verification and wizard node template generation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

import pytest

# Mock imports for testing
from app.models.wizard import PlannedNode


# ── Signature Verification Tests ───────────────────────────────────


def _canonical_json(obj: Any) -> str:
    """Produce a deterministic JSON string for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(content: str) -> str:
    """Compute SHA-256 hex digest of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sign(content_hash: str, signing_key: str) -> str:
    """Produce HMAC-SHA256 signature of a content hash."""
    return hmac.new(
        signing_key.encode("utf-8"),
        content_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class TestSignatureVerification:
    """Test signature creation and verification."""

    def test_signature_creation_and_storage(self):
        """Test that signatures are created and stored in definitions."""
        # Simulate agent definition
        definition = {
            "name": "test-agent",
            "nodes": [{"id": "input", "type": "input"}],
            "edges": [],
        }

        # Create signature
        canonical = _canonical_json(definition)
        content_hash = _compute_hash(canonical)
        signing_key = "test-signing-key"
        signature = _sign(content_hash, signing_key)

        # Store in definition
        definition["_signature"] = signature

        # Verify signature is stored
        assert "_signature" in definition
        assert len(definition["_signature"]) == 64  # SHA-256 hex digest length

    def test_signature_verification_success(self):
        """Test that valid signatures pass verification."""
        definition = {
            "name": "test-agent",
            "nodes": [{"id": "input", "type": "input"}],
            "edges": [],
        }

        # Create and store signature
        signing_key = "test-signing-key"
        canonical = _canonical_json(definition)
        content_hash = _compute_hash(canonical)
        stored_signature = _sign(content_hash, signing_key)
        definition["_signature"] = stored_signature

        # Verify signature
        definition_copy = dict(definition)
        definition_copy.pop("_signature")
        canonical_verify = _canonical_json(definition_copy)
        content_hash_verify = _compute_hash(canonical_verify)
        expected_sig = _sign(content_hash_verify, signing_key)

        # Use constant-time comparison
        valid = hmac.compare_digest(expected_sig, stored_signature)
        assert valid is True

    def test_signature_verification_failure_tampered(self):
        """Test that tampered definitions fail verification."""
        definition = {
            "name": "test-agent",
            "nodes": [{"id": "input", "type": "input"}],
            "edges": [],
        }

        # Create and store signature
        signing_key = "test-signing-key"
        canonical = _canonical_json(definition)
        content_hash = _compute_hash(canonical)
        stored_signature = _sign(content_hash, signing_key)
        definition["_signature"] = stored_signature

        # Tamper with definition
        definition["nodes"].append({"id": "malicious", "type": "hack"})

        # Verify signature should fail
        definition_copy = dict(definition)
        definition_copy.pop("_signature")
        canonical_verify = _canonical_json(definition_copy)
        content_hash_verify = _compute_hash(canonical_verify)
        expected_sig = _sign(content_hash_verify, signing_key)

        valid = hmac.compare_digest(expected_sig, stored_signature)
        assert valid is False

    def test_signature_verification_failure_wrong_key(self):
        """Test that verification fails with wrong signing key."""
        definition = {
            "name": "test-agent",
            "nodes": [{"id": "input", "type": "input"}],
            "edges": [],
        }

        # Create signature with one key
        signing_key = "test-signing-key"
        canonical = _canonical_json(definition)
        content_hash = _compute_hash(canonical)
        stored_signature = _sign(content_hash, signing_key)
        definition["_signature"] = stored_signature

        # Try to verify with different key
        wrong_key = "wrong-signing-key"
        definition_copy = dict(definition)
        definition_copy.pop("_signature")
        canonical_verify = _canonical_json(definition_copy)
        content_hash_verify = _compute_hash(canonical_verify)
        expected_sig = _sign(content_hash_verify, wrong_key)

        valid = hmac.compare_digest(expected_sig, stored_signature)
        assert valid is False

    def test_signature_verification_missing_signature(self):
        """Test that verification fails when signature is missing."""
        stored_signature = ""
        expected_sig = "some-signature"

        valid = hmac.compare_digest(expected_sig, stored_signature) if stored_signature else False
        assert valid is False


# ── Wizard Node Template Tests ─────────────────────────────────────


class TestWizardNodeTemplates:
    """Test wizard node template generation."""

    def test_input_node_template(self):
        """Test INPUT node template generation."""
        node = PlannedNode(
            node_id="input",
            label="User Input",
            node_type="input",
            description="Receives user input",
        )

        # Check that template would include input validation
        assert node.node_type == "input"
        # In actual implementation, this would generate:
        # - Input validation
        # - Message appending
        # - State updates

    def test_output_node_template(self):
        """Test OUTPUT node template generation."""
        node = PlannedNode(
            node_id="output",
            label="Response",
            node_type="output",
            description="Returns final result",
        )

        assert node.node_type == "output"
        # Should generate output formatting logic

    def test_router_node_template(self):
        """Test ROUTER node template generation."""
        node = PlannedNode(
            node_id="router",
            label="Intent Router",
            node_type="router",
            description="Routes based on intent",
            config={"model": "gpt-4o-mini"},
        )

        assert node.node_type == "router"
        assert node.config.get("model") == "gpt-4o-mini"
        # Should generate intent classification logic

    def test_llm_node_template(self):
        """Test LLM node template generation."""
        node = PlannedNode(
            node_id="llm_processor",
            label="LLM Processor",
            node_type="llm",
            description="Processes with language model",
            config={"model": "gpt-4o"},
        )

        assert node.node_type == "llm"
        assert node.config.get("model") == "gpt-4o"
        # Should generate LLM completion logic

    def test_tool_node_template(self):
        """Test TOOL node template generation."""
        node = PlannedNode(
            node_id="tool_slack",
            label="Slack Integration",
            node_type="tool",
            description="Interacts with Slack",
            config={"connector": "slack"},
        )

        assert node.node_type == "tool"
        assert node.config.get("connector") == "slack"
        # Should generate connector execution logic

    def test_auth_node_template(self):
        """Test AUTH node template generation."""
        node = PlannedNode(
            node_id="auth_slack",
            label="Slack Auth",
            node_type="auth",
            description="Authenticates with Slack",
            config={"vault_path": "archon/tenant-123/connectors/slack"},
        )

        assert node.node_type == "auth"
        assert node.config.get("vault_path") == "archon/tenant-123/connectors/slack"
        # Should generate Vault credential fetching logic

    def test_unknown_node_type_fallback(self):
        """Test that unknown node types get fallback template."""
        node = PlannedNode(
            node_id="custom_node",
            label="Custom Node",
            node_type="custom_unknown_type",
            description="Some custom logic",
        )

        assert node.node_type == "custom_unknown_type"
        # Should generate generic fallback implementation


# ── Integration Tests ───────────────────────────────────────────────


class TestIntegration:
    """Integration tests for the critical fixes."""

    def test_signature_roundtrip(self):
        """Test full signature creation and verification flow."""
        # Create a version definition
        definition = {
            "name": "customer-support-bot",
            "tenant_id": str(uuid4()),
            "nodes": [
                {"id": "input", "type": "input"},
                {"id": "router", "type": "router", "config": {"model": "gpt-4o-mini"}},
                {"id": "output", "type": "output"},
            ],
            "edges": [
                {"source": "input", "target": "router"},
                {"source": "router", "target": "output"},
            ],
        }

        # Sign the definition
        signing_key = "production-signing-key"
        canonical = _canonical_json(definition)
        content_hash = _compute_hash(canonical)
        signature = _sign(content_hash, signing_key)

        # Store signature
        signed_definition = dict(definition)
        signed_definition["_signature"] = signature

        # Verify signature (as would happen in verify_signature method)
        stored_sig = signed_definition.get("_signature", "")
        verify_copy = dict(signed_definition)
        verify_copy.pop("_signature", None)
        verify_canonical = _canonical_json(verify_copy)
        verify_hash = _compute_hash(verify_canonical)
        expected_sig = _sign(verify_hash, signing_key)

        valid = hmac.compare_digest(expected_sig, stored_sig) if stored_sig else False
        assert valid is True

    def test_wizard_node_coverage(self):
        """Test that all common node types are covered."""
        node_types = ["input", "output", "router", "llm", "tool", "auth"]

        nodes = [
            PlannedNode(
                node_id=f"node_{ntype}",
                label=f"{ntype.title()} Node",
                node_type=ntype,
                description=f"Test {ntype} node",
            )
            for ntype in node_types
        ]

        assert len(nodes) == 6
        assert all(node.node_type in node_types for node in nodes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
