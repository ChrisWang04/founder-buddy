import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the Supabase client BEFORE importing the component
const mockLimit = vi.fn();

vi.mock("@/lib/supabase", () => ({
  createClient: () => ({
    auth: {
      getUser: async () => ({ data: { user: { id: "test-user" } } }),
    },
    from: () => ({
      select: () => ({
        eq: () => ({
          order: () => ({
            limit: mockLimit,
          }),
        }),
      }),
      delete: () => ({ eq: async () => ({}) }),
    }),
  }),
}));

import ConversationList from "@/app/components/ConversationList";

describe("ConversationList", () => {
  beforeEach(() => {
    mockLimit.mockReset();
  });

  it('shows "No past conversations" when list is empty', async () => {
    mockLimit.mockResolvedValueOnce({ data: [] });
    render(
      <ConversationList
        onNewConversation={() => {}}
        onLoadConversation={() => {}}
      />
    );
    await waitFor(() =>
      expect(screen.getByText("No past conversations")).toBeInTheDocument()
    );
  });

  it("renders business plan content as the label when present", async () => {
    mockLimit.mockResolvedValueOnce({
      data: [
        {
          id: 1,
          user_id: "test-user",
          session_id: "s1",
          created_at: "2026-01-01T00:00:00Z",
          business_plans: [{ content: "Coffee shop plan" }],
          messages: [{ role: "user", content: "ignored" }],
        },
      ],
    });

    render(
      <ConversationList
        onNewConversation={() => {}}
        onLoadConversation={() => {}}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Coffee shop plan")).toBeInTheDocument()
    );
  });

  it("falls back to first user message when no BP exists", async () => {
    mockLimit.mockResolvedValueOnce({
      data: [
        {
          id: 2,
          user_id: "test-user",
          session_id: "s2",
          created_at: "2026-01-01T00:00:00Z",
          messages: [
            { role: "assistant", content: "AI greeting" },
            { role: "user", content: "I want to start a bakery" },
          ],
        },
      ],
    });

    render(
      <ConversationList
        onNewConversation={() => {}}
        onLoadConversation={() => {}}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("I want to start a bakery")).toBeInTheDocument()
    );
  });

  it("re-fetches when refreshKey changes", async () => {
    mockLimit
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({
        data: [
          {
            id: 3,
            user_id: "test-user",
            session_id: "s3",
            created_at: "2026-01-01T00:00:00Z",
            business_plans: [{ content: "newly appeared" }],
          },
        ],
      });

    const { rerender } = render(
      <ConversationList
        onNewConversation={() => {}}
        onLoadConversation={() => {}}
        refreshKey={0}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("No past conversations")).toBeInTheDocument()
    );

    rerender(
      <ConversationList
        onNewConversation={() => {}}
        onLoadConversation={() => {}}
        refreshKey={1}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("newly appeared")).toBeInTheDocument()
    );
  });
});
