'use client'

import { useState, useEffect } from 'react'
import { useUser } from '@clerk/nextjs'

// ─── Types ─────────────────────────────────────────────────────────────────

interface ProfileData {
  name:     string
  email:    string
  phone:    string
  company:  string
  location: string
  role:     string
}

// ─── Edit Modal ─────────────────────────────────────────────────────────────

function EditProfileModal({
  profile,
  onSave,
  onClose,
}: {
  profile: ProfileData
  onSave: (updated: ProfileData) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<ProfileData>({ ...profile })

  function setField(key: keyof ProfileData, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const fields: { key: keyof ProfileData; label: string; type?: string }[] = [
    { key: 'name',     label: 'Full Name' },
    { key: 'email',    label: 'Email',    type: 'email' },
    { key: 'phone',    label: 'Phone',    type: 'tel' },
    { key: 'company',  label: 'Company' },
    { key: 'location', label: 'Location' },
    { key: 'role',     label: 'Job Title' },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-surface-container-low rounded-2xl p-8 w-full max-w-lg border border-outline-variant/10 shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-bold">Edit Profile</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
          >
            <span className="material-symbols-outlined text-xl">close</span>
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-6">
          {fields.map(({ key, label, type = 'text' }) => (
            <div key={key} className="space-y-2">
              <label className="text-[10px] font-semibold text-outline uppercase tracking-wider block">
                {label}
              </label>
              <input
                className="input-dark"
                type={type}
                value={draft[key]}
                onChange={(e) => setField(key, e.target.value)}
              />
            </div>
          ))}
        </div>

        <div className="flex items-center gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2.5 rounded-xl text-sm font-bold text-on-surface-variant hover:text-white bg-surface-container hover:bg-surface-container-high transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => { onSave(draft); onClose() }}
            className="px-5 py-2.5 bg-primary text-on-primary rounded-xl text-sm font-bold hover:shadow-lg hover:shadow-primary/20 transition-all active:scale-95"
          >
            Save Changes
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const { user } = useUser()

  const [profile, setProfile] = useState<ProfileData>({
    name:     user?.fullName ?? '',
    email:    user?.primaryEmailAddress?.emailAddress ?? '',
    phone:    '',
    company:  '',
    location: '',
    role:     '',
  })
  const [editing, setEditing] = useState(false)

  // Clerk loads asynchronously — sync name & email once user object is available
  useEffect(() => {
    if (!user) return
    setProfile((prev) => ({
      ...prev,
      name:  prev.name  || user.fullName  || '',
      email: prev.email || user.primaryEmailAddress?.emailAddress || '',
    }))
  }, [user])

  const avatarUrl = user?.imageUrl
  const initials  = (profile.name || 'U')
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <div className="px-8 py-10 animate-fade-in">
      {editing && (
        <EditProfileModal
          profile={profile}
          onSave={(updated) => setProfile(updated)}
          onClose={() => setEditing(false)}
        />
      )}

      {/* Profile Header */}
      <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/5 mb-8">
        <div className="h-2 bg-gradient-to-r from-primary via-secondary to-tertiary"></div>
        <div className="p-8 flex flex-col sm:flex-row items-start sm:items-center gap-6">

          {/* Avatar */}
          <div className="relative">
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt={profile.name || 'User'}
                className="w-24 h-24 rounded-full object-cover"
              />
            ) : (
              <div className="w-24 h-24 rounded-full bg-gradient-to-br from-primary-container to-secondary-container flex items-center justify-center text-on-primary font-bold text-3xl">
                {initials}
              </div>
            )}
          </div>

          <div className="flex-1">
            <h1 className="text-2xl font-bold">{profile.name || user?.fullName || 'Your Name'}</h1>
            <p className="text-on-surface-variant text-sm">{profile.role || 'Add your job title'}</p>
            <p className="text-xs text-outline mt-1">
              {[profile.company, profile.location].filter(Boolean).join(' • ') || 'Add your company and location'}
            </p>
            <div className="flex items-center gap-3 mt-3">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-secondary"></div>
                <span className="text-xs text-secondary font-medium">Active</span>
              </div>
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setEditing(true)}
              className="px-5 py-2.5 border border-outline-variant/20 rounded-xl text-sm font-bold text-on-surface-variant hover:text-white hover:border-outline-variant/50 transition-all flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-sm">edit</span>
              Edit Profile
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-8">
        {/* Left — Personal Info */}
        <div className="col-span-12 lg:col-span-5 space-y-8">
          <div className="bg-surface-container-low rounded-xl p-8 border border-outline-variant/5">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-sm font-bold uppercase tracking-widest flex items-center gap-3">
                <span className="w-2 h-6 bg-primary rounded-full"></span>
                Personal Information
              </h2>
              <button
                onClick={() => setEditing(true)}
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                <span className="material-symbols-outlined text-sm">edit</span>
                Edit
              </button>
            </div>
            <div className="space-y-5">
              {([
                { label: 'Full Name', value: profile.name || '—' },
                { label: 'Email',    value: profile.email || user?.primaryEmailAddress?.emailAddress || '—' },
                { label: 'Phone',    value: profile.phone || '—' },
                { label: 'Company',  value: profile.company || '—' },
                { label: 'Location', value: profile.location || '—' },
                { label: 'Role',     value: profile.role || '—' },
              ] as const).map((item) => (
                <div key={item.label} className="flex items-center justify-between py-2 border-b border-outline-variant/5 last:border-none">
                  <div>
                    <p className="text-[10px] font-semibold text-outline uppercase tracking-wider">{item.label}</p>
                    <p className="text-sm text-on-surface">{item.value}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right — Security */}
        <div className="col-span-12 lg:col-span-7 space-y-8">
          <div className="bg-surface-container-low rounded-xl p-8 border border-outline-variant/5">
            <h2 className="text-sm font-bold uppercase tracking-widest mb-6 flex items-center gap-3">
              <span className="w-2 h-6 bg-tertiary rounded-full"></span>
              Account
            </h2>
            <div className="space-y-5">
              <div className="flex items-center justify-between py-3 px-4 bg-surface-container rounded-xl">
                <div>
                  <p className="text-xs font-bold">Email address</p>
                  <p className="text-[11px] text-on-surface-variant">{user?.primaryEmailAddress?.emailAddress ?? '—'}</p>
                </div>
                <span className="text-[10px] text-secondary font-bold uppercase">Verified</span>
              </div>

              <div className="flex items-center justify-between py-3 px-4 bg-surface-container rounded-xl">
                <div>
                  <p className="text-xs font-bold">Password & Security</p>
                  <p className="text-[11px] text-on-surface-variant">Managed by Clerk</p>
                </div>
              </div>

              <div className="flex items-center justify-between py-3 px-4 bg-surface-container rounded-xl">
                <div>
                  <p className="text-xs font-bold">Sign-in method</p>
                  <p className="text-[11px] text-on-surface-variant capitalize">
                    {user?.externalAccounts?.[0]?.provider ?? 'Email'}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Danger Zone */}
          <div className="bg-surface-container-low rounded-xl p-8 border border-error/20">
            <h2 className="text-sm font-bold uppercase tracking-widest text-error mb-4">Danger Zone</h2>
            <p className="text-xs text-on-surface-variant mb-4">
              Permanently delete your account and all associated data. This cannot be undone.
            </p>
            <button className="px-5 py-2.5 border border-error/30 text-error rounded-xl text-sm font-bold hover:bg-error/10 transition-colors">
              Delete Account
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
