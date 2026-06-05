/**
 * SSE buffer parsing — extracted from FounderBuddyApp's processBuffer so it
 * can be tested without React state.
 *
 * The wire format is the standard `data: <json>\n\n` per event. We split on
 * `\n\n`, strip the `data: ` prefix, and JSON.parse the payload. The final
 * fragment (possibly an incomplete frame) is returned as `remainder` for the
 * caller to prepend to the next buffer.
 */

export type SSEEvent =
  | { type: "token"; content: string }
  | { type: "bp_token"; content: string }
  | { type: "done"; [k: string]: unknown }
  | { type: "error"; detail?: string };

export interface SSEParseResult {
  events: SSEEvent[];
  remainder: string;
}

export function parseSSEBuffer(buffer: string): SSEParseResult {
  const parts = buffer.split("\n\n");
  const remainder = parts.pop() ?? "";
  const events: SSEEvent[] = [];

  for (const part of parts) {
    const line = part.trim();
    if (!line.startsWith("data: ")) continue;
    try {
      events.push(JSON.parse(line.slice(6)));
    } catch (e) {
      // Malformed JSON is skipped (matches frontend behavior). Anything that
      // isn't a SyntaxError propagates.
      if (e instanceof SyntaxError) continue;
      throw e;
    }
  }

  return { events, remainder };
}
