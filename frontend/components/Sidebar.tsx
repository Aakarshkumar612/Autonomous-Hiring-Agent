'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useUser } from '@clerk/nextjs'

const mainNavItems = [
  { href: '/dashboard',              icon: 'dashboard',    label: 'Dashboard' },
  { href: '/dashboard/upload',       icon: 'upload_file',  label: 'Upload Resume' },
  { href: '/dashboard/applications', icon: 'description',  label: 'Applications' },
  { href: '/dashboard/results',      icon: 'analytics',    label: 'Results' },
  { href: '/dashboard/interview',    icon: 'forum',        label: 'Live Interview', badge: 'LIVE', badgeColor: 'secondary' },
  { href: '/dashboard/chatbot',      icon: 'smart_toy',    label: 'AI Chatbot' },
  { href: '/dashboard/history',      icon: 'history',      label: 'History' },
]

const prefNavItems = [
  { href: '/dashboard/settings', icon: 'settings', label: 'Settings' },
  { href: '/dashboard/help', icon: 'help', label: 'Help' },
]

export default function Sidebar() {
  const pathname = usePathname()
  const { user } = useUser()

  const displayName = user?.fullName ?? user?.firstName ?? 'User'
  const userEmail   = user?.primaryEmailAddress?.emailAddress ?? ''
  const avatarUrl   = user?.imageUrl
  const initials    = displayName
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2) || 'U'

  const isActive = (href: string) => {
    if (href === '/dashboard') return pathname === '/dashboard'
    return pathname.startsWith(href)
  }

  return (
    <aside className="fixed h-full w-[256px] left-0 top-0 overflow-y-auto bg-[#0a0f1e] shadow-2xl shadow-black/50 z-[60] flex flex-col py-8 no-scrollbar">
      {/* Logo */}
      <div className="px-6 mb-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-primary-container flex items-center justify-center">
            <span className="material-symbols-outlined text-on-primary text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>
              smart_toy
            </span>
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-primary">HireIQ</h1>
            <p className="text-[10px] font-semibold tracking-wider uppercase text-on-surface-variant opacity-60">
              Autonomous Precision
            </p>
          </div>
        </div>
      </div>

      {/* Main Nav */}
      <nav className="flex-1 space-y-0.5">
        <div className="px-6 pb-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-outline opacity-50 font-bold">Main</p>
        </div>

        {mainNavItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`flex items-center gap-3 px-6 py-3 transition-all duration-150 group ${
              isActive(item.href)
                ? 'text-primary font-semibold border-r-2 border-primary bg-surface-container'
                : 'text-on-surface-variant hover:text-white hover:bg-surface-container-low'
            }`}
          >
            <span
              className="material-symbols-outlined text-[20px]"
              style={item.label === 'AI Chatbot' && isActive(item.href) ? { fontVariationSettings: "'FILL' 1" } : {}}
            >
              {item.icon}
            </span>
            <span className="text-[11px] font-semibold tracking-wider uppercase flex-1">{item.label}</span>
            {item.badge && (
              <span
                className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase tracking-wider ${
                  item.badgeColor === 'secondary'
                    ? 'bg-secondary/20 text-secondary border border-secondary/30'
                    : 'bg-surface-container-high text-outline'
                }`}
              >
                {item.badge}
              </span>
            )}
          </Link>
        ))}

        {/* Preferences section */}
        <div className="px-6 pt-6 pb-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-outline opacity-50 font-bold">Preferences</p>
        </div>

        {prefNavItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`flex items-center gap-3 px-6 py-3 transition-all duration-150 ${
              isActive(item.href)
                ? 'text-primary font-semibold border-r-2 border-primary bg-surface-container'
                : 'text-on-surface-variant hover:text-white hover:bg-surface-container-low'
            }`}
          >
            <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
            <span className="text-[11px] font-semibold tracking-wider uppercase">{item.label}</span>
          </Link>
        ))}
      </nav>

      {/* Bottom: New Analysis CTA + User */}
      <div className="px-4 mt-6 space-y-4">
        <Link href="/dashboard/upload" className="block">
          <button className="w-full bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-3 rounded-xl flex items-center justify-center gap-2 active:scale-[0.98] transition-transform shadow-lg shadow-primary-container/20 text-sm">
            <span className="material-symbols-outlined text-[18px]">add</span>
            New Analysis
          </button>
        </Link>

        <div className="pt-4 border-t border-outline-variant/10 space-y-1">
          <Link
            href="/dashboard/notifications"
            className="flex items-center justify-between text-on-surface-variant hover:text-white cursor-pointer px-2 py-2 rounded-lg hover:bg-surface-container-low transition-colors"
          >
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-[20px]">notifications</span>
              <span className="text-xs font-semibold">Notifications</span>
            </div>
            <span className="w-2 h-2 bg-secondary rounded-full"></span>
          </Link>

          <Link
            href="/dashboard/profile"
            className="flex items-center gap-3 text-on-surface-variant hover:text-white cursor-pointer px-2 py-2 rounded-lg hover:bg-surface-container-low transition-colors"
          >
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt={displayName}
                className="w-8 h-8 rounded-full object-cover flex-shrink-0"
              />
            ) : (
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-sm flex-shrink-0">
                {initials}
              </div>
            )}
            <div className="min-w-0">
              <p className="text-xs font-bold text-on-surface truncate">{displayName}</p>
              <p className="text-[10px] text-outline uppercase tracking-tighter truncate">{userEmail}</p>
            </div>
            <div className="w-2 h-2 bg-secondary rounded-full flex-shrink-0 ml-auto"></div>
          </Link>
        </div>
      </div>
    </aside>
  )
}
