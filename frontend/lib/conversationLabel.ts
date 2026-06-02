/**
 * Derive a sidebar label for a conversation row.
 *
 * Priority: business plan content → first user message → fallback string.
 * Truncated to 40 chars with an ellipsis.
 */

export interface ConversationLabelInput {
  business_plans?: { content: string }[];
  messages?: { content: string; role: string }[];
}

const MAX_LABEL_CHARS = 40;

function truncate(text: string): string {
  return text.length > MAX_LABEL_CHARS ? `${text.slice(0, MAX_LABEL_CHARS)}...` : text;
}

export function getConversationLabel(conversation: ConversationLabelInput): string {
  const planContent = conversation.business_plans?.[0]?.content;
  if (planContent) return truncate(planContent);

  const firstUserMessage = conversation.messages?.find((m) => m.role === "user");
  if (firstUserMessage) return truncate(firstUserMessage.content);

  return "New conversation";
}
