import { describe, expect, it } from "vitest";
import { getConversationLabel } from "@/lib/conversationLabel";

describe("getConversationLabel", () => {
  it('returns "New conversation" when neither plan nor messages present', () => {
    expect(getConversationLabel({})).toBe("New conversation");
  });

  it('returns "New conversation" when arrays are empty', () => {
    expect(getConversationLabel({ business_plans: [], messages: [] })).toBe(
      "New conversation"
    );
  });

  it("returns plan content when present", () => {
    expect(
      getConversationLabel({
        business_plans: [{ content: "Coffee shop business plan" }],
      })
    ).toBe("Coffee shop business plan");
  });

  it("truncates plan content longer than 40 chars", () => {
    const long = "x".repeat(60);
    expect(
      getConversationLabel({ business_plans: [{ content: long }] })
    ).toBe(`${"x".repeat(40)}...`);
  });

  it("falls back to first user message when no plan", () => {
    expect(
      getConversationLabel({
        messages: [
          { role: "user", content: "I want to start a coffee shop" },
          { role: "assistant", content: "What problem...?" },
        ],
      })
    ).toBe("I want to start a coffee shop");
  });

  it("ignores assistant messages when picking the first user message", () => {
    expect(
      getConversationLabel({
        messages: [
          { role: "assistant", content: "AI greeting first" },
          { role: "user", content: "user reply" },
        ],
      })
    ).toBe("user reply");
  });

  it("truncates the user message when longer than 40 chars", () => {
    const long = "u".repeat(60);
    expect(
      getConversationLabel({ messages: [{ role: "user", content: long }] })
    ).toBe(`${"u".repeat(40)}...`);
  });

  it("prefers business plan over messages when both exist", () => {
    expect(
      getConversationLabel({
        business_plans: [{ content: "Plan wins" }],
        messages: [{ role: "user", content: "User message ignored" }],
      })
    ).toBe("Plan wins");
  });

  it("ignores empty plan content and falls through to messages", () => {
    expect(
      getConversationLabel({
        business_plans: [{ content: "" }],
        messages: [{ role: "user", content: "Used instead" }],
      })
    ).toBe("Used instead");
  });

  it('returns "New conversation" when only assistant messages exist', () => {
    expect(
      getConversationLabel({
        messages: [{ role: "assistant", content: "Hello" }],
      })
    ).toBe("New conversation");
  });

  it("preserves messages at exactly 40 chars without truncation", () => {
    const exact40 = "x".repeat(40);
    expect(
      getConversationLabel({ messages: [{ role: "user", content: exact40 }] })
    ).toBe(exact40);
  });
});
