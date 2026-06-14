import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Copy,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { OpenAPI } from "@/client"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

type GwyUserProfileResponse = {
  id: string
  user_id: string
  education: string | null
  degree: string | null
  major: string | null
  political_status: string | null
  is_fresh_graduate: boolean
  grassroots_experience_years: number | null
  target_regions: string[]
  avoid_conditions: string[]
  desired_departments: string[]
  desired_positions: string[]
  excluded_positions: string[]
  daily_study_hours: number | null
  notes: string | null
  feishu_webhook_url: string | null
}

type GwyUserProfileUpdateRequest = {
  education?: string | null
  degree?: string | null
  major?: string | null
  political_status?: string | null
  is_fresh_graduate?: boolean | null
  grassroots_experience_years?: number | null
  target_regions?: string[] | null
  avoid_conditions?: string[] | null
  desired_departments?: string[] | null
  desired_positions?: string[] | null
  excluded_positions?: string[] | null
  daily_study_hours?: number | null
  notes?: string | null
  feishu_webhook_url?: string | null
}

type FeishuWebhookTestResponse = {
  status: string
  detail: string
  response_json: Record<string, unknown>
  trace: Array<Record<string, unknown>>
}

const listFieldSchema = z
  .string()
  .max(2000, { message: "内容太长了，建议拆短一点" })
  .default("")

const optionalWebhookSchema = z
  .string()
  .max(2048, { message: "飞书 Webhook 地址太长了" })
  .refine((value) => !value || /^https?:\/\/.+/i.test(value), {
    message: "请输入有效的飞书 Webhook 地址",
  })
  .default("")

const formSchema = z.object({
  education: z.string().max(255).default(""),
  degree: z.string().max(255).default(""),
  major: z.string().max(255).default(""),
  political_status: z.string().max(255).default(""),
  is_fresh_graduate: z.boolean().default(false),
  grassroots_experience_years: z
    .string()
    .regex(/^\d*$/, { message: "请输入非负整数" })
    .default(""),
  target_regions: listFieldSchema,
  avoid_conditions: listFieldSchema,
  desired_departments: listFieldSchema,
  desired_positions: listFieldSchema,
  excluded_positions: listFieldSchema,
  daily_study_hours: z
    .string()
    .regex(/^\d*$/, { message: "请输入非负整数" })
    .default(""),
  notes: z.string().max(4000).default(""),
  feishu_webhook_url: optionalWebhookSchema,
})

type FormValues = z.input<typeof formSchema>
type FormData = z.output<typeof formSchema>

const apiBase = (OpenAPI.BASE || "").replace(/\/$/, "")

function splitListText(value: string): string[] {
  return value
    .split(/[\n,，]+/g)
    .map((item) => item.trim())
    .filter(Boolean)
}

function joinListText(values: string[] | null | undefined): string {
  return (values || []).join("\n")
}

function toOptionalNumber(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number.parseInt(trimmed, 10)
  return Number.isFinite(parsed) ? parsed : null
}

function toProfileFormData(profile: GwyUserProfileResponse): FormValues {
  return {
    education: profile.education ?? "",
    degree: profile.degree ?? "",
    major: profile.major ?? "",
    political_status: profile.political_status ?? "",
    is_fresh_graduate: profile.is_fresh_graduate,
    grassroots_experience_years:
      profile.grassroots_experience_years?.toString() ?? "",
    target_regions: joinListText(profile.target_regions),
    avoid_conditions: joinListText(profile.avoid_conditions),
    desired_departments: joinListText(profile.desired_departments),
    desired_positions: joinListText(profile.desired_positions),
    excluded_positions: joinListText(profile.excluded_positions),
    daily_study_hours: profile.daily_study_hours?.toString() ?? "",
    notes: profile.notes ?? "",
    feishu_webhook_url: profile.feishu_webhook_url ?? "",
  }
}

const shellClass =
  "rounded-2xl border border-slate-200/80 bg-white/95 shadow-sm shadow-slate-200/40"

const fieldClass =
  "min-h-24 w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm outline-none transition-colors placeholder:text-slate-400 focus-visible:border-slate-400 focus-visible:ring-[3px] focus-visible:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-50"

const compactFieldClass =
  "rounded-xl border border-slate-200 bg-white shadow-sm focus-visible:border-slate-400 focus-visible:ring-[3px] focus-visible:ring-slate-200"

const GwyProfile = () => {
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const profileQuery = useQuery({
    queryKey: ["gwy-profile"],
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const response = await fetch(`${apiBase}/api/v1/gwy/profile/me`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
        },
      })

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payload?.detail || `读取用户画像失败，状态码 ${response.status}`,
        )
      }

      return (await response.json()) as GwyUserProfileResponse
    },
  })

  const form = useForm<FormValues, unknown, FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      education: "",
      degree: "",
      major: "",
      political_status: "",
      is_fresh_graduate: false,
      grassroots_experience_years: "",
      target_regions: "",
      avoid_conditions: "",
      desired_departments: "",
      desired_positions: "",
      excluded_positions: "",
      daily_study_hours: "",
      notes: "",
      feishu_webhook_url: "",
    },
  })

  const feishuWebhookUrl = (form.watch("feishu_webhook_url") ?? "").trim()
  const feishuConfigured = Boolean(feishuWebhookUrl)

  useEffect(() => {
    if (profileQuery.data) {
      form.reset(toProfileFormData(profileQuery.data))
    }
  }, [form, profileQuery.data])

  const mutation = useMutation({
    mutationFn: async (data: FormData) => {
      const payload: GwyUserProfileUpdateRequest = {
        education: data.education.trim() || null,
        degree: data.degree.trim() || null,
        major: data.major.trim() || null,
        political_status: data.political_status.trim() || null,
        is_fresh_graduate: data.is_fresh_graduate,
        grassroots_experience_years: toOptionalNumber(
          data.grassroots_experience_years,
        ),
        target_regions: splitListText(data.target_regions),
        avoid_conditions: splitListText(data.avoid_conditions),
        desired_departments: splitListText(data.desired_departments),
        desired_positions: splitListText(data.desired_positions),
        excluded_positions: splitListText(data.excluded_positions),
        daily_study_hours: toOptionalNumber(data.daily_study_hours),
        notes: data.notes.trim() || null,
        feishu_webhook_url: data.feishu_webhook_url.trim() || null,
      }

      const response = await fetch(`${apiBase}/api/v1/gwy/profile/me`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
        },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        const payloadData = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payloadData?.detail || `保存用户画像失败，状态码 ${response.status}`,
        )
      }

      return (await response.json()) as GwyUserProfileResponse
    },
    onSuccess: (data) => {
      showSuccessToast("用户画像已保存")
      form.reset(toProfileFormData(data))
    },
    onError: handleError.bind(showErrorToast),
  })

  const feishuTestMutation = useMutation({
    mutationFn: async () => {
      const webhookUrl =
        (form.getValues("feishu_webhook_url") ?? "").trim() || null
      const response = await fetch(
        `${apiBase}/api/v1/gwy/profile/me/feishu/test`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
          },
          body: JSON.stringify({ webhook_url: webhookUrl }),
        },
      )

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payload?.detail || `飞书测试失败，状态码 ${response.status}`,
        )
      }

      return (await response.json()) as FeishuWebhookTestResponse
    },
    onSuccess: (data) => {
      showSuccessToast(data.detail || "飞书连接测试成功")
    },
    onError: handleError.bind(showErrorToast),
  })

  const errorMessage =
    profileQuery.error instanceof Error ? profileQuery.error.message : null

  const summaryItems = profileQuery.data
    ? [
        {
          label: "学历 / 学位",
          value: `${profileQuery.data.education || "未填"} / ${
            profileQuery.data.degree || "未填"
          }`,
        },
        {
          label: "专业",
          value: profileQuery.data.major || "未填",
        },
        {
          label: "政治面貌",
          value: profileQuery.data.political_status || "未填",
        },
        {
          label: "目标地区",
          value:
            profileQuery.data.target_regions.length > 0
              ? profileQuery.data.target_regions.join("、")
              : "未填",
        },
      ]
    : []

  const clipboardUrl = feishuWebhookUrl || "未配置"

  const copyWebhookUrl = async () => {
    if (!feishuWebhookUrl) {
      showErrorToast("当前还没有配置飞书 Webhook 地址")
      return
    }

    try {
      await navigator.clipboard.writeText(feishuWebhookUrl)
      showSuccessToast("飞书 Webhook 已复制")
    } catch {
      showErrorToast("复制失败，请手动选择复制")
    }
  }

  return (
    <div className="w-full space-y-5">
      <div className="rounded-3xl border border-slate-200/80 bg-gradient-to-br from-white via-slate-50 to-slate-100 px-5 py-5 shadow-sm shadow-slate-200/40">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 shadow-sm">
              <Sparkles className="size-3.5" />
              公考画像
            </div>
            <div className="space-y-2">
              <h3 className="text-2xl font-semibold tracking-tight text-slate-900">
                用户画像
              </h3>
              <p className="text-sm leading-6 text-slate-600">
                这里保存你的报考基础信息、目标偏好和飞书通知地址。保存后会自动参与岗位推荐和后续分析。
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {summaryItems.map((item) => (
                <div
                  key={item.label}
                  className="rounded-2xl border border-slate-200 bg-white/90 px-3 py-2 shadow-sm"
                >
                  <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">
                    {item.label}
                  </p>
                  <p className="mt-1 text-sm font-medium text-slate-900">
                    {item.value}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900">飞书 URL</p>
                <p className="text-xs text-slate-500">
                  配置后可用于分析结果通知和测试消息。
                </p>
              </div>
              <span
                className={cn(
                  "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium",
                  feishuConfigured
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-slate-100 text-slate-500",
                )}
              >
                {feishuConfigured ? "已配置" : "未配置"}
              </span>
            </div>

            <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">
                当前地址
              </p>
              <p className="mt-1 break-all font-mono text-xs leading-5 text-slate-700">
                {clipboardUrl}
              </p>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={copyWebhookUrl}
                disabled={!feishuConfigured}
              >
                <Copy className="size-4" />
                复制
              </Button>
              <LoadingButton
                type="button"
                variant="outline"
                size="sm"
                loading={feishuTestMutation.isPending}
                onClick={() => feishuTestMutation.mutate()}
                disabled={mutation.isPending || profileQuery.isLoading}
              >
                <ExternalLink className="size-4" />
                测试连接
              </LoadingButton>
            </div>
          </div>
        </div>
      </div>

      {errorMessage ? (
        <p className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {errorMessage}
        </p>
      ) : null}

      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((data) => mutation.mutate(data))}
          className="space-y-5"
        >
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
            <section className={shellClass}>
              <div className="border-b border-slate-200/80 px-5 py-4">
                <h4 className="text-sm font-semibold text-slate-900">
                  基础信息
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  这些字段会直接参与职位过滤、资格判断和最终分析。
                </p>
              </div>

              <div className="space-y-5 px-5 py-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="education"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>学历</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            placeholder="本科"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="degree"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>学位</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            placeholder="学士"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="major"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>专业</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            placeholder="法学"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="political_status"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>政治面貌</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            placeholder="中共党员"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="grassroots_experience_years"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>基层经历年限</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            type="text"
                            inputMode="numeric"
                            placeholder="0"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="daily_study_hours"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>每日学习时长</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            type="text"
                            inputMode="numeric"
                            placeholder="3"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <FormField
                  control={form.control}
                  name="is_fresh_graduate"
                  render={({ field }) => (
                    <FormItem className="flex flex-row items-start gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3">
                      <FormControl>
                        <Checkbox
                          checked={field.value}
                          onCheckedChange={(checked) =>
                            field.onChange(Boolean(checked))
                          }
                        />
                      </FormControl>
                      <div className="space-y-1 leading-none">
                        <FormLabel>应届生身份</FormLabel>
                        <p className="text-sm text-slate-500">
                          开启后，推荐和分析会优先按应届条件判断。
                        </p>
                      </div>
                    </FormItem>
                  )}
                />

                <div className="grid gap-4 md:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="target_regions"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>目标地区</FormLabel>
                        <FormControl>
                          <textarea
                            className={fieldClass}
                            placeholder={"北京\n上海\n广东"}
                            {...field}
                          />
                        </FormControl>
                        <p className="text-xs text-slate-500">
                          一行一个，或者用逗号分隔。
                        </p>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="avoid_conditions"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>避开条件</FormLabel>
                        <FormControl>
                          <textarea
                            className={fieldClass}
                            placeholder={"基层岗位\n夜班\n驻外"}
                            {...field}
                          />
                        </FormControl>
                        <p className="text-xs text-slate-500">
                          写上明确不接受的条件，便于过滤和解释。
                        </p>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="desired_departments"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>偏好部门</FormLabel>
                        <FormControl>
                          <textarea
                            className={fieldClass}
                            placeholder={"税务局\n发改委"}
                            {...field}
                          />
                        </FormControl>
                        <p className="text-xs text-slate-500">
                          可以写部门名、单位名或者关键词。
                        </p>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="desired_positions"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>偏好岗位</FormLabel>
                        <FormControl>
                          <textarea
                            className={fieldClass}
                            placeholder={"综合管理\n文字综合"}
                            {...field}
                          />
                        </FormControl>
                        <p className="text-xs text-slate-500">
                          用于辅助排序和最终推荐。
                        </p>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <FormField
                  control={form.control}
                  name="excluded_positions"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>排除岗位</FormLabel>
                      <FormControl>
                        <textarea
                          className={fieldClass}
                          placeholder={"执法岗\n值班岗"}
                          {...field}
                        />
                      </FormControl>
                      <p className="text-xs text-slate-500">
                        明确不考虑的岗位可以直接写在这里。
                      </p>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="notes"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>补充说明</FormLabel>
                      <FormControl>
                        <textarea
                          className={cn(fieldClass, "min-h-28")}
                          placeholder="例如：优先考虑省会城市，能接受加班，但不考虑夜班。"
                          {...field}
                        />
                      </FormControl>
                      <p className="text-xs text-slate-500">
                        这部分会被分析页一起读取，方便补充个性化偏好。
                      </p>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </section>

            <aside className="space-y-5">
              <section className={shellClass}>
                <div className="border-b border-slate-200/80 px-5 py-4">
                  <h4 className="text-sm font-semibold text-slate-900">
                    飞书通知
                  </h4>
                  <p className="mt-1 text-xs text-slate-500">
                    把 Webhook 地址放这里，保存后就能复用到分析结果通知。
                  </p>
                </div>

                <div className="space-y-4 px-5 py-5">
                  <FormField
                    control={form.control}
                    name="feishu_webhook_url"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Webhook 地址</FormLabel>
                        <FormControl>
                          <Input
                            className={compactFieldClass}
                            type="url"
                            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
                            {...field}
                          />
                        </FormControl>
                        <p className="text-xs text-slate-500">
                          留空表示不启用飞书通知。
                        </p>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">
                          当前状态
                        </p>
                        <p className="mt-1 text-sm font-medium text-slate-900">
                          {feishuConfigured
                            ? "已配置飞书 URL"
                            : "暂未配置飞书 URL"}
                        </p>
                      </div>
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
                          feishuConfigured
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-slate-200 text-slate-600",
                        )}
                      >
                        {feishuConfigured ? "启用" : "关闭"}
                      </span>
                    </div>
                    <div className="mt-3 flex items-start gap-2 rounded-xl border border-dashed border-slate-200 bg-white px-3 py-2">
                      <ShieldCheck className="mt-0.5 size-4 shrink-0 text-slate-400" />
                      <p className="break-all font-mono text-xs leading-5 text-slate-700">
                        {clipboardUrl}
                      </p>
                    </div>
                  </div>

                  <LoadingButton
                    type="button"
                    variant="outline"
                    loading={feishuTestMutation.isPending}
                    onClick={() => feishuTestMutation.mutate()}
                    disabled={mutation.isPending || profileQuery.isLoading}
                    className="w-full"
                  >
                    <RefreshCw className="size-4" />
                    测试飞书连接
                  </LoadingButton>
                </div>
              </section>
            </aside>
          </div>

          <div className={shellClass}>
            <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <p className="text-sm font-medium text-slate-900">
                  保存当前用户画像
                </p>
                <p className="text-xs text-slate-500">
                  保存后会自动用于岗位推荐、报告分析和飞书通知。
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    if (profileQuery.data) {
                      form.reset(toProfileFormData(profileQuery.data))
                    }
                  }}
                  disabled={mutation.isPending || profileQuery.isLoading}
                >
                  重置
                </Button>
                <LoadingButton type="submit" loading={mutation.isPending}>
                  保存画像
                </LoadingButton>
              </div>
            </div>
          </div>
        </form>
      </Form>
    </div>
  )
}

export default GwyProfile
