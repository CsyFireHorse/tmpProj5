import { describe, expect, it } from "vitest";
import { duration, renderSnippet, stringify, summarizeInput } from "./format";

describe("summarizeInput", () => {
  it("prefers the field a reader cares about", () => {
    expect(summarizeInput({ command: ["rg", "-n", "foo"], cwd: "/tmp" })).toBe("rg -n foo");
    expect(summarizeInput({ path: "src/app.ts", encoding: "utf8" })).toBe("src/app.ts");
  });

  it("falls back to compact JSON", () => {
    expect(summarizeInput({ a: 1 })).toBe('{"a":1}');
  });

  it("handles missing input", () => {
    expect(summarizeInput(null)).toBe("");
    expect(summarizeInput(undefined)).toBe("");
  });
});

describe("renderSnippet", () => {
  it("turns the server's markers into highlights", () => {
    expect(renderSnippet("an <<idempotency>> key")).toBe("an <mark>idempotency</mark> key");
  });

  it("escapes markup in the transcript before marking it", () => {
    expect(renderSnippet("<script>alert(1)</script>")).toBe(
      "&lt;script&gt;alert(1)&lt;/script&gt;",
    );
  });
});

describe("duration", () => {
  it("formats sub-second and multi-second gaps", () => {
    expect(duration("2026-09-12T10:00:00Z", "2026-09-12T10:00:00.250Z")).toBe("250ms");
    expect(duration("2026-09-12T10:00:00Z", "2026-09-12T10:00:03Z")).toBe("3.0s");
  });

  it("returns null when an endpoint is missing", () => {
    expect(duration("2026-09-12T10:00:00Z", null)).toBeNull();
  });
});

describe("stringify", () => {
  it("truncates instead of freezing the page on huge payloads", () => {
    expect(stringify("x".repeat(100), 10)).toHaveLength(11);
  });
});
