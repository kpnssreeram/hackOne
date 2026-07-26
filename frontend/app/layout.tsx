import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Nolan — Story Series Studio',
  description: 'One idea in. One cinematic audio or video series out.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-nolan-bg text-nolan-text overflow-x-hidden">
        {/* Ambient orbs */}
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="orb orb-3" />
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  )
}
