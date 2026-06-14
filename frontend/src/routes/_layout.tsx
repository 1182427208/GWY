import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const router = useRouterState()
  const isGwyArea = router.location.pathname.startsWith("/gwy/")

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          isGwyArea && "bg-gradient-to-br from-slate-50 via-white to-sky-50/60",
          isGwyArea && "h-svh overflow-hidden",
        )}
      >
        {!isGwyArea ? (
          <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4 backdrop-blur">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
          </header>
        ) : null}
        <main
          className={cn(
            "flex min-h-0 flex-1 flex-col",
            "overflow-y-auto",
            isGwyArea ? "p-0" : "p-6 md:p-8",
          )}
        >
          <div
            className={cn(
              isGwyArea ? "min-h-full w-full" : "mx-auto max-w-7xl",
            )}
          >
            <Outlet />
          </div>
        </main>
        {!isGwyArea ? <Footer /> : null}
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
