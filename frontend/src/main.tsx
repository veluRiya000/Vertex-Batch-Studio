import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import { PreferencesProvider } from './preferences'
createRoot(document.getElementById('root')!).render(<PreferencesProvider><App /></PreferencesProvider>)
