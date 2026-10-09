import { apiRequest, invalidateApiCache } from './client';

export async function sendAgentMessage(message, threadId = null, userId = 'operator_ui') {
  invalidateApiCache('/api/agent/conversations');
  return apiRequest('/api/agent/chat', {
    method: 'POST',
    body: {
      message,
      thread_id: threadId,
      user_id: userId,
    },
  });
}

export async function listAgentConversations(limit = 50, offset = 0, userId = 'operator_ui') {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (userId) query.append('user_id', userId);

  return apiRequest(`/api/agent/conversations?${query.toString()}`, {
    method: 'GET',
    cacheTtlMs: 2000,
  });
}

export async function createAgentConversation(title = null, threadId = null, userId = 'operator_ui') {
  invalidateApiCache('/api/agent/conversations');
  return apiRequest('/api/agent/conversations', {
    method: 'POST',
    body: {
      title,
      thread_id: threadId,
      user_id: userId,
    },
  });
}

export async function getAgentConversation(threadId, userId = 'operator_ui') {
  if (!threadId) return { messages: [] };
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  return apiRequest(`/api/agent/conversations/${encodeURIComponent(threadId)}${query}`, {
    method: 'GET',
    cacheTtlMs: 2000,
  });
}

export async function renameAgentConversation(threadId, title, userId = 'operator_ui') {
  if (!threadId) throw new Error('threadId is required');
  invalidateApiCache('/api/agent/conversations');
  return apiRequest(`/api/agent/conversations/${encodeURIComponent(threadId)}`, {
    method: 'PATCH',
    body: {
      title,
      user_id: userId,
    },
  });
}

export async function deleteAgentConversation(threadId, userId = 'operator_ui') {
  if (!threadId) return { status: 'success' };
  invalidateApiCache('/api/agent/conversations');
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  return apiRequest(`/api/agent/conversations/${encodeURIComponent(threadId)}${query}`, {
    method: 'DELETE',
  });
}

/**
 * Backward compatibility helper: explicitly deletes a conversation thread.
 * NOTE: Starting a new conversation must call createAgentConversation, NOT delete!
 */
export async function resetAgentConversation(threadId, userId = 'operator_ui') {
  return deleteAgentConversation(threadId, userId);
}
