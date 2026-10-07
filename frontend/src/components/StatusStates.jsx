import React from 'react';

export function LoadingSpinner({ text = 'Đang tải dữ liệu...' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '48px 24px', gap: '14px', color: 'var(--text-secondary)' }}>
      <div style={{ width: '32px', height: '32px', border: '3px solid var(--border-card)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
      <span style={{ fontSize: '0.85rem' }}>{text}</span>
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export function EmptyState({ icon: Icon, title = 'Không có dữ liệu', message = 'Chưa có bản ghi nào phù hợp với bộ lọc.', action = null }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '48px 24px', textAlign: 'center', gap: '12px' }}>
      {Icon && <Icon size={40} style={{ color: 'var(--text-muted)' }} />}
      <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', maxWidth: '400px' }}>{message}</p>
      {action && <div style={{ marginTop: '8px' }}>{action}</div>}
    </div>
  );
}

export function ErrorState({ title = 'Lỗi tải dữ liệu', message, onRetry = null }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '36px 24px', textAlign: 'center', gap: '12px', background: 'rgba(239, 68, 68, 0.08)', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
      <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#ef4444' }}>{title}</h4>
      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', maxWidth: '500px' }}>{message}</p>
      {onRetry && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  );
}
