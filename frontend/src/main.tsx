import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { installFetchInterceptor } from './auth/authStore'

// Tüm fetch çağrılarına token enjekte et + 401'de oturumu kapat (render'dan önce kurulmalı)
installFetchInterceptor()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
