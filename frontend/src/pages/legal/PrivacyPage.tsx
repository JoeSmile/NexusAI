import { Navigate } from 'react-router-dom'

/** Privacy is folded into the unified user agreement. */
export default function PrivacyPage() {
  return <Navigate to="/terms" replace />
}
