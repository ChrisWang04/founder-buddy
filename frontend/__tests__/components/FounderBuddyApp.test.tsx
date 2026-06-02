/**
 * Component tests for FounderBuddyApp.
 *
 * Focus: the two highest-value error paths that we explicitly fixed during
 * development — handleLoadConversation's 404 path and handleSendMessage's
 * error path (non-2xx /chat/stream response).
 *
 * Heavy mocking is required because the component depends on Supabase auth,
 * next/navigation, and the backend API. We mock all three.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

// ─── Mocks (must come before importing the component) ────────────────────────

const supabaseMockState = {
  conversations: [] as Array<{
    id: number;
    user_id: string;
    session_id: string;
    created_at: string;
    business_plans?: { content: string }[];
    messages?: { content: string; role: string }[];
  }>,
};

vi.mock("@/lib/supabase", () => ({
  createClient: () => ({
    auth: {
      getUser: async () => ({
        data: { user: { id: "u1", email: "x@y.z" } },
      }),
      getSession: async () => ({
        data: { session: { access_token: "fake-token" } },
      }),
      signOut: async () => ({}),
    },
    from: () => ({
      select: () => ({
        eq: () => ({
          order: () => ({
            limit: async () => ({ data: supabaseMockState.conversations }),
          }),
        }),
      }),
      delete: () => ({ eq: async () => ({}) }),
    }),
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import FounderBuddyApp from "@/app/components/FounderBuddyApp";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockFetchSequence(responses: Array<Partial<Response>>) {
  const fn = vi.fn();
  for (const r of responses) {
    fn.mockResolvedValueOnce(r as Response);
  }
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

function jsonResponse(body: unknown, status = 200): Partial<Response> {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("FounderBuddyApp", () => {
  beforeEach(() => {
    supabaseMockState.conversations = [];
    vi.restoreAllMocks();
  });

  it("shows the unresumable-session notice when /chat/state returns 404", async () => {
    // Seed one past conversation so the list renders something to click
    supabaseMockState.conversations = [
      {
        id: 1,
        user_id: "u1",
        session_id: "old-session",
        created_at: "2026-01-01T00:00:00Z",
        business_plans: [],
      },
    ];

    // /chat/messages returns OK with no messages, /chat/state returns 404
    mockFetchSequence([
      jsonResponse({ messages: [] }, 200),     // /chat/messages
      jsonResponse({ detail: "Not found" }, 404), // /chat/state
    ]);

    render(<FounderBuddyApp />);

    // Wait for the conversation to appear in the sidebar
    const convoButton = await screen.findByText("New conversation");
    await act(async () => {
      fireEvent.click(convoButton);
    });

    // The notice should appear in the chat
    await waitFor(() =>
      expect(
        screen.getByText(
          /This conversation can't be resumed.*older session/i
        )
      ).toBeInTheDocument()
    );
  });

  it("shows 'Sorry, there was an error' when /chat/stream returns non-OK", async () => {
    // Start with no past conversations
    supabaseMockState.conversations = [];

    // First send → /chat/start succeeds and returns a session
    // Second send → /chat/stream returns 500
    mockFetchSequence([
      jsonResponse(
        {
          session_id: "s-1",
          agent_message: "Welcome question?",
          is_done: false,
          section_status: {},
          business_plan: null,
        },
        200
      ),
      { ok: false, status: 500, body: null } as Partial<Response>,
    ]);

    render(<FounderBuddyApp />);

    // Wait for initial render
    const input = await screen.findByPlaceholderText(/Describe your startup/);
    const form = input.closest("form")!;

    // First message via /chat/start
    fireEvent.change(input, { target: { value: "coffee shop" } });
    await act(async () => {
      fireEvent.submit(form);
    });

    // Welcome question should appear
    await waitFor(() =>
      expect(screen.getByText("Welcome question?")).toBeInTheDocument()
    );

    // Second message via /chat/stream — backend returns 500
    fireEvent.change(input, { target: { value: "another message" } });
    await act(async () => {
      fireEvent.submit(form);
    });

    await waitFor(() =>
      expect(
        screen.getByText(/Sorry, there was an error/i)
      ).toBeInTheDocument()
    );
  });
});
