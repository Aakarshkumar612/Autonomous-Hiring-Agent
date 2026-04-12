import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import './globals.css'

export const metadata: Metadata = {
  title: {
    default: 'HireIQ — Autonomous Hiring Intelligence',
    template: '%s | HireIQ',
  },
  description: 'HireIQ autonomously scores resumes, conducts AI-powered interviews, detects AI-generated responses, and makes data-driven hiring decisions — in minutes, not weeks.',
  keywords: ['hiring', 'AI', 'recruitment', 'autonomous', 'resume', 'interview'],
  authors: [{ name: 'HireIQ' }],
  openGraph: {
    title: 'HireIQ — Autonomous Hiring Intelligence',
    description: 'Hire smarter, fairer, and faster with AI.',
    type: 'website',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <ClerkProvider>
      <html lang="en" className="dark">
        <head>
          <link rel="preconnect" href="https://fonts.googleapis.com" />
          <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
          <link
            href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"
            rel="stylesheet"
          />
          <link
            href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
            rel="stylesheet"
          />
        </head>
        <body className="bg-background text-on-surface font-body antialiased selection:bg-primary-container/30 overflow-x-hidden">
          {children}
        </body>
      </html>
    </ClerkProvider>
  )
}
