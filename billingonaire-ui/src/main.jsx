import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './Layout.jsx'
import 'bootstrap/dist/css/bootstrap.min.css';
import { ToastProvider } from './components/ToastProvider.jsx';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
)
