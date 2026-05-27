import React, { createContext, useContext, useState, useCallback } from 'react';

const ToastContext = createContext(null);

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => {
  const ctx = useContext(ToastContext);
  return ctx || { addToast: () => {} };
};

let _toastCount = 0;

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'success', duration = 4500) => {
    const id = ++_toastCount;
    setToasts(prev => [...prev, { id, message, type }]);
    if (duration > 0) {
      setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration);
    }
  }, []);

  const dismiss = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const variantFor = (type) => {
    if (type === 'error') return 'danger';
    if (type === 'info') return 'primary';
    return type;
  };

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        style={{
          position: 'fixed',
          top: '4.5rem',
          right: '1rem',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          maxWidth: '400px',
          width: 'calc(100vw - 2rem)',
          pointerEvents: 'none',
        }}
      >
        {toasts.map(toast => (
          <div
            key={toast.id}
            role="alert"
            className={`alert alert-${variantFor(toast.type)} d-flex align-items-start gap-2 mb-0 shadow`}
            style={{ pointerEvents: 'all', fontSize: '0.875rem', animation: 'fadeInRight 0.2s ease' }}
          >
            <span style={{ flex: 1 }}>{toast.message}</span>
            <button
              type="button"
              className="btn-close mt-0"
              style={{ fontSize: '0.7rem', flexShrink: 0 }}
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss"
            />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};
