import Link from 'next/link'
import { SignUp } from '@clerk/nextjs'
import type { Metadata } from 'next'

export const metadata: Metadata = { title: 'Sign Up' }

const features = [
  '100 free resume analyses per month',
  'Full AI interview pipeline access',
  'Real-time AI detection engine',
  'No credit card required',
]

export default function SignUpPage() {
  return (
    <div className="min-h-screen bg-surface flex">
      {/* Left Half */}
      <div className="hidden lg:flex flex-col justify-between w-1/2 relative overflow-hidden p-12">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] radial-glow-secondary pointer-events-none"></div>

        <Link href="/" className="relative z-10">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold tracking-tight text-primary">HireIQ</span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-outline px-2 py-0.5 border border-outline-variant/30 rounded-full">Autonomous</span>
          </div>
        </Link>

        <div className="relative z-10 max-w-md">
          <h2 className="text-3xl font-bold tracking-tight mb-6">Start hiring with AI intelligence</h2>
          <p className="text-on-surface-variant mb-8">Get your free account and experience the future of autonomous hiring. No credit card needed.</p>

          <div className="space-y-4 mb-8">
            {features.map((f) => (
              <div key={f} className="flex items-center gap-3">
                <span className="material-symbols-outlined text-secondary text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                <span className="text-sm text-on-surface-variant">{f}</span>
              </div>
            ))}
          </div>

          <div className="flex gap-8">
            {[
              { value: '500+', label: 'Companies' },
              { value: '12k+', label: 'Hires Made' },
              { value: '95%', label: 'Accuracy' },
            ].map((stat) => (
              <div key={stat.label}>
                <p className="text-2xl font-mono font-bold text-primary">{stat.value}</p>
                <p className="text-[10px] text-on-surface-variant uppercase tracking-wider">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="text-[10px] text-outline relative z-10">© 2026 HireIQ Intelligence Systems</p>
      </div>

      {/* Right Half — Clerk Sign Up */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-[420px]">
          {/* Mobile logo */}
          <div className="lg:hidden mb-8 text-center">
            <Link href="/">
              <span className="text-2xl font-bold tracking-tight text-primary">HireIQ</span>
            </Link>
          </div>

          <SignUp
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
                formFieldInput: 'bg-surface-container-high border border-outline-variant/20 text-on-surface rounded-xl placeholder:text-outline focus:border-secondary focus:ring-1 focus:ring-secondary transition-colors',
                formButtonPrimary: 'bg-gradient-to-r from-secondary to-secondary-container text-on-secondary-fixed font-bold rounded-xl shadow-lg shadow-secondary/20 hover:shadow-secondary/30 hover:opacity-90 transition-all',
                footerActionLink: 'text-primary font-semibold hover:underline',
                footerActionText: 'text-on-surface-variant text-sm',
                identityPreviewText: 'text-on-surface',
                identityPreviewEditButton: 'text-primary',
                formResendCodeLink: 'text-secondary',
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
