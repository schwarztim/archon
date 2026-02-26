import { describe, it, expect } from "vitest";
import { cn, generateNodeId } from "@/utils/cn";

describe("cn (class merge utility)", () => {
  it("merges multiple class strings", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("deduplicates conflicting tailwind classes (last wins)", () => {
    const result = cn("bg-red-500", "bg-blue-500");
    expect(result).toBe("bg-blue-500");
  });

  it("ignores falsy values", () => {
    expect(cn("foo", false && "bar", null, undefined, "baz")).toBe("foo baz");
  });

  it("handles conditional object syntax", () => {
    expect(cn({ "text-white": true, "text-black": false })).toBe("text-white");
  });

  it("handles empty inputs", () => {
    expect(cn()).toBe("");
    expect(cn("")).toBe("");
  });

  it("merges array inputs", () => {
    expect(cn(["foo", "bar"])).toBe("foo bar");
  });

  it("preserves text-white when no conflicting text class follows", () => {
    const result = cn("text-white", "font-medium");
    expect(result).toContain("text-white");
  });

  it("preserves text-gray-400 when no conflicting text class follows", () => {
    const result = cn("text-gray-400", "font-medium");
    expect(result).toContain("text-gray-400");
  });
});

describe("generateNodeId", () => {
  it("generates a string starting with node_", () => {
    const id = generateNodeId();
    expect(id).toMatch(/^node_\d+_[a-z0-9]+$/);
  });

  it("generates unique IDs across calls", () => {
    const ids = new Set(Array.from({ length: 20 }, () => generateNodeId()));
    expect(ids.size).toBe(20);
  });
});
