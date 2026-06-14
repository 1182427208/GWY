import { createFileRoute } from "@tanstack/react-router"
import ChangePassword from "@/components/UserSettings/ChangePassword"
import DeleteAccount from "@/components/UserSettings/DeleteAccount"
import GwyProfile from "@/components/UserSettings/GwyProfile"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

const tabsConfig = [
  { value: "my-profile", title: "基本信息", component: UserInformation },
  { value: "gwy-profile", title: "用户画像", component: GwyProfile },
  { value: "password", title: "密码", component: ChangePassword },
  { value: "danger-zone", title: "危险操作", component: DeleteAccount },
]

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  head: () => ({
    meta: [
      {
        title: "Settings - FastAPI Template",
      },
    ],
  }),
})

function UserSettings() {
  const { user: currentUser } = useAuth()
  const finalTabs = currentUser?.is_superuser
    ? tabsConfig.slice(0, 3)
    : tabsConfig

  if (!currentUser) {
    return null
  }

  return (
    <div className="flex w-full flex-col gap-4 pb-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">用户设置</h1>
        <p className="text-muted-foreground">
          管理账号信息、用户画像和安全设置
        </p>
      </div>

      <Tabs defaultValue="my-profile" className="w-full gap-4">
        <TabsList className="grid h-auto w-full grid-cols-2 gap-2 rounded-2xl bg-slate-100 p-2 md:grid-cols-4">
          {finalTabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {finalTabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value} className="w-full">
            <tab.component />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
