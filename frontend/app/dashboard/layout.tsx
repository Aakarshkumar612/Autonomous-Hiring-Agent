import Sidebar from '@/components/Sidebar'
import DashboardHeader from '@/components/DashboardHeader'
import KeepAlive from '@/components/KeepAlive'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <KeepAlive />
      <Sidebar />
      <DashboardHeader />
      <main className="ml-[256px] pt-16 min-h-screen relative">
        {/* Background ambient glows */}
        <div className="fixed top-0 right-0 w-[600px] h-[600px] bg-primary-container/5 rounded-full blur-[120px] -z-10 pointer-events-none"></div>
        <div className="fixed bottom-1/4 left-1/4 w-[400px] h-[400px] bg-secondary/5 rounded-full blur-[120px] -z-10 pointer-events-none"></div>
        {children}
      </main>
    </div>
  )
}
