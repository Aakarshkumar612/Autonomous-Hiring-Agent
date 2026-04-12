'use client'

import Link from 'next/link'
import { useUser } from '@clerk/nextjs'

export default function DashboardHeader() {
  const { user } = useUser()

  const fullName  = user?.fullName ?? user?.firstName ?? 'User'
  const initials  = fullName
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
  const avatarUrl = user?.imageUrl

  return (
    <header className="fixed top-0 right-0 w-[calc(100%-256px)] h-16 z-50 flex items-center justify-between px-8 bg-gradient-to-b from-[#0f1223] to-transparent backdrop-blur-xl border-b border-outline-variant/5">
      {/* Search */}
      <div className="relative w-full max-w-md group">
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-lg">
          search
        </span>
        <input
          className="w-full bg-surface-container-lowest border-none text-sm px-10 py-2.5 rounded-xl focus:ring-1 focus:ring-primary/50 text-on-surface-variant placeholder:text-outline/50 transition-all"
          placeholder="Search talent, analysis, or reports..."
          type="text"
        />
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-xs font-mono text-secondary opacity-80">
          <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse"></span>
          <span className="hidden sm:inline uppercase tracking-widest">System Active</span>
        </div>

        <div className="h-6 w-px bg-outline-variant/20"></div>

        <Link href="/dashboard/notifications">
          <button className="relative text-on-surface-variant hover:text-white transition-colors p-1">
            <span className="material-symbols-outlined text-[22px]">notifications</span>
          </button>
        </Link>

        <Link href="/dashboard/settings">
          <button className="text-on-surface-variant hover:text-white transition-colors p-1">
            <span className="material-symbols-outlined text-[22px]">settings</span>
          </button>
        </Link>

        <div className="h-6 w-px bg-outline-variant/20"></div>

        <Link href="/dashboard/profile" className="flex items-center gap-3 cursor-pointer group">
          <div className="text-right hidden sm:block">
            <p className="text-xs font-bold text-on-surface">{fullName}</p>
            <p className="text-[10px] text-primary truncate max-w-[160px]">
              {user?.primaryEmailAddress?.emailAddress ?? ''}
            </p>
          </div>
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt={fullName}
              className="w-8 h-8 rounded-full object-cover group-hover:ring-2 ring-primary/30 transition-all"
            />
          ) : (
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-xs group-hover:ring-2 ring-primary/30 transition-all">
              {initials}
            </div>
          )}
        </Link>
      </div>
    </header>
  )
}
