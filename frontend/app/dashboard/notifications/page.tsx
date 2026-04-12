'use client'

import { useState } from 'react'

const filterTabs = ['All', 'Scores', 'Decisions', 'Alerts', 'System']

export default function NotificationsPage() {
  const [activeTab, setActiveTab] = useState('All')

  return (
    <div className="px-8 py-10 animate-fade-in">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-1">Notifications</h1>
          <p className="text-on-surface-variant text-sm">Stay updated on pipeline events and decisions</p>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-2 mb-8">
        {filterTabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider border transition-all ${
              activeTab === tab
                ? 'bg-primary/10 text-primary border-primary/30'
                : 'border-outline-variant/20 text-on-surface-variant hover:border-outline-variant/50'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Empty State */}
      <div className="flex flex-col items-center justify-center py-32 text-center max-w-3xl">
        <span className="material-symbols-outlined text-6xl text-outline mb-4">notifications_off</span>
        <h3 className="text-lg font-bold text-on-surface mb-2">No notifications yet</h3>
        <p className="text-sm text-on-surface-variant max-w-sm">
          You'll be notified here when resumes are scored, interviews complete, AI detection flags a response, or hiring decisions are made.
        </p>
      </div>
    </div>
  )
}
