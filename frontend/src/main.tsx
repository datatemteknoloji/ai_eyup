import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { installFetchInterceptor } from './auth/authStore'
import { initChatFontSize } from './lib/chatFontSize'

// Tüm fetch çağrılarına token enjekte et + 401'de oturumu kapat (render'dan önce kurulmalı)
installFetchInterceptor()
initChatFontSize()   // Adım 16: sohbet yazı boyutu (localStorage)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
