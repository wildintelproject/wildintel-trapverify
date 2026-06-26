import { useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes, Navigate } from 'react-router-dom'
import Navbar from './components/Navbar'
import GalleryPage from './pages/GalleryPage'
import IndexPage from './pages/IndexPage'
import ResultsPage from './pages/ResultsPage'
import SetupPage from './pages/SetupPage'
import { api } from './api'

export default function App() {
  const [ready, setReady] = useState<boolean | null>(null)

  useEffect(() => {
    api.getState()
      .then((s) => setReady(s.ready))
      .catch(() => setReady(false))
  }, [])

  if (ready === null) return (
    <div className="d-flex justify-content-center align-items-center vh-100">
      <div className="spinner-border text-secondary" role="status" />
    </div>
  )

  return (
    <BrowserRouter>
      <Navbar ready={ready} />
      <Routes>
        {/* Bienvenida — siempre accesible */}
        <Route path="/" element={
          <SetupPage onSetup={() => setReady(true)} ready={ready} />
        } />

        {/* Wizard de configuración (pasos 0-3) — accesible desde la bienvenida */}
        <Route path="/setup" element={
          <SetupPage onSetup={() => setReady(true)} ready={ready} />
        } />

        {/* Verificación — solo si hay sesión activa */}
        <Route path="/species"
          element={ready ? <IndexPage /> : <Navigate to="/" replace />}
        />
        <Route path="/gallery/:species"
          element={ready ? <GalleryPage /> : <Navigate to="/" replace />}
        />
        <Route path="/results"
          element={ready ? <ResultsPage /> : <Navigate to="/" replace />}
        />
      </Routes>
    </BrowserRouter>
  )
}
