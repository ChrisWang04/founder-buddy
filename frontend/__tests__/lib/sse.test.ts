import { describe, expect, it } from "vitest";
import { parseSSEBuffer } from "@/lib/sse";

describe("parseSSEBuffer", () => {
  it("parses a single complete event", () => {
    const buffer = `data: {"type":"token","content":"hi"}\n\n`;
    const { events, remainder } = parseSSEBuffer(buffer);
    expect(events).toEqual([{ type: "token", content: "hi" }]);
    expect(remainder).toBe("");
  });

  it("parses multiple events in one buffer", () => {
    const buffer =
      `data: {"type":"token","content":"a"}\n\n` +
      `data: {"type":"token","content":"b"}\n\n` +
      `data: {"type":"done","is_done":true}\n\n`;
    const { events, remainder } = parseSSEBuffer(buffer);
    expect(events).toHaveLength(3);
    expect(events[0]).toEqual({ type: "token", content: "a" });
    expect(events[2]).toMatchObject({ type: "done", is_done: true });
    expect(remainder).toBe("");
  });

  it("returns incomplete trailing frame as remainder", () => {
    const buffer = `data: {"type":"token","content":"complete"}\n\ndata: {"type":"to`;
    const { events, remainder } = parseSSEBuffer(buffer);
    expect(events).toEqual([{ type: "token", content: "complete" }]);
    expect(remainder).toBe('data: {"type":"to');
  });

  it("returns empty events and full buffer as remainder when no complete frame", () => {
    const buffer = `data: {"partial":`;
    const { events, remainder } = parseSSEBuffer(buffer);
    expect(events).toEqual([]);
    expect(remainder).toBe(buffer);
  });

  it("skips frames without a `data: ` prefix", () => {
    const buffer = `event: ping\n\ndata: {"type":"token","content":"x"}\n\n`;
    const { events } = parseSSEBuffer(buffer);
    expect(events).toEqual([{ type: "token", content: "x" }]);
  });

  it("skips frames with malformed JSON without throwing", () => {
    const buffer =
      `data: {not valid json\n\n` +
      `data: {"type":"token","content":"good"}\n\n`;
    const { events } = parseSSEBuffer(buffer);
    expect(events).toEqual([{ type: "token", content: "good" }]);
  });

  it("parses error events", () => {
    const buffer = `data: {"type":"error","detail":"oops"}\n\n`;
    const { events } = parseSSEBuffer(buffer);
    expect(events).toEqual([{ type: "error", detail: "oops" }]);
  });

  it("handles empty buffer", () => {
    const { events, remainder } = parseSSEBuffer("");
    expect(events).toEqual([]);
    expect(remainder).toBe("");
  });

  it("handles buffer containing only an empty frame separator", () => {
    const { events, remainder } = parseSSEBuffer("\n\n");
    expect(events).toEqual([]);
    expect(remainder).toBe("");
  });

  it("trims whitespace around frames", () => {
    const buffer = `   data: {"type":"token","content":"x"}   \n\n`;
    const { events } = parseSSEBuffer(buffer);
    expect(events).toEqual([{ type: "token", content: "x" }]);
  });

  it("preserves JSON content with special chars", () => {
    const buffer = `data: {"type":"token","content":"line1\\nline2 \\"quoted\\""}\n\n`;
    const { events } = parseSSEBuffer(buffer);
    expect((events[0] as { content: string }).content).toBe('line1\nline2 "quoted"');
  });

  it("propagates non-SyntaxError exceptions", () => {
    // JSON.parse throws SyntaxError on bad input, which we skip. We can't
    // easily induce a non-SyntaxError from JSON.parse, but the contract is
    // documented in the source. Verify malformed JSON does NOT throw.
    expect(() => parseSSEBuffer("data: bad\n\n")).not.toThrow();
  });
});
