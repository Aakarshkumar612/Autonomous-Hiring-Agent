import Link from 'next/link'
import { SignIn } from '@clerk/nextjs'
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Sign In' }

const features = [
  'AI-powered resume scoring in seconds',
  'Autonomous 3-round interviews',
  '95% accurate AI detection engine',
]

export default function SignInPage() {
  return (
    <div className="min-h-screen bg-surface flex">
      {/* Left Half */}
      <div className="hidden lg:flex flex-col justify-between w-1/2 relative overflow-hidden p-12">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] radial-glow-primary pointer-events-none"></div>

        <Link href="/" className="relative z-10">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold tracking-tight text-primary">HireIQ</span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-outline px-2 py-0.5 border border-outline-variant/30 rounded-full">Autonomous</span>
          </div>
        </Link>

        <div className="relative z-10 max-w-md">
          <h2 className="text-3xl font-bold tracking-tight mb-6">Join 500+ companies hiring smarter</h2>
          <div className="space-y-4 mb-8">
            {features.map((f) => (
              <div key={f} className="flex items-center gap-3">
                <span className="material-symbols-outlined text-primary text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                <span className="text-sm text-on-surface-variant">{f}</span>
              </div>
            ))}
          </div>

          <div className="glass-panel rounded-xl p-6 border border-outline-variant/10">
            <div className="flex gap-1 text-secondary mb-3">
              {[...Array(5)].map((_, i) => (
                <span key={i} className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>star</span>
              ))}
            </div>
            <p className="text-sm text-on-surface italic mb-4">
              "HireIQ cut our hiring process from 3 weeks to 3 hours. The AI interviews are indistinguishable from human-conducted ones."
            </p>
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-xs">MT</div>
              <div>
                <p className="text-xs font-bold">Marcus Thorne</p>
                <p className="text-[10px] text-on-surface-variant">VP Engineering, VeloScale</p>
              </div>
            </div>
          </div>
        </div>

        <p className="text-[10px] text-outline relative z-10">© 2026 HireIQ Intelligence Systems</p>
      </div>

      {/* Right Half — Clerk Sign In */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-[420px]">
          {/* Mobile logo */}
          <div className="lg:hidden mb-8 text-center">
            <Link href="/">
              <span className="text-2xl font-bold tracking-tight text-primary">HireIQ</span>
            </Link>
          </div>

          <SignIn
            appearance={{
              elements: {
                rootBox: 'w-full',
                card: 'bg-surface-container border border-outline-variant/10 shadow-2xl shadow-black/40 rounded-2xl',
                headerTitle: 'text-on-surface font-bold',
                headerSubtitle: 'text-on-surface-variant',
                socialButtonsBlockButton: 'border border-outline-variant/20 bg-surface-container-high text-on-surface hover:bg-surface-bright transition-colors rounded-xl',
                socialButtonsBlockButtonText: 'text-on-surface font-semibold text-sm',
                dividerLine: 'bg-outline-variant/20',
                dividerText: 'text-outline text-xs uppercase tracking-wider',
                formFieldLabel: 'text-[10px] font-semibold text-outline uppercase tracking-wider',
                formFieldInput: 'bg-surface-container-high border border-outline-variant/20 text-on-surface rounded-xl placeholder:text-outline focus:border-primary focus:ring-1 focus:ring-primary transition-colors',
                formButtonPrimary: 'bg-primary text-on-primary font-bold rounded-xl shadow-lg shadow-primary/20 hover:shadow-primary/30 hover:opacity-90 transition-all',
                footerActionLink: 'text-primary font-semibold hover:underline',
                footerActionText: 'text-on-surface-variant text-sm',
                identityPreviewText: 'text-on-surface',
                identityPreviewEditButton: 'text-primary',
                formResendCodeLink: 'text-primary',
                otpCodeFieldInput: 'bg-surface-container-high border border-outline-variant/20 text-on-surface rounded-xl',
                alertText: 'text-error',
                formFieldSuccessText: 'text-success',
              },
            }}
          />
        </div>
      </div>
    </div>
  )
}
