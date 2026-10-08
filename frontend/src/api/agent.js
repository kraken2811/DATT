/**
 * Agent API client for interacting with the LangGraph DATT AI Agent.
 */

import { apiRequest } from './client';

export async function sendAgentMessage(message, threadId = null, userId = 'operator_ui') {
  return apiRequest('/api/agent/chat', {
    method: 'POST',
    body: {
      message,
      thread_id: threadId,
      user_id: userId,
    },
  });
}

export async function getAgentConversation(threadId, userId = 'operator_ui') {
  if (!threadId) return { messages: [] };
  return apiRequest(`/api/agent/conversations/${encodeURIComponent(threadId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'GET',
    cacheTtlMs: 2000,
  });
}

export async function resetAgentConversation(threadId, userId = 'operator_ui') {
  if (!threadId) return { status: 'success' };
  return apiRequest(`/api/agent/conversations/${encodeURIComponent(threadId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}
