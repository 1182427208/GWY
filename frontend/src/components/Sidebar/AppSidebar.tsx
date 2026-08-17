import {
  BarChart3,
  Briefcase,
  FileText,
  Home,
  MessageSquareText,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  { icon: Briefcase, title: "Items", path: "/items" },
  { icon: MessageSquareText, title: "政策对话", path: "/gwy/chat" },
  { icon: Briefcase, title: "岗位推荐", path: "/gwy/positions" },
  { icon: FileText, title: "岗位分析", path: "/gwy/analysis" },
  { icon: BarChart3, title: "评测分析", path: "/gwy/evals" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const evaluationItem = baseItems[baseItems.length - 1]
  const items = currentUser?.is_superuser
    ? [
        ...baseItems.slice(0, -1),
        { icon: Users, title: "Admin", path: "/admin" },
        evaluationItem,
      ]
    : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
