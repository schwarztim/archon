/**
 * Tests for EventTimeline.
 *
 * Coverage
 *  - Renders supplied events grouped/filtered by phase
 *  - Filter chips toggle event_type visibility
 *  - chain_verified=false shows the warning badge
 *  - chain_verified=true shows the verified badge
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

import { EventTimeline } from "@/components/executions/EventTimeline";
import type { WorkflowRunEvent } from "@/types/events";

function makeEvent(
  i: number,
  event_type: WorkflowRunEvent["event_type"],
  step_id: string | null = null,
): WorkflowRunEvent {
  return {
    id: `ev-${i}`,
    run_id: "run-1",
    sequence: i,
    event_type,
    payload: { idx: i },
    tenant_id: null,
    correlation_id: null,
    span_id: null,
    step_id,
    prev_hash: i === 0 ? null : `hash-${i - 1}`,
    current_hash: `hash-${i}`,
    created_at: new Date(Date.now() + i * 1000).toISOString(),
  };
}

describe("EventTimeline", () => {
  const fixture: WorkflowRunEvent[] = [
    makeEvent(0, "run.created"),
    makeEvent(1, "run.started"),
    makeEvent(2, "step.started", "step-a"),
    makeEvent(3, "step.completed", "step-a"),
    makeEvent(4, "run.completed"),
  ];

  it("renders all supplied events by default", () => {
    render(<EventTimeline events={fixture} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(fixture.length);
    expect(screen.getAllByText(/run.created/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/step.completed/i).length).toBeGreaterThan(0);
  });

  it("groups by phase when the Step toggle is clicked", () => {
    render(<EventTimeline events={fixture} />);

    fireEvent.click(screen.getByText("Step"));

    // After filter, only step.* events remain
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    items.forEach((li) => {
      const eventType = li.getAttribute("data-event-type") ?? "";
      expect(eventType.startsWith("step.")).toBe(true);
    });
  });

  it("filter chips narrow the visible events", () => {
    render(<EventTimeline events={fixture} />);

    // Toggle the run.created chip — only run.created events should remain
    const chip = screen.getAllByText("run.created").find(
      (el) => el.tagName.toLowerCase() === "button",
    );
    expect(chip).toBeDefined();
    if (chip) fireEvent.click(chip);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]?.getAttribute("data-event-type")).toBe("run.created");
  });

  it("shows the chain-verified badge when chainVerified is true", () => {
    render(<EventTimeline events={fixture} chainVerified={true} />);
    expect(screen.getByTestId("chain-verified")).toBeInTheDocument();
    expect(screen.queryByTestId("chain-broken")).toBeNull();
  });

  it("shows the warning badge when chainVerified is false", () => {
    render(<EventTimeline events={fixture} chainVerified={false} />);
    expect(screen.getByTestId("chain-broken")).toBeInTheDocument();
    expect(screen.queryByTestId("chain-verified")).toBeNull();
  });

  it("renders no chain badge when chainVerified is null", () => {
    render(<EventTimeline events={fixture} chainVerified={null} />);
    expect(screen.queryByTestId("chain-verified")).toBeNull();
    expect(screen.queryByTestId("chain-broken")).toBeNull();
  });

  it("Replay button calls onReplay with the step_id", () => {
    const onReplay = vi.fn();
    render(
      <EventTimeline
        events={fixture}
        allowReplay
        onReplay={onReplay}
      />,
    );

    const stepEvent = screen
      .getAllByRole("listitem")
      .find((li) => li.getAttribute("data-step-id") === "step-a");
    expect(stepEvent).toBeDefined();
    if (!stepEvent) return;

    const replayBtn = within(stepEvent).getByRole("button", {
      name: /replay step step-a/i,
    });
    fireEvent.click(replayBtn);
    expect(onReplay).toHaveBeenCalledWith("step-a");
  });
});
