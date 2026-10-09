import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Header } from '../components/Header';
import { AgentMessageContent } from '../components/AgentMessageContent';
import {
  sendAgentMessage,
  listAgentConversations,
  createAgentConversation,
  getAgentConversation,
  renameAgentConversation,
  deleteAgentConversation,
} from '../api/agent';
import { useToast } from '../context/ToastContext';
import {
  Bot,
  User,
  Send,
  Trash2,
  Sparkles,
  BookOpen,
  Camera,
  Activity,
  Shield,
  FileText,
  AlertCircle,
  HelpCircle,
  Layers,
  ArrowRight,
  Plus,
  MessageSquare,
  Edit2,
  Check,
  X,
  PanelLeftClose,
  PanelLeft,
  Clock,
  RefreshCw,
  Search,
} from 'lucide-react';

const QUICK_PROMPTS = [
  {
    icon: Camera,
    label: 'Kiểm tra Camera',
    prompt: 'Kiểm tra trạng thái hoạt động của camera_01',
  },
  {
    icon: Activity,
    label: 'Thống kê 24h',
    prompt: 'Cho tôi xem thống kê phân loại phương tiện và lưu lượng trong 24 giờ qua',
  },
  {
    icon: Shield,
    label: 'Danh sách theo dõi',
    prompt: 'Tra cứu danh sách theo dõi biển số xe và đối tượng khuôn mặt',
  },
  {
    icon: BookOpen,
    label: 'Tài liệu khắc phục',
    prompt: 'Theo tài liệu hướng dẫn, cách khắc phục khi camera bị offline hoặc mất kết nối?',
  },
];

function formatConversationTime(isoString) {
  if (!isoString) return '';
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return '';
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    if (diffMs < 0) return 'Vừa xong';
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Vừa xong';
    if (diffMins < 60) return `${diffMins} phút trước`;
    if (diffHours < 24) return `${diffHours} giờ trước`;
    if (diffDays === 1) return 'Hôm qua';
    if (diffDays < 7) return `${diffDays} ngày trước`;
    return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
  } catch {
    return '';
  }
}

export function AgentPage() {
  const { showToast } = useToast();

  // Conversation list & active thread state
  const [conversations, setConversations] = useState([]);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    if (typeof window !== 'undefined' && window.innerWidth < 900) {
      return false;
    }
    return true;
  });

  // Active chat state
  const [threadId, setThreadId] = useState(() => {
    return localStorage.getItem('datt_agent_thread_id') || `thread_${Date.now()}`;
  });
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [apiStatus, setApiStatus] = useState('connecting');

  // Inline rename & delete modal state
  const [editingThreadId, setEditingThreadId] = useState(null);
  const [editTitleInput, setEditTitleInput] = useState('');
  const [deleteModalConv, setDeleteModalConv] = useState(null);
  const [deleting, setDeleting] = useState(false);

  // Ref tracking to prevent race conditions during rapid conversation switching
  const messagesEndRef = useRef(null);
  const activeThreadRef = useRef(threadId);
  const fetchSeqRef = useRef(0);

  useEffect(() => {
    activeThreadRef.current = threadId;
  }, [threadId]);

  // Sync thread_id to localStorage for page reload continuity
  useEffect(() => {
    if (threadId) {
      localStorage.setItem('datt_agent_thread_id', threadId);
    }
  }, [threadId]);

  // Load conversation registry from PostgreSQL
  const loadConversationsList = useCallback(async () => {
    setLoadingConversations(true);
    try {
      const resp = await listAgentConversations(50, 0);
      if (resp && resp.status === 'success' && Array.isArray(resp.conversations)) {
        setConversations(resp.conversations);
        return resp.conversations;
      }
    } catch (err) {
      console.warn('Failed to load conversation registry:', err);
    } finally {
      setLoadingConversations(false);
    }
    return [];
  }, []);

  // Initial load of conversation registry
  useEffect(() => {
    loadConversationsList();
  }, [loadConversationsList]);

  // Load conversation history on mount or thread switch
  useEffect(() => {
    let active = true;
    const currentSeq = ++fetchSeqRef.current;

    async function loadHistory() {
      if (!threadId) return;
      setLoadingHistory(true);
      try {
        const resp = await getAgentConversation(threadId);
        if (!active || fetchSeqRef.current !== currentSeq) return;
        setApiStatus(resp?.status === 'error' ? 'error' : 'connected');
        if (resp && resp.messages && resp.messages.length > 0) {
          const restored = resp.messages
            .filter((m) => m.type === 'human' || m.type === 'ai' || m.type === 'AIMessage' || m.type === 'HumanMessage')
            .map((m, idx) => ({
              id: m.id || `restored_${idx}`,
              role: (m.type === 'human' || m.type === 'HumanMessage') ? 'user' : 'assistant',
              content: m.content,
              timestamp: '',
              sources: [],
              toolsCalled: m.tool_calls ? m.tool_calls.map((tc) => tc.name || tc.function?.name || 'tool') : [],
            }));
          if (restored.length > 0) {
            setMessages(restored);
            return;
          }
        }
      } catch (err) {
        if (active && fetchSeqRef.current === currentSeq) {
          setApiStatus('error');
          console.warn('Failed to restore conversation history:', err);
        }
      } finally {
        if (active && fetchSeqRef.current === currentSeq) {
          setLoadingHistory(false);
        }
      }

      if (active && fetchSeqRef.current === currentSeq) {
        setMessages([
          {
            id: 'welcome',
            role: 'assistant',
            content:
              'Xin chào! Tôi là Trợ lý AI Vận hành Hệ thống DATT (DATT AI Agent). Tôi có thể hỗ trợ bạn kiểm tra camera trực tuyến, tra cứu sự kiện, thống kê lưu lượng xe, theo dõi biển số/khuôn mặt, và giải đáp tài liệu hướng dẫn vận hành.',
            sources: [],
            toolsCalled: [],
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
      }
    }

    loadHistory();
    return () => {
      active = false;
    };
  }, [threadId]);

  // Auto scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  // Handle sending message
  const handleSendMessage = async (textToSend) => {
    const text = (textToSend || inputValue).trim();
    if (!text || loading) return;

    const currentThreadId = threadId;
    const userMsg = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setLoading(true);

    try {
      const resp = await sendAgentMessage(text, currentThreadId);
      setApiStatus('connected');
      if (activeThreadRef.current === currentThreadId) {
        if (resp && resp.status === 'success') {
          const botMsg = {
            id: `bot_${Date.now()}`,
            role: 'assistant',
            content: resp.reply,
            sources: resp.sources || [],
            toolsCalled: [...new Set(resp.tools_called || [])],
            timestamp: new Date().toLocaleTimeString(),
          };
          setMessages((prev) => [...prev, botMsg]);
        } else {
          const errorMsg = {
            id: `err_${Date.now()}`,
            role: 'assistant',
            isError: true,
            content: resp?.reply || 'Hệ thống gặp sự cố khi xử lý tin nhắn. Vui lòng thử lại.',
            timestamp: new Date().toLocaleTimeString(),
          };
          setMessages((prev) => [...prev, errorMsg]);
          showToast(resp?.reply || 'Không thể nhận phản hồi từ AI Agent', 'error');
        }
      }
      // Refresh conversation registry in background to reflect updated title and timestamps
      loadConversationsList();
    } catch (err) {
      setApiStatus('error');
      if (activeThreadRef.current === currentThreadId) {
        const errorMsg = {
          id: `err_${Date.now()}`,
          role: 'assistant',
          isError: true,
          content: `Không thể kết nối đến AI Agent: ${err.message || err}`,
          timestamp: new Date().toLocaleTimeString(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      }
      showToast(err.message || 'Lỗi mạng khi kết nối AI Agent', 'error');
    } finally {
      setLoading(false);
    }
  };

  // Create a new conversation: MUST PRESERVE OLD THREADS (NEVER CALL DELETE!)
  const handleCreateNewConversation = async () => {
    if (loading) return;
    try {
      const resp = await createAgentConversation();
      if (resp && resp.status === 'success' && resp.conversation) {
        const newConv = resp.conversation;
        setConversations((prev) => [newConv, ...prev.filter((c) => c.thread_id !== newConv.thread_id)]);
        setThreadId(newConv.thread_id);
        setMessages([
          {
            id: 'welcome_new',
            role: 'assistant',
            content: 'Xin chào! Cuộc trò chuyện mới đã sẵn sàng. Tôi có thể hỗ trợ gì cho bạn?',
            sources: [],
            toolsCalled: [],
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
        showToast('Đã tạo cuộc trò chuyện mới.', 'info');
      } else {
        const fallbackThread = `thread_${Date.now()}`;
        setThreadId(fallbackThread);
        setMessages([
          {
            id: 'welcome_new',
            role: 'assistant',
            content: 'Cuộc trò chuyện mới đã sẵn sàng. Tôi có thể hỗ trợ gì cho bạn?',
            sources: [],
            toolsCalled: [],
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
        showToast('Đã tạo phiên trò chuyện mới.', 'info');
      }
    } catch (err) {
      console.warn('Failed to register new conversation:', err);
      const fallbackThread = `thread_${Date.now()}`;
      setThreadId(fallbackThread);
      setMessages([
        {
          id: 'welcome_new',
          role: 'assistant',
          content: 'Cuộc trò chuyện mới đã sẵn sàng. Tôi có thể hỗ trợ gì cho bạn?',
          sources: [],
          toolsCalled: [],
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
      showToast('Đã tạo phiên trò chuyện mới.', 'info');
    }
  };

  // Switch conversation
  const handleSelectConversation = (selectedThreadId) => {
    if (selectedThreadId === threadId || loading) return;
    setThreadId(selectedThreadId);
  };

  // Rename conversation
  const handleStartRename = (conv, e) => {
    e.stopPropagation();
    setEditingThreadId(conv.thread_id);
    setEditTitleInput(conv.title || '');
  };

  const handleCancelRename = (e) => {
    if (e) e.stopPropagation();
    setEditingThreadId(null);
    setEditTitleInput('');
  };

  const handleSaveRename = async (targetThreadId, e) => {
    if (e) e.stopPropagation();
    const newTitle = editTitleInput.trim();
    if (!newTitle) {
      setEditingThreadId(null);
      return;
    }
    try {
      await renameAgentConversation(targetThreadId, newTitle);
      setConversations((prev) =>
        prev.map((c) => (c.thread_id === targetThreadId ? { ...c, title: newTitle, updated_at: new Date().toISOString() } : c))
      );
      showToast('Đã đổi tên cuộc trò chuyện.', 'success');
    } catch (err) {
      showToast(`Không thể đổi tên: ${err.message || err}`, 'error');
    } finally {
      setEditingThreadId(null);
      setEditTitleInput('');
    }
  };

  // Delete conversation explicitly with confirmation
  const handleRequestDelete = (conv, e) => {
    e.stopPropagation();
    setDeleteModalConv(conv);
  };

  const handleConfirmDelete = async () => {
    if (!deleteModalConv) return;
    const targetThreadId = deleteModalConv.thread_id;
    setDeleting(true);
    try {
      await deleteAgentConversation(targetThreadId);
      const remaining = conversations.filter((c) => c.thread_id !== targetThreadId);
      setConversations(remaining);
      showToast('Đã xóa cuộc trò chuyện.', 'info');
      setDeleteModalConv(null);

      // If active conversation was deleted, switch to next or create new
      if (threadId === targetThreadId) {
        if (remaining.length > 0) {
          setThreadId(remaining[0].thread_id);
        } else {
          handleCreateNewConversation();
        }
      }
    } catch (err) {
      showToast(`Không thể xóa cuộc trò chuyện: ${err.message || err}`, 'error');
    } finally {
      setDeleting(false);
    }
  };

  // Filter conversations by search query
  const filteredConversations = conversations.filter((c) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (c.title || '').toLowerCase().includes(query) || (c.thread_id || '').toLowerCase().includes(query);
  });

  const activeConversation = conversations.find((c) => c.thread_id === threadId);

  return (
    <div className="page-container agent-page" id="agentPage">
      <Header
        title="DATT AI Assistant"
        status={{
          className: apiStatus === 'connected' ? 'live' : apiStatus === 'connecting' ? 'connecting' : 'disconnected',
          label: apiStatus === 'connected' ? 'AGENT API ONLINE' : apiStatus === 'connecting' ? 'AGENT API CONNECTING' : 'AGENT API OFFLINE',
        }}
        subtitle="Hệ thống Điều phối Tác tử LangGraph, LangChain & Truy xuất Tri thức pgvector RAG"
        actions={
          <div className="header-actions-group">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleCreateNewConversation}
              disabled={loading}
              id="btnNewConversation"
              title="Tạo cuộc trò chuyện mới mà không xóa lịch sử cũ"
            >
              <Plus size={16} />
              <span>Cuộc trò chuyện mới</span>
            </button>
          </div>
        }
      />

      <div className="agent-main-container">
        {/* Persistent Conversation History Sidebar */}
        <aside className={`agent-history-sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
          <div className="sidebar-header">
            <div className="sidebar-title">
              <MessageSquare size={16} />
              <span>Lịch sử trò chuyện</span>
              {conversations.length > 0 && (
                <span className="conversation-count-badge">{conversations.length}</span>
              )}
            </div>
            <button
              type="button"
              className="btn-icon sidebar-collapse-btn"
              onClick={() => setSidebarOpen(false)}
              title="Thu nhỏ thanh bên"
            >
              <PanelLeftClose size={16} />
            </button>
          </div>

          <div className="sidebar-action-bar">
            <button
              type="button"
              className="btn btn-primary btn-new-chat-sidebar"
              onClick={handleCreateNewConversation}
              disabled={loading}
              id="btnSidebarNewChat"
            >
              <Plus size={16} />
              <span>Cuộc trò chuyện mới</span>
            </button>
          </div>

          {/* Quick Search in Conversation History */}
          {conversations.length > 3 && (
            <div className="conversation-search-bar">
              <Search size={14} className="search-icon" />
              <input
                type="text"
                placeholder="Tìm kiếm cuộc trò chuyện..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="conversation-search-input"
              />
              {searchQuery && (
                <button
                  type="button"
                  className="search-clear-btn"
                  onClick={() => setSearchQuery('')}
                  title="Xóa tìm kiếm"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          )}

          {/* Conversation List */}
          <div className="conversation-list" role="list">
            {loadingConversations && conversations.length === 0 ? (
              <div className="conversation-list-loading">
                <RefreshCw size={16} className="spin-icon" />
                <span>Đang tải danh sách...</span>
              </div>
            ) : filteredConversations.length === 0 ? (
              <div className="conversation-empty-state">
                <MessageSquare size={26} className="empty-icon" />
                <p className="empty-title">
                  {searchQuery ? 'Không tìm thấy kết quả' : 'Chưa có cuộc trò chuyện'}
                </p>
                <p className="empty-sub">
                  {searchQuery ? 'Thử tìm với từ khóa khác' : 'Bắt đầu đặt câu hỏi với AI Assistant'}
                </p>
              </div>
            ) : (
              filteredConversations.map((conv) => {
                const isActive = conv.thread_id === threadId;
                const isEditing = editingThreadId === conv.thread_id;

                return (
                  <div
                    key={conv.thread_id}
                    className={`conversation-item ${isActive ? 'active' : ''}`}
                    onClick={() => !isEditing && handleSelectConversation(conv.thread_id)}
                    role="listitem"
                  >
                    <div className="conversation-item-icon">
                      <MessageSquare size={15} />
                    </div>

                    <div className="conversation-item-body">
                      {isEditing ? (
                        <form
                          className="conversation-rename-form"
                          onSubmit={(e) => {
                            e.preventDefault();
                            handleSaveRename(conv.thread_id, e);
                          }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="text"
                            value={editTitleInput}
                            onChange={(e) => setEditTitleInput(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Escape') handleCancelRename(e);
                            }}
                            autoFocus
                            className="rename-input"
                          />
                          <button
                            type="submit"
                            className="rename-action-btn save"
                            title="Lưu tên mới"
                          >
                            <Check size={13} />
                          </button>
                          <button
                            type="button"
                            className="rename-action-btn cancel"
                            onClick={handleCancelRename}
                            title="Hủy"
                          >
                            <X size={13} />
                          </button>
                        </form>
                      ) : (
                        <>
                          <div className="conversation-item-title" title={conv.title || 'Cuộc trò chuyện mới'}>
                            {conv.title || 'Cuộc trò chuyện mới'}
                          </div>
                          <div className="conversation-item-meta">
                            <Clock size={11} />
                            <span>
                              {formatConversationTime(conv.last_message_at || conv.updated_at || conv.created_at)}
                            </span>
                          </div>
                        </>
                      )}
                    </div>

                    {!isEditing && (
                      <div className="conversation-item-actions" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="item-action-btn rename"
                          onClick={(e) => handleStartRename(conv, e)}
                          title="Đổi tên cuộc trò chuyện"
                        >
                          <Edit2 size={13} />
                        </button>
                        <button
                          type="button"
                          className="item-action-btn delete"
                          onClick={(e) => handleRequestDelete(conv, e)}
                          title="Xóa cuộc trò chuyện này"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* Mobile backdrop overlay */}
        {sidebarOpen && (
          <div
            className="sidebar-backdrop"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Chat Layout */}
        <div className="agent-chat-layout">
          {/* Thread header / title bar */}
          <div className="chat-thread-header">
            {!sidebarOpen && (
              <button
                type="button"
                className="btn-icon sidebar-open-btn"
                onClick={() => setSidebarOpen(true)}
                title="Mở lịch sử cuộc trò chuyện"
              >
                <PanelLeft size={16} />
              </button>
            )}
            <div className="chat-active-title">
              <span className="title-text">{activeConversation?.title || 'Cuộc trò chuyện mới'}</span>
              <span className="thread-badge" title="Thread ID">{threadId}</span>
            </div>
          </div>

          {/* Quick Prompts Bar */}
          <div className="quick-prompts-bar">
            <div className="quick-prompts-label">
              <Sparkles size={14} /> Gợi ý thao tác nhanh:
            </div>
            <div className="quick-prompts-list">
              {QUICK_PROMPTS.map((qp, idx) => {
                const IconComponent = qp.icon;
                return (
                  <button
                    key={idx}
                    type="button"
                    className="quick-prompt-chip"
                    onClick={() => handleSendMessage(qp.prompt)}
                    disabled={loading}
                  >
                    <IconComponent size={14} />
                    <span>{qp.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Message Thread History */}
          <div className="chat-messages-container" id="chatMessages">
            {loadingHistory && (
              <div className="chat-history-loading">
                <RefreshCw size={18} className="spin-icon" />
                <span>Đang tải lịch sử tin nhắn...</span>
              </div>
            )}

            {messages.map((msg) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={msg.id}
                  className={`chat-message-row ${isUser ? 'user-row' : 'assistant-row'}`}
                >
                  <div className={`message-avatar ${isUser ? 'user-avatar' : 'bot-avatar'}`}>
                    {isUser ? <User size={18} /> : <Bot size={18} />}
                  </div>

                  <div className="message-content-wrapper">
                    <div className="message-bubble">
                      {msg.toolsCalled && msg.toolsCalled.length > 0 && (
                        <div className="tools-badge-list">
                          <Layers size={12} />
                          <span>Công cụ đã dùng:</span>
                          {[...new Set(msg.toolsCalled)].map((tc, tidx) => (
                            <span key={tidx} className="tool-tag">
                              {tc}
                            </span>
                          ))}
                        </div>
                      )}

                      <AgentMessageContent content={msg.content} isUser={isUser} />

                      {msg.sources && msg.sources.length > 0 && (
                        <div className="sources-container">
                          <div className="sources-header">
                            <BookOpen size={13} />
                            <span>Nguồn tài liệu RAG tham chiếu:</span>
                          </div>
                          <div className="sources-grid">
                            {msg.sources.map((src, sidx) => (
                              <div key={sidx} className="source-card">
                                <div className="source-title">
                                  <FileText size={12} />
                                  <span>{src.title}</span>
                                </div>
                                <div className="source-meta">
                                  <span>Mục: {src.section}</span>
                                  {src.score && (
                                    <span className="source-score">
                                      {(src.score * 100).toFixed(0)}% khớp
                                    </span>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {msg.timestamp && (
                      <span className="message-timestamp">{msg.timestamp}</span>
                    )}
                  </div>
                </div>
              );
            })}

            {loading && (
              <div className="chat-message-row assistant-row loading-row">
                <div className="message-avatar bot-avatar">
                  <Bot size={18} />
                </div>
                <div className="message-content-wrapper">
                  <div className="message-bubble typing-indicator">
                    <span className="dot"></span>
                    <span className="dot"></span>
                    <span className="dot"></span>
                    <span className="loading-caption">AI Agent đang tra cứu và suy luận...</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Bar */}
          <form
            className="chat-input-bar"
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
          >
            <input
              type="text"
              className="chat-text-input"
              id="agentMessageInput"
              placeholder="Hỏi về camera, phương tiện, biển số, khuôn mặt hoặc tra cứu vận hành..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              disabled={loading}
              autoFocus
            />
            <button
              type="submit"
              className="btn btn-primary btn-send"
              id="btnSendAgentMessage"
              onClick={(e) => {
                e.preventDefault();
                handleSendMessage();
              }}
              disabled={!inputValue.trim() || loading}
            >
              <Send size={16} />
              <span>Gửi</span>
            </button>
          </form>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {deleteModalConv && (
        <div className="agent-modal-backdrop" onClick={() => !deleting && setDeleteModalConv(null)}>
          <div className="agent-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <AlertCircle size={20} className="modal-icon-danger" />
              <h3>Xác nhận xóa cuộc trò chuyện</h3>
            </div>
            <p className="modal-desc">
              Bạn có chắc chắn muốn xóa cuộc trò chuyện <strong>"{deleteModalConv.title || 'Cuộc trò chuyện'}"</strong> không?
              Toàn bộ lịch sử tin nhắn và ngữ cảnh của cuộc trò chuyện này sẽ bị xóa vĩnh viễn khỏi hệ thống.
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setDeleteModalConv(null)}
                disabled={deleting}
              >
                Hủy
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={handleConfirmDelete}
                disabled={deleting}
              >
                {deleting ? 'Đang xóa...' : 'Xóa vĩnh viễn'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
