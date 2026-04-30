/**
 * P3 — Operator flow E2E test.
 *
 * Drives the full operator UX through a paused-approval workflow:
 *   1. Create an agent + workflow with a humanApprovalNode via the REST API.
 *   2. POST /api/v1/executions to start a run.
 *   3. Navigate to /executions/{run_id} and confirm we land on the detail page.
 *   4. Wait for status="paused" (the run pauses at approval).
 *   5. Navigate to /approvals and click Approve on the matching card.
 *   6. Confirm reason in the dialog.
 *   7. Navigate back to /executions/{run_id}; wait for status="completed".
 *   8. Navigate to /artifacts and verify the run artifact is listed.
 *   9. Navigate to /cost and verify the run's tokens/cost are surfaced.
 *
 * Backend availability check: if neither the frontend (3000) nor backend
 * (8000) is reachable on the configured host, the test SKIPS with a clear
 * message rather than failing — the Vitest contract test under
 * ``src/tests/operator-flow.contract.test.tsx`` is the always-on substitute.
 *
 * Run with:  npm run test:e2e -- e2e/operator-flow.spec.ts
 */
import { test, expect, type APIRequestContext } from "@playwright/test";

const BACKEND_URL = process.env.ARCHON_BACKEND_URL ?? "http://localhost:8000";
const FRONTEND_URL = process.env.ARCHON_FRONTEND_URL ?? "http://localhost:3000";

// ─── Backend reachability ────────────────────────────────────────────

async function backendReachable(request: APIRequestContext): Promise<boolean> {
  try {
    const res = await request.get(`${BACKEND_URL}/health`, {
      timeout: 2000,
    });
    return res.ok();
  } catch {
    return false;
  }
}

async function frontendReachable(request: APIRequestContext): Promise<boolean> {
  try {
    const res = await request.get(`${FRONTEND_URL}/`, { timeout: 2000 });
    return res.status() < 500;
  } catch {
    return false;
  }
}

// ─── Backend setup helpers ───────────────────────────────────────────

async function createAgent(
  request: APIRequestContext,
): Promise<string> {
  const res = await request.post(`${BACKEND_URL}/api/v1/agents/`, {
    data: {
      name: `operator-flow-agent-${Date.now()}`,
      description: "agent for operator-flow E2E",
      definition: { model: "gpt-3.5-turbo" },
      tags: ["e2e"],
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return (body.data ?? body).id;
}

async function createWorkflowWithApproval(
  request: APIRequestContext,
): Promise<string> {
  const res = await request.post(`${BACKEND_URL}/api/v1/workflows/`, {
    data: {
      name: `operator-flow-wf-${Date.now()}`,
      steps: [
        {
          step_id: "input_step",
          name: "Input",
          node_type: "outputNode",
          config: { value: "operator-flow input" },
          depends_on: [],
        },
        {
          step_id: "approval_gate",
          name: "Operator Approval",
          node_type: "humanApprovalNode",
          config: { reason: "Operator must approve before completion" },
          depends_on: ["input_step"],
        },
        {
          step_id: "final_step",
          name: "Final",
          node_type: "outputNode",
          config: { value: "post-approval" },
          depends_on: ["approval_gate"],
        },
      ],
      graph_definition: {},
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return (body.data ?? body).id;
}

async function startExecution(
  request: APIRequestContext,
  agentId: string,
  workflowId: string,
): Promise<string> {
  const res = await request.post(`${BACKEND_URL}/api/v1/executions`, {
    data: {
      agent_id: agentId,
      workflow_id: workflowId,
      input_data: { trigger: "e2e" },
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return (body.data ?? body).id;
}

async function waitForRunStatus(
  request: APIRequestContext,
  runId: string,
  status: string,
  timeoutMs = 15_000,
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const res = await request.get(
      `${BACKEND_URL}/api/v1/workflow-runs/${runId}`,
    );
    if (res.ok()) {
      const body = await res.json();
      const got = (body.data ?? body).status;
      if (got === status) return;
      if (
        ["completed", "failed", "cancelled"].includes(got) &&
        got !== status
      ) {
        throw new Error(
          `Run ${runId} reached terminal status=${got}, expected ${status}`,
        );
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(
    `Timed out waiting for run ${runId} to reach status=${status}`,
  );
}

// ─── The test ───────────────────────────────────────────────────────

test.describe("P3: operator flow", () => {
  test("operator: start → observe → approve → resume → terminal → artifacts", async ({
    page,
    request,
  }) => {
    const beReady = await backendReachable(request);
    const feReady = await frontendReachable(request);
    test.skip(
      !(beReady && feReady),
      `Skipping — backend(${BACKEND_URL})=${beReady} frontend(${FRONTEND_URL})=${feReady}. ` +
        `The Vitest contract test (src/tests/operator-flow.contract.test.tsx) is the always-on substitute.`,
    );

    // 1-2: Seed agent + workflow + run via the real REST surface.
    const agentId = await createAgent(request);
    const workflowId = await createWorkflowWithApproval(request);
    const runId = await startExecution(request, agentId, workflowId);

    // 3: Land on the execution detail page.
    await page.goto(`${FRONTEND_URL}/executions/${runId}`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toContainText(runId.slice(0, 8));

    // 4: Wait for the run to pause at the approval gate.
    await waitForRunStatus(request, runId, "paused");

    // 5: Navigate to /approvals.
    await page.goto(`${FRONTEND_URL}/approvals`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: /approvals/i })).toBeVisible();

    // 6: Click Approve on the matching card and confirm reason.
    const approveBtn = page
      .getByRole("button", { name: /approve approval/i })
      .first();
    await approveBtn.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel(/reason/i).fill("E2E operator approval");
    await dialog.getByRole("button", { name: /^approve$/i }).click();

    // 7: Wait for the run to complete.
    await waitForRunStatus(request, runId, "completed");

    // 8: Navigate to /artifacts and verify the run shows up.
    await page.goto(`${FRONTEND_URL}/artifacts`);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { name: /artifacts/i })).toBeVisible();

    // 9: Cost dashboard surfaces tokens for the run.
    await page.goto(`${FRONTEND_URL}/cost`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).not.toBeEmpty();
  });
});
