'use client'

import { useState } from 'react'

const filterTabs = ['All Events', 'Uploads', 'Scores', 'Interviews', 'Decisions', 'Detection']

export default function HistoryPage() {
  const [activeTab, setActiveTab] = useState('All Events')

  return (
    <div className="px-8 py-10 animate-fade-in">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight mb-1">Activity History</h1>
        <p className="text-on-surface-variant text-sm">Complete log of all system events and pipeline actions</p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-10">
        <div className="flex flex-wrap gap-2">
          {filterTabs.map((f) => (
            <button
              key={f}
              onClick={() => setActiveTab(f)}
              className={`px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider transition-all border ${
                activeTab === f
                  ? 'bg-primary/10 text-primary border-primary/30'
                  : 'border-outline-variant/20 text-on-surface-variant hover:border-outline-variant/50'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <button className="px-4 py-2 bg-surface-container-low border border-outline-variant/20 rounded-lg text-xs font-bold text-on-surface-variant hover:text-white flex items-center gap-2 transition-all">
          <span className="material-symbols-outlined text-sm">download</span>
          Export Log
        </button>
      </div>

      {/* Empty State */}
      <div className="flex flex-col items-center justify-center py-32 text-center">
        <span className="material-symbols-outlined text-6xl text-outline mb-4">history</span>
        <h3 className="text-lg font-bold text-on-surface mb-2">No activity yet</h3>
        <p className="text-sm text-on-surface-variant max-w-sm">
          Events will appear here as you upload resumes, run the scoring pipeline, conduct interviews, and make hiring decisions.
        </p>
      </div>
    </div>
  )
}
