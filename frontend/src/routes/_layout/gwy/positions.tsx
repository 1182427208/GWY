import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  ArrowLeftRight,
  CheckSquare2,
  ChevronLeft,
  ChevronRight,
  Filter,
  RefreshCw,
  Search,
  Sparkles,
  Table2,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { GwyAnalysisService, OpenAPI } from "@/client"
import { GwyPositionsExcelPage } from "@/components/GwyPositionsExcelPage"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

type PositionRow = {
  id: string
  department_code?: string | null
  department_name?: string | null
  office_name?: string | null
  institution_type?: string | null
  job_title?: string | null
  position_attribute?: string | null
  position_distribution?: string | null
  position_desc?: string | null
  position_code?: string | null
  institution_level?: string | null
  exam_category?: string | null
  recruit_count?: number | null
  major_requirement?: string | null
  education_requirement?: string | null
  degree_requirement?: string | null
  political_status_requirement?: string | null
  grassroots_years_requirement?: string | null
  grassroots_project_experience?: string | null
  professional_test_in_interview?: string | null
  interview_ratio?: string | null
  work_location?: string | null
  household_registration_location?: string | null
  remarks?: string | null
  department_website?: string | null
  contact_phone_1?: string | null
  contact_phone_2?: string | null
  contact_phone_3?: string | null
  source_file?: string | null
  source_sheet?: string | null
  source_row_number?: number | null
}

type PositionListResponse = {
  data: PositionRow[]
  count: number
  page: number
  page_size: number
  filters: Record<string, unknown>
}

type PositionAnalyzeRecord = PositionRow & {
  position_id?: string | null
  score?: number | null
  recommend_level?: string | null
  risk_level?: string | null
  need_manual_confirm?: boolean | null
  reasons?: { type?: string | null; text?: string | null }[]
  risks?: { type?: string | null; text?: string | null }[]
  hard_filter_passed?: boolean
  hard_filter_reasons?: string[]
  hard_filter_risks?: string[]
}

type PositionAnalyzeResponse = {
  analysis: string
  summary: Record<string, unknown>
  recommendations: PositionAnalyzeRecord[]
  selected_positions: PositionAnalyzeRecord[]
  retrieval_trace: Record<string, unknown>[]
}

type PositionFilters = {
  major: string
  education: string
  degree: string
  political_status: string
  region: string
  department: string
  job_title: string
}

const DEFAULT_FILTERS: PositionFilters = {
  major: "",
  education: "",
  degree: "",
  political_status: "",
  region: "",
  department: "",
  job_title: "",
}

const MAJOR_OPTIONS = [
  "工学",
  "理学",
  "法学",
  "经济学",
  "管理学",
  "文学",
  "教育学",
  "医学",
  "农学",
  "哲学",
  "历史学",
  "艺术学",
]

const EDUCATION_OPTIONS = [
  "不限",
  "专科",
  "本科",
  "硕士研究生",
  "硕士研究生及以上",
]

const DEGREE_OPTIONS = ["不限", "学士", "硕士", "博士"]

const POLITICAL_STATUS_OPTIONS = [
  "不限",
  "中共党员",
  "中共预备党员",
  "共青团员",
  "群众",
]

const REGION_OPTIONS = [
  "北京",
  "北京市",
  "上海",
  "上海市",
  "广东",
  "广东省",
  "江苏",
  "江苏省",
  "浙江",
  "浙江省",
  "山东",
  "山东省",
  "四川",
  "四川省",
  "湖北",
  "湖北省",
  "陕西",
  "陕西省",
  "天津",
  "天津市",
  "重庆",
  "重庆市",
]

const PAGE_SIZE_OPTIONS = [10, 20, 50]

export const Route = createFileRoute("/_layout/gwy/positions")({
  component: GwyPositionsExcelPage,
  head: () => ({
    meta: [
      {
        title: "岗位总表 - GwyPilot",
      },
    ],
  }),
})

void GwyPositionsPage

function GwyPositionsPage() {
  const navigate = useNavigate()
  const apiBase = (OpenAPI.BASE || "").replace(/\/$/, "")
  const [draftFilters, setDraftFilters] =
    useState<PositionFilters>(DEFAULT_FILTERS)
  const [appliedFilters, setAppliedFilters] =
    useState<PositionFilters>(DEFAULT_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [rows, setRows] = useState<PositionRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [analysisQuery, setAnalysisQuery] = useState(
    "请结合我当前筛选出的岗位，给出推荐顺序、匹配原因和风险提示。",
  )
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [analysisResult, setAnalysisResult] =
    useState<PositionAnalyzeResponse | null>(null)

  const pageCount = useMemo(() => {
    return Math.max(1, Math.ceil(total / pageSize))
  }, [pageSize, total])

  const currentPageSelected = useMemo(() => {
    return rows.length > 0 && rows.every((row) => selectedIds.has(row.id))
  }, [rows, selectedIds])

  const currentPageSelectedSome = useMemo(() => {
    return rows.some((row) => selectedIds.has(row.id)) && !currentPageSelected
  }, [rows, selectedIds, currentPageSelected])

  const buildQueryParams = useCallback(
    (filters: PositionFilters, nextPage: number, nextPageSize: number) => {
      const params = new URLSearchParams()
      params.set("year", "2026")
      params.set("page", String(nextPage))
      params.set("page_size", String(nextPageSize))
      if (filters.major) params.set("major", filters.major)
      if (filters.education) params.set("education", filters.education)
      if (filters.degree) params.set("degree", filters.degree)
      if (filters.political_status)
        params.set("political_status", filters.political_status)
      if (filters.region) params.set("region", filters.region)
      if (filters.department) params.set("department", filters.department)
      if (filters.job_title) params.set("job_title", filters.job_title)
      return params
    },
    [],
  )

  const loadPositions = useCallback(
    async (
      filters: PositionFilters,
      nextPage: number,
      nextPageSize: number,
      signal?: AbortSignal,
    ) => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch(
          `${apiBase}/api/v1/gwy/positions?${buildQueryParams(
            filters,
            nextPage,
            nextPageSize,
          ).toString()}`,
          {
            headers: {
              Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
            },
            signal,
          },
        )
        if (!response.ok) {
          throw new Error(`岗位列表加载失败：HTTP ${response.status}`)
        }
        const payload = (await response.json()) as PositionListResponse
        setRows(payload.data || [])
        setTotal(payload.count || 0)
        setPage(payload.page || nextPage)
        setPageSize(payload.page_size || nextPageSize)
      } catch (fetchError) {
        if (signal?.aborted) {
          return
        }
        setError(
          fetchError instanceof Error
            ? fetchError.message
            : "岗位列表加载失败，请稍后再试",
        )
      } finally {
        if (!signal?.aborted) {
          setLoading(false)
        }
      }
    },
    [apiBase, buildQueryParams],
  )

  useEffect(() => {
    const controller = new AbortController()
    void loadPositions(appliedFilters, page, pageSize, controller.signal)
    return () => controller.abort()
  }, [appliedFilters, loadPositions, page, pageSize])

  const applyFilters = () => {
    setAnalysisResult(null)
    setAnalysisError(null)
    setSelectedIds(new Set())
    setAppliedFilters({ ...draftFilters })
    setPage(1)
  }

  const resetFilters = () => {
    setDraftFilters(DEFAULT_FILTERS)
    setAnalysisResult(null)
    setAnalysisError(null)
    setSelectedIds(new Set())
    setAppliedFilters(DEFAULT_FILTERS)
    setPage(1)
    setPageSize(20)
  }

  const toggleRow = (rowId: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (checked) {
        next.add(rowId)
      } else {
        next.delete(rowId)
      }
      return next
    })
  }

  const toggleCurrentPage = (checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      for (const row of rows) {
        if (checked) {
          next.add(row.id)
        } else {
          next.delete(row.id)
        }
      }
      return next
    })
  }

  const analyzeSelected = async () => {
    if (selectedIds.size === 0) {
      setAnalysisError("请先勾选至少一条岗位。")
      return
    }
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const response = await GwyAnalysisService.createPositionAnalysisTask({
        requestBody: buildAnalysisTaskRequest({
          query: analysisQuery,
          selectedIds: Array.from(selectedIds),
          filters: appliedFilters,
          selectionRows: selectionSummary,
        }),
      })
      setAnalysisResult(null)
      await navigate({
        to: "/gwy/analysis",
        search: { task_id: response.task_id },
      })
    } catch (analysisFetchError) {
      setAnalysisError(
        analysisFetchError instanceof Error
          ? analysisFetchError.message
          : "岗位分析失败，请稍后再试",
      )
    } finally {
      setAnalysisLoading(false)
    }
  }

  const selectionSummary = useMemo(() => {
    return rows.filter((row) => selectedIds.has(row.id))
  }, [rows, selectedIds])

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6">
      <div className="rounded-3xl border border-slate-200 bg-gradient-to-r from-white via-sky-50/60 to-white px-5 py-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-slate-900">
              <Table2 className="h-5 w-5 text-sky-600" />
              <h1 className="text-xl font-semibold">岗位推荐</h1>
            </div>
            <p className="text-sm text-slate-500">
              像 Excel 一样筛选岗位，勾选后再做匹配分析，全部基于 PostgreSQL
              职位表。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant="outline" className="bg-white">
              共 {total} 条
            </Badge>
            <Badge variant="outline" className="bg-white">
              当前页 {rows.length} 条
            </Badge>
            <Badge variant="outline" className="bg-white">
              已选 {selectedIds.size} 条
            </Badge>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-h-0 flex-col gap-4">
          <Card className="border-slate-200 shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <Filter className="h-4 w-4 text-sky-600" />
                筛选条件
              </CardTitle>
              <CardDescription>
                先缩小范围，再让系统分析选中的岗位。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <FilterSelect
                  label="专业"
                  value={draftFilters.major}
                  options={MAJOR_OPTIONS}
                  placeholder="请选择专业"
                  onValueChange={(value) =>
                    setDraftFilters((current) => ({ ...current, major: value }))
                  }
                />
                <FilterSelect
                  label="学历"
                  value={draftFilters.education}
                  options={EDUCATION_OPTIONS}
                  placeholder="请选择学历"
                  onValueChange={(value) =>
                    setDraftFilters((current) => ({
                      ...current,
                      education: value,
                    }))
                  }
                />
                <FilterSelect
                  label="学位"
                  value={draftFilters.degree}
                  options={DEGREE_OPTIONS}
                  placeholder="请选择学位"
                  onValueChange={(value) =>
                    setDraftFilters((current) => ({
                      ...current,
                      degree: value,
                    }))
                  }
                />
                <FilterSelect
                  label="政治面貌"
                  value={draftFilters.political_status}
                  options={POLITICAL_STATUS_OPTIONS}
                  placeholder="请选择政治面貌"
                  onValueChange={(value) =>
                    setDraftFilters((current) => ({
                      ...current,
                      political_status: value,
                    }))
                  }
                />
                <FilterSelect
                  label="地区偏好"
                  value={draftFilters.region}
                  options={REGION_OPTIONS}
                  placeholder="请选择地区"
                  onValueChange={(value) =>
                    setDraftFilters((current) => ({
                      ...current,
                      region: value,
                    }))
                  }
                />
                <FilterInput
                  label="部门关键词"
                  value={draftFilters.department}
                  placeholder="例如：发展改革委"
                  onChange={(value) =>
                    setDraftFilters((current) => ({
                      ...current,
                      department: value,
                    }))
                  }
                />
                <FilterInput
                  label="岗位关键词"
                  value={draftFilters.job_title}
                  placeholder="例如：一级主任科员"
                  onChange={(value) =>
                    setDraftFilters((current) => ({
                      ...current,
                      job_title: value,
                    }))
                  }
                />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button onClick={applyFilters} className="gap-2">
                  <Search className="h-4 w-4" />
                  查询
                </Button>
                <Button
                  variant="outline"
                  onClick={resetFilters}
                  className="gap-2"
                >
                  <RefreshCw className="h-4 w-4" />
                  重置
                </Button>
                <div className="ml-auto text-xs text-slate-500">
                  查询会自动按 2026 年岗位表筛选
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="min-h-0 flex-1 border-slate-200 shadow-sm">
            <CardHeader className="border-b pb-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-base">岗位列表</CardTitle>
                  <CardDescription>
                    支持分页、勾选和按当前页全选
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <span>每页</span>
                  <Select
                    value={String(pageSize)}
                    onValueChange={(value) => {
                      setPage(1)
                      setPageSize(Number(value))
                    }}
                  >
                    <SelectTrigger className="w-[110px]">
                      <SelectValue placeholder="20" />
                    </SelectTrigger>
                    <SelectContent>
                      {PAGE_SIZE_OPTIONS.map((option) => (
                        <SelectItem key={option} value={String(option)}>
                          {option} 条
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardHeader>
            <CardContent className="min-h-0 pt-4">
              {error ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}

              <div className="min-h-0 overflow-hidden rounded-2xl border border-slate-200">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">
                        <Checkbox
                          checked={
                            currentPageSelected
                              ? true
                              : currentPageSelectedSome
                                ? "indeterminate"
                                : false
                          }
                          onCheckedChange={(checked) =>
                            toggleCurrentPage(checked === true)
                          }
                        />
                      </TableHead>
                      <TableHead className="min-w-[220px]">部门</TableHead>
                      <TableHead className="min-w-[200px]">岗位</TableHead>
                      <TableHead className="min-w-[260px]">专业要求</TableHead>
                      <TableHead className="min-w-[130px]">
                        学历 / 学位
                      </TableHead>
                      <TableHead className="min-w-[120px]">地区</TableHead>
                      <TableHead className="min-w-[90px]">招录</TableHead>
                      <TableHead className="min-w-[180px]">备注</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {loading ? (
                      <TableRow>
                        <TableCell colSpan={8} className="py-10 text-center">
                          正在加载岗位数据...
                        </TableCell>
                      </TableRow>
                    ) : rows.length ? (
                      rows.map((row) => {
                        const isSelected = selectedIds.has(row.id)
                        return (
                          <TableRow
                            key={row.id}
                            data-state={isSelected ? "selected" : undefined}
                            className={cn(isSelected && "bg-sky-50/60")}
                          >
                            <TableCell>
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={(checked) =>
                                  toggleRow(row.id, checked === true)
                                }
                              />
                            </TableCell>
                            <TableCell className="whitespace-normal">
                              <div className="space-y-1">
                                <div className="font-medium text-slate-900">
                                  {row.department_name || "未填写"}
                                </div>
                                <div className="text-xs text-slate-500">
                                  {row.office_name || "无办公处室信息"} ·
                                  {row.position_code ||
                                    row.department_code ||
                                    "无代码"}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="whitespace-normal">
                              <div className="space-y-1">
                                <div className="font-medium text-slate-900">
                                  {row.job_title || "未填写"}
                                </div>
                                <div className="text-xs text-slate-500">
                                  {row.position_attribute || "普通职位"}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="whitespace-normal text-slate-700">
                              {row.major_requirement || "不限"}
                            </TableCell>
                            <TableCell className="whitespace-normal text-slate-700">
                              <div className="space-y-1">
                                <div>{row.education_requirement || "不限"}</div>
                                <div className="text-xs text-slate-500">
                                  {row.degree_requirement || "不限"}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="whitespace-normal text-slate-700">
                              {row.work_location ||
                                row.position_distribution ||
                                row.household_registration_location ||
                                "未填写"}
                            </TableCell>
                            <TableCell className="text-slate-700">
                              {row.recruit_count ?? "未填"}
                            </TableCell>
                            <TableCell className="whitespace-normal text-slate-500">
                              {row.remarks || "无"}
                            </TableCell>
                          </TableRow>
                        )
                      })
                    ) : (
                      <TableRow>
                        <TableCell colSpan={8} className="py-10 text-center">
                          暂无符合条件的岗位，请尝试放宽筛选条件。
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
                <div>
                  第 {page} / {pageCount} 页，共 {total} 条
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPage((current) => Math.max(1, current - 1))
                    }
                    disabled={page <= 1 || loading}
                  >
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPage((current) => Math.min(pageCount, current + 1))
                    }
                    disabled={page >= pageCount || loading}
                  >
                    下一页
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="flex min-h-0 flex-col gap-4">
          <Card className="border-slate-200 shadow-sm">
            <CardHeader className="pb-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <Sparkles className="h-4 w-4 text-sky-600" />
                选中岗位分析
              </CardTitle>
              <CardDescription>
                勾选岗位后输入你的诉求，再让系统做匹配分析。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                当前已选 {selectedIds.size} 条岗位，当前页选中{" "}
                {selectionSummary.length} 条。
              </div>
              <textarea
                value={analysisQuery}
                onChange={(event) => setAnalysisQuery(event.target.value)}
                className="min-h-[120px] w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
                placeholder="例如：我更看重北京、稳定、工学硕士、党员要求。"
              />
              <div className="flex gap-2">
                <Button
                  onClick={() => {
                    void analyzeSelected()
                  }}
                  disabled={analysisLoading || selectedIds.size === 0}
                  className="flex-1 gap-2"
                >
                  <ArrowLeftRight className="h-4 w-4" />
                  {analysisLoading ? "创建任务中..." : "开始分析并打开报告"}
                </Button>
              </div>
              <div className="text-xs leading-5 text-slate-500">
                点击后会先创建分析任务，然后立刻跳转到报告页，任务完成后页面会自动刷新。
              </div>
              {analysisError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {analysisError}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card className="min-h-0 flex-1 border-slate-200 shadow-sm">
            <CardHeader className="border-b pb-4">
              <CardTitle className="text-base">分析结果</CardTitle>
              <CardDescription>
                这里会展示系统的推荐顺序、理由和风险提示。
              </CardDescription>
            </CardHeader>
            <CardContent className="min-h-0 space-y-4 overflow-y-auto pt-4">
              {analysisResult ? (
                <>
                  <div className="rounded-2xl border border-sky-100 bg-sky-50/70 px-4 py-3 text-sm leading-6 text-slate-700">
                    {analysisResult.analysis}
                  </div>
                  <div className="grid gap-3">
                    {analysisResult.recommendations.map((item, index) => (
                      <Card
                        key={`${item.position_id || item.position_code || index}`}
                        className="border-slate-200 shadow-none"
                      >
                        <CardContent className="space-y-3 px-4 py-4">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="font-semibold text-slate-900">
                                {item.department_name || "未命名部门"}
                              </div>
                              <div className="text-sm text-slate-600">
                                {item.office_name || "无办公处室"} ·{" "}
                                {item.job_title || "岗位名称未知"}
                              </div>
                            </div>
                            <Badge
                              variant="outline"
                              className="bg-white text-slate-700"
                            >
                              {item.score?.toFixed(1) || "0.0"} 分
                            </Badge>
                          </div>
                          <div className="grid gap-2 text-xs text-slate-500">
                            <div>代码：{item.position_code || "无"}</div>
                            <div>
                              地区：
                              {item.work_location ||
                                item.household_registration_location ||
                                "未填写"}
                            </div>
                            <div>专业：{item.major_requirement || "不限"}</div>
                            <div>
                              学历 / 学位：
                              {item.education_requirement || "不限"} /{" "}
                              {item.degree_requirement || "不限"}
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {(item.reasons || []).slice(0, 3).map((reason) => (
                              <Badge
                                key={`${reason.type}-${reason.text}`}
                                variant="secondary"
                              >
                                {reason.text || "匹配"}
                              </Badge>
                            ))}
                            {(item.risks || []).slice(0, 2).map((risk) => (
                              <Badge
                                key={`${risk.type}-${risk.text}`}
                                variant="outline"
                              >
                                {risk.text || "风险"}
                              </Badge>
                            ))}
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </>
              ) : (
                <div className="flex min-h-[260px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 text-center text-sm text-slate-500">
                  <CheckSquare2 className="mb-3 h-9 w-9 text-slate-300" />
                  选中岗位后点击“开始分析”，这里会展示匹配结果。
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function buildAnalysisTaskRequest({
  query,
  selectedIds,
  filters,
  selectionRows,
}: {
  query: string
  selectedIds: string[]
  filters: PositionFilters
  selectionRows: PositionRow[]
}) {
  const visibleColumns = [
    "department_name",
    "office_name",
    "job_title",
    "position_code",
    "recruit_count",
    "education_requirement",
    "degree_requirement",
    "major_requirement",
    "political_status_requirement",
    "work_location",
    "remarks",
  ]

  const filterPayload = {
    major: filters.major || "",
    education: filters.education || "",
    degree: filters.degree || "",
    political_status: filters.political_status || "",
    region: filters.region || "",
    department: filters.department || "",
    job_title: filters.job_title || "",
    year: 2026,
  }

  return {
    title: "2026年岗位智能分析快照",
    source_sheet: "2026年度国考职位表",
    notes: query.trim(),
    filters_json: filterPayload,
    selected_position_ids: selectedIds,
    visible_columns: visibleColumns,
    snapshot_json: {
      title: "2026年岗位智能分析快照",
      source_sheet: "2026年度国考职位表",
      notes: query.trim(),
      filters_json: filterPayload,
      selected_position_ids: selectedIds,
      visible_columns: visibleColumns,
      selected_row_samples: selectionRows.slice(0, 20),
    },
  }
}

function FilterSelect({
  label,
  value,
  options,
  placeholder,
  onValueChange,
}: {
  label: string
  value: string
  options: readonly string[]
  placeholder: string
  onValueChange: (value: string) => void
}) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function FilterInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder: string
  onChange: (value: string) => void
}) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  )
}
