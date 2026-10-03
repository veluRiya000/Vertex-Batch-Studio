import { notifyRendererReady, reportRendererFailure } from './tauri-bridge'
import { useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './management.css'
import { PreferencesProvider } from './preferences'
function StudioRoot() {
  useEffect(() => { void notifyRendererReady().catch(reportRendererFailure) }, [])
  return <PreferencesProvider><App /></PreferencesProvider>
}
createRoot(document.getElementById('root')!).render(<StudioRoot />)
