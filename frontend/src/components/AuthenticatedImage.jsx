import React, { useState, useEffect, useRef } from 'react';
import { apiRequest } from '../api/client';
import { readConnection } from '../api/connection';

// In-memory cache for materialized blob URLs to prevent redundant network fetches
const blobUrlCache = new Map();

const DEFAULT_AVATAR_FALLBACK =
  'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="%2364748b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>';

export function AuthenticatedImage({
  src,
  alt = '',
  className = '',
  style = {},
  fallback = null,
  onError = null,
  ...rest
}) {
  const [objectUrl, setObjectUrl] = useState(() => {
    if (!src) return '';
    if (src.startsWith('data:') || src.startsWith('blob:')) return src;
    if (blobUrlCache.has(src)) return blobUrlCache.get(src);
    return '';
  });
  const [hasError, setHasError] = useState(false);
  const [loading, setLoading] = useState(!objectUrl && Boolean(src));
  const activeSrcRef = useRef(src);

  useEffect(() => {
    activeSrcRef.current = src;
    setHasError(false);

    if (!src) {
      setObjectUrl('');
      setLoading(false);
      return;
    }

    // Direct render for inline data URIs or already-resolved blob URLs
    if (src.startsWith('data:') || src.startsWith('blob:')) {
      setObjectUrl(src);
      setLoading(false);
      return;
    }

    // Check memory cache
    if (blobUrlCache.has(src)) {
      setObjectUrl(blobUrlCache.get(src));
      setLoading(false);
      return;
    }

    const { token } = readConnection();
    // If no token is required/configured, attempt normal img loading
    if (!token && !src.startsWith('/api/')) {
      setObjectUrl(src);
      setLoading(false);
      return;
    }

    let isCancelled = false;
    const abortCtrl = new AbortController();
    setLoading(true);

    (async () => {
      try {
        const response = await apiRequest(src, {
          signal: abortCtrl.signal,
          responseType: 'response',
          cacheTtlMs: 60000,
        });

        if (isCancelled || activeSrcRef.current !== src) return;

        const blob = await response.blob();
        if (isCancelled || activeSrcRef.current !== src) return;

        const url = URL.createObjectURL(blob);
        blobUrlCache.set(src, url);
        setObjectUrl(url);
      } catch (err) {
        if (err.name !== 'AbortError' && !isCancelled && activeSrcRef.current === src) {
          // If authenticated fetch fails, try fallback or direct load
          setHasError(true);
          if (onError) onError(err);
        }
      } finally {
        if (!isCancelled && activeSrcRef.current === src) {
          setLoading(false);
        }
      }
    })();

    return () => {
      isCancelled = true;
      abortCtrl.abort();
    };
  }, [src, onError]);

  const handleImgError = (e) => {
    setHasError(true);
    if (onError) onError(e);
    else e.currentTarget.src = DEFAULT_AVATAR_FALLBACK;
  };

  if (hasError && fallback) {
    return <>{fallback}</>;
  }

  const finalSrc = objectUrl || (hasError ? DEFAULT_AVATAR_FALLBACK : (loading ? '' : src));

  return (
    <img
      src={finalSrc || DEFAULT_AVATAR_FALLBACK}
      alt={alt}
      className={className}
      style={{
        ...style,
        opacity: loading && !objectUrl ? 0.6 : 1,
        transition: 'opacity 0.2s ease',
      }}
      onError={handleImgError}
      {...rest}
    />
  );
}
