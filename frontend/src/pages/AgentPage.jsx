import React, { useState, useEffect, useRef } from 'react';
import { Header } from '../components/Header';
import { AgentMessageContent } from '../components/AgentMessageContent';
import { sendAgentMessage, resetAgentConversation, getAgentConversation } from '../api/agent';
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

export function AgentPage() {
  const { showToast } = useToast();
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState('connecting');
  const [threadId, setThreadId] = useState(() => {
    return localStorage.getItem('datt_agent_thread_id') || `thread_${Date.now()}`;
  });
  const messagesEndRef = useRef(null);

  // Sync thread_id to localStorage
  useEffect(() => {
    localStorage.setItem('datt_agent_thread_id', threadId);
  }, [threadId]);

  // Load conversation history on mount or set initial welcome message
  useEffect(() => {
    let active = true;
    async function loadHistory() {
      if (!threadId) return;
      try {
        const resp = await getAgentConversation(threadId);
        if (active) setApiStatus(resp?.status === 'error' ? 'error' : 'connected');
        if (active && resp && resp.messages && resp.messages.length > 0) {
          const restored = resp.messages
            .filter((m) => m.type === 'human' || m.type === 'ai' || m.type === 'AIMessage' || m.type === 'HumanMessage')
            .map((m, idx) => ({
              id: `restored_${idx}`,
              role: (m.type === 'human' || m.type === 'HumanMessage') ? 'user' : 'assistant',
              content: m.content,
              timestamp: '',
              sources: [],
              toolsCalled: [],
            }));
          if (restored.length > 0) {
            setMessages(restored);
            return;
          }
        }
      } catch (err) {
        if (active) setApiStatus('error');
        console.warn('Failed to restore conversation history:', err);
      }

      if (active && messages.length === 0) {
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

  const handleSendMessage = async (textToSend) => {
    const text = (textToSend || inputValue).trim();
    if (!text || loading) return;

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
      const resp = await sendAgentMessage(text, threadId);
      setApiStatus('connected');
      if (resp && resp.status === 'success') {
        const botMsg = {
          id: `bot_${Date.now()}`,
          role: 'assistant',
          content: resp.reply,
          sources: resp.sources || [],
          toolsCalled: resp.tools_called || [],
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
    } catch (err) {
      setApiStatus('error');
      const errorMsg = {
        id: `err_${Date.now()}`,
        role: 'assistant',
        isError: true,
        content: `Không thể kết nối đến AI Agent: ${err.message || err}`,
        timestamp: new Date().toLocaleTimeString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
      showToast(err.message || 'Lỗi mạng khi kết nối AI Agent', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleResetConversation = async () => {
    try {
      await resetAgentConversation(threadId);
    } catch (e) {
      // Ignore reset failure
    }
    const newThread = `thread_${Date.now()}`;
    setThreadId(newThread);
    setMessages([
      {
        id: 'welcome_new',
        role: 'assistant',
        content: 'Cuộc hội thoại đã được đặt lại. Tôi có thể hỗ trợ gì cho bạn?',
        sources: [],
        toolsCalled: [],
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);
    showToast('Bộ nhớ ngắn hạn của phiên hội thoại đã được làm mới.', 'info');
  };

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
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleResetConversation}
            disabled={loading}
            title="Tạo phiên hội thoại mới và xóa bộ nhớ tạm"
          >
            <Trash2 size={16} />
            <span>Phiên mới</span>
          </button>
        }
      />

      <div className="agent-chat-layout">
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
                        {msg.toolsCalled.map((tc, tidx) => (
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

                  <span className="message-timestamp">{msg.timestamp}</span>
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
            placeholder="Hỏi về camera, sự kiện, thống kê hoặc nhập câu hỏi vận hành..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={loading}
            autoFocus
          />
          <button
            type="submit"
            className="btn btn-primary btn-send"
            id="btnSendAgentMessage"
            disabled={!inputValue.trim() || loading}
          >
            <Send size={16} />
            <span>Gửi</span>
          </button>
        </form>
      </div>
    </div>
  );
}
