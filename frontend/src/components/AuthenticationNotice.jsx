import React from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../context/AppContext';

export function AuthenticationNotice() {
  const { authenticationStatus } = useApp();
  if (!authenticationStatus) return null;
  return (
    <div className="card" role="alert" id="authenticationNotice" style={{ margin: '16px 24px 0', padding: '12px 16px' }}>
      {authenticationStatus === 403
        ? 'Tài khoản chưa có quyền truy cập dữ liệu này.'
        : 'Cần xác thực: token chưa được cấu hình hoặc không còn hợp lệ.'}
      {' '}<Link to="/settings">Mở Cài đặt để xác thực</Link>
    </div>
  );
}
