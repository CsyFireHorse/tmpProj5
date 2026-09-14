import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Part } from "../api/types";
import { PartView } from "./Parts";

function renderPart(part: Part) {
  return render(<PartView part={part} />);
}

describe("PartView", () => {
  it("renders text as markdown", () => {
    renderPart({ id: "p1", type: "text", text: "**bold** answer", locator: null, raw: null });
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });

  it("collapses a tool call to a one-line summary", () => {
    renderPart({
      id: "p2",
      type: "tool",
      name: "shell",
      call_id: "c1",
      input: { command: ["pytest", "-q"] },
      output: "1 failed",
      status: "error",
      error: null,
      title: null,
      started_at: null,
      ended_at: null,
      metadata: null,
      locator: null,
      raw: null,
    });
    expect(screen.getByText("shell")).toBeInTheDocument();
    expect(screen.getByText("pytest -q")).toBeInTheDocument();
    // Output stays hidden until the row is expanded.
    expect(screen.queryByText("1 failed")).not.toBeInTheDocument();
  });

  it("keeps an unrecognized record visible as raw JSON", () => {
    renderPart({
      id: "p3",
      type: "unknown",
      kind: "future_item_kind",
      data: { note: "added in a later release" },
      locator: null,
      raw: null,
    });
    expect(screen.getByText("future_item_kind")).toBeInTheDocument();
    expect(screen.getByText(/shown as raw JSON/)).toBeInTheDocument();
  });

  it("counts added and removed lines in a diff", () => {
    renderPart({
      id: "p4",
      type: "patch",
      files: [],
      unified_diff: "--- a/x\n+++ b/x\n@@\n+added\n-removed\n context",
      locator: null,
      raw: null,
    });
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("−1")).toBeInTheDocument();
  });
});
