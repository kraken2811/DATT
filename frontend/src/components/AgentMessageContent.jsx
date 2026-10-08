import React from 'react';
import ReactMarkdown from 'react-markdown';

// User messages stay literal. Assistant Markdown never executes raw HTML.
export function AgentMessageContent({ content, isUser = false }) {
  const value = typeof content === 'string' ? content : '';
  if (isUser) return <div className="message-text user-message-text">{value}</div>;
  return (
    <div className="message-text agent-markdown">
      <ReactMarkdown
        skipHtml
        components={{
          a: ({ href, children }) => href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
          img: ({ alt }) => <span>{alt || ''}</span>,
        }}
      >{value}</ReactMarkdown>
    </div>
  );
}
