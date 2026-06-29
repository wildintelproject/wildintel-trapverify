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
    <div className="flex justify-center items-center min-h-screen bg-zinc-950">
      <div className="w-8 h-8 border-2 border-zinc-700 border-t-zinc-300 rounded-full animate-spin" />
    </div>
  )

  return (
    <BrowserRouter>
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
        <Navbar ready={ready} />
        <Routes>
          <Route path="/" element={
            <SetupPage onSetup={() => setReady(true)} ready={ready} />
          } />
          <Route path="/setup" element={
            <SetupPage onSetup={() => setReady(true)} ready={ready} />
          } />
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
      </div>
    </BrowserRouter>
  )
}
