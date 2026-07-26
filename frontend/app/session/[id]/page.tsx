import { Suspense } from 'react'
import SessionPageClient from './SessionPageClient'

// Required for Next.js static export with dynamic routes.
// FastAPI serves session/placeholder/index.html for every /session/* URL;
// the actual session ID is read from the URL at runtime via useParams().
export function generateStaticParams() {
  return [{ id: 'placeholder' }]
}

export default function Page({ params }: { params: { id: string } }) {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <p className="text-white text-sm animate-pulse">Loading Nolan Studio…</p>
        </div>
      }
    >
      <SessionPageClient />
    </Suspense>
  )
}
