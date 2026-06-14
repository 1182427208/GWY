import { useNavigate } from "@tanstack/react-router"
import {
  ArrowUpDown,
  Maximize2,
  RefreshCw,
  Search,
  Sparkles,
  Table2,
  X,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { GwyAnalysisService, OpenAPI } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"

const SHEET_NAMES = [
  "中央党群机关",
  "中央国家行政机关（本级）",
  "中央国家行政机关省级以下直属机构",
  "中央国家行政机关参照公务员法管理事业单位",
] as const

type SheetName = (typeof SHEET_NAMES)[number]
type SortDirection = "asc" | "desc"

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
  raw_data?: Record<string, unknown>
}

type PositionListResponse = {
  data: PositionRow[]
  count: number
  page: number
  page_size: number
  filters: Record<string, unknown>
}

type SheetState = {
  filters: Record<string, string>
  sortKey: string
  sortDirection: SortDirection
  pageNumber: number
  pageSize: number
  scrollTop: number
  scrollLeft: number
}

type SavedSheetSnapshot = {
  savedAt: string
  rowCount: number
  rowIds: string[]
  filters: Record<string, string>
  sortKey: string
  sortDirection: SortDirection
}

type PageState = {
  activeSheet: SheetName
  sheets: Record<SheetName, SheetState>
  savedSnapshots: Partial<Record<SheetName, SavedSheetSnapshot>>
}

type ColumnDef = {
  label: string
  key: keyof PositionRow
  width: string
  sortType?: "text" | "number"
}

const ALL_VALUE = "__all__"
const ANALYZE_LIMIT = 300
const LARGE_SHEET_RENDER_THRESHOLD = 1000
const DEFAULT_PAGE_SIZE = 100
const PAGE_SIZE_OPTIONS = [50, 100, 200] as const
const TABLE_MIN_WIDTH = 2100
const DISPLAY_YEAR = 2026

const COLUMN_DEFS: ColumnDef[] = [
  { label: "部门代码", key: "department_code", width: "w-[64px]" },
  { label: "部门名称", key: "department_name", width: "w-[96px]" },
  { label: "用人司局", key: "office_name", width: "w-[88px]" },
  { label: "机构性质", key: "institution_type", width: "w-[72px]" },
  { label: "招考职位", key: "job_title", width: "w-[96px]" },
  { label: "职位属性", key: "position_attribute", width: "w-[64px]" },
  { label: "职位分布", key: "position_distribution", width: "w-[64px]" },
  { label: "职位简介", key: "position_desc", width: "w-[100px]" },
  { label: "职位代码", key: "position_code", width: "w-[64px]" },
  { label: "机构层级", key: "institution_level", width: "w-[64px]" },
  { label: "考试类别", key: "exam_category", width: "w-[64px]" },
  {
    label: "招考人数",
    key: "recruit_count",
    width: "w-[56px]",
    sortType: "number",
  },
  { label: "专业", key: "major_requirement", width: "w-[96px]" },
  { label: "学历", key: "education_requirement", width: "w-[72px]" },
  { label: "学位", key: "degree_requirement", width: "w-[72px]" },
  {
    label: "政治面貌",
    key: "political_status_requirement",
    width: "w-[84px]",
  },
  {
    label: "基层工作最低年限",
    key: "grassroots_years_requirement",
    width: "w-[84px]",
  },
  {
    label: "服务基层项目工作经历",
    key: "grassroots_project_experience",
    width: "w-[96px]",
  },
  {
    label: "是否在面试阶段组织专业能力测试",
    key: "professional_test_in_interview",
    width: "w-[96px]",
  },
  { label: "面试人员比例", key: "interview_ratio", width: "w-[72px]" },
  { label: "工作地点", key: "work_location", width: "w-[84px]" },
  {
    label: "落户地点",
    key: "household_registration_location",
    width: "w-[84px]",
  },
  { label: "备注", key: "remarks", width: "w-[96px]" },
  { label: "部门网站", key: "department_website", width: "w-[100px]" },
  { label: "咨询电话1", key: "contact_phone_1", width: "w-[72px]" },
  { label: "咨询电话2", key: "contact_phone_2", width: "w-[72px]" },
  { label: "咨询电话3", key: "contact_phone_3", width: "w-[72px]" },
]

type PositionsGridCache = {
  rows: PositionRow[]
  lastUpdatedAt: string | null
}

const POSITIONS_GRID_CACHE_STORAGE_KEY = `gwy:positions:grid-cache:v2:${DISPLAY_YEAR}`

let positionsGridCache: PositionsGridCache | null = readPositionsGridCache()
let positionsGridLoadPromise: Promise<PositionsGridCache> | null = null

function getPositionsGridCache(): PositionsGridCache | null {
  if (positionsGridCache) {
    return positionsGridCache
  }
  const cache = readPositionsGridCache()
  if (cache) {
    positionsGridCache = cache
  }
  return cache
}

function readPositionsGridCache(): PositionsGridCache | null {
  if (typeof window === "undefined") {
    return null
  }

  try {
    const raw = window.sessionStorage.getItem(POSITIONS_GRID_CACHE_STORAGE_KEY)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw) as Partial<PositionsGridCache>
    if (!Array.isArray(parsed.rows)) {
      return null
    }
    return {
      rows: parsed.rows as PositionRow[],
      lastUpdatedAt:
        typeof parsed.lastUpdatedAt === "string" ? parsed.lastUpdatedAt : null,
    }
  } catch {
    return null
  }
}

function writePositionsGridCache(cache: PositionsGridCache): void {
  positionsGridCache = cache
  if (typeof window === "undefined") {
    return
  }

  try {
    window.sessionStorage.setItem(
      POSITIONS_GRID_CACHE_STORAGE_KEY,
      JSON.stringify(cache),
    )
  } catch {
    // Best-effort cache only.
  }
}

async function loadPositionsGridFromApi(
  apiBase: string,
  signal?: AbortSignal,
): Promise<PositionsGridCache> {
  if (positionsGridLoadPromise) {
    return positionsGridLoadPromise
  }

  positionsGridLoadPromise = (async () => {
    const response = await fetch(
      `${apiBase}/api/v1/gwy/positions/grid?year=${DISPLAY_YEAR}`,
      {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
        },
        signal,
      },
    )
    if (!response.ok) {
      throw new Error(`岗位总表加载失败：HTTP ${response.status}`)
    }
    const payload = (await response.json()) as PositionListResponse
    const cache = {
      rows: payload.data || [],
      lastUpdatedAt: new Date().toLocaleString("zh-CN"),
    }
    writePositionsGridCache(cache)
    return cache
  })().finally(() => {
    positionsGridLoadPromise = null
  })

  return positionsGridLoadPromise
}

function defaultSheetState(): SheetState {
  return {
    filters: Object.fromEntries(
      COLUMN_DEFS.map((column) => [column.label, ""]),
    ),
    sortKey: "source_row_number",
    sortDirection: "asc",
    pageNumber: 1,
    pageSize: DEFAULT_PAGE_SIZE,
    scrollTop: 0,
    scrollLeft: 0,
  }
}

function defaultPageState(): PageState {
  return {
    activeSheet: SHEET_NAMES[0],
    sheets: Object.fromEntries(
      SHEET_NAMES.map((sheet) => [sheet, defaultSheetState()]),
    ) as Record<SheetName, SheetState>,
    savedSnapshots: {},
  }
}

function groupRowsBySheet(rows: PositionRow[]) {
  const grouped: Record<SheetName, PositionRow[]> = Object.fromEntries(
    SHEET_NAMES.map((sheet) => [sheet, []]),
  ) as unknown as Record<SheetName, PositionRow[]>
  for (const row of rows) {
    const sheet = row.source_sheet as SheetName | undefined
    if (sheet && SHEET_NAMES.includes(sheet)) {
      grouped[sheet].push(row)
    }
  }
  return grouped
}

function getColumnValue(row: PositionRow, column: ColumnDef) {
  const rawValue = row.raw_data?.[column.label]
  if (
    rawValue !== undefined &&
    rawValue !== null &&
    String(rawValue).trim() !== ""
  ) {
    return rawValue
  }
  return row[column.key]
}

function normalizeText(value: string | number | null | undefined) {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, "")
    .toLowerCase()
}

function toDisplayText(value: unknown) {
  if (value === null || value === undefined) {
    return ""
  }
  return String(value).replace(/\s+/g, " ").trim()
}

function compareValues(
  left: PositionRow,
  right: PositionRow,
  sortKey: string,
  sortDirection: SortDirection,
) {
  const multiplier = sortDirection === "asc" ? 1 : -1
  if (sortKey === "source_row_number") {
    return (
      ((left.source_row_number ?? 0) - (right.source_row_number ?? 0)) *
      multiplier
    )
  }
  const column = COLUMN_DEFS.find((item) => item.label === sortKey)
  if (!column) {
    return 0
  }
  const leftValue = getColumnValue(left, column)
  const rightValue = getColumnValue(right, column)
  if (column.sortType === "number") {
    const leftNumber = Number(leftValue ?? 0)
    const rightNumber = Number(rightValue ?? 0)
    if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) {
      return (leftNumber - rightNumber) * multiplier
    }
  }
  return (
    String(leftValue ?? "").localeCompare(
      String(rightValue ?? ""),
      "zh-Hans-CN",
    ) * multiplier
  )
}

function buildDistinctOptions(
  rows: PositionRow[],
  column: ColumnDef,
  limit = 120,
) {
  const distinct = new Map<string, string>()
  for (const row of rows) {
    const display = toDisplayText(getColumnValue(row, column))
    if (!display) continue
    const key = normalizeText(display)
    if (!distinct.has(key)) {
      distinct.set(key, display)
    }
  }
  return Array.from(distinct.values())
    .sort((left, right) => left.localeCompare(right, "zh-Hans-CN"))
    .slice(0, limit)
}

function getSheetSummary(rows: PositionRow[]) {
  const summary = new Map<SheetName, number>()
  for (const sheet of SHEET_NAMES) {
    summary.set(sheet, 0)
  }
  for (const row of rows) {
    const sheet = row.source_sheet as SheetName | undefined
    if (sheet && summary.has(sheet)) {
      summary.set(sheet, (summary.get(sheet) ?? 0) + 1)
    }
  }
  return summary
}

export function GwyPositionsExcelPage() {
  const apiBase = (OpenAPI.BASE || "").replace(/\/$/, "")
  const navigate = useNavigate()
  const [pageState, setPageState] = useState<PageState>(defaultPageState())
  const [rows, setRows] = useState<PositionRow[]>(
    () => getPositionsGridCache()?.rows ?? [],
  )
  const [loading, setLoading] = useState(() => !getPositionsGridCache())
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(
    () => getPositionsGridCache()?.lastUpdatedAt ?? null,
  )
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [tableDialogOpen, setTableDialogOpen] = useState(false)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const horizontalScrollRef = useRef<HTMLDivElement | null>(null)
  const isSyncingScrollRef = useRef(false)
  const scrollSaveTimerRef = useRef<number | null>(null)
  const pendingScrollStateRef = useRef<{ top: number; left: number } | null>(
    null,
  )

  const activeSheet = pageState.activeSheet
  const activeSheetState = pageState.sheets[activeSheet]
  const groupedRows = useMemo(() => groupRowsBySheet(rows), [rows])
  const sheetSummary = useMemo(() => getSheetSummary(rows), [rows])

  useEffect(() => {
    let active = true
    const shouldShowLoading = !getPositionsGridCache()
    if (shouldShowLoading) {
      setLoading(true)
    }
    setError(null)
    void (async () => {
      try {
        const cached = getPositionsGridCache()
        if (cached) {
          setRows(cached.rows)
          setLastUpdatedAt(cached.lastUpdatedAt)
          return
        }
        const cache = await loadPositionsGridFromApi(apiBase)
        if (!active) return
        setRows(cache.rows)
        setLastUpdatedAt(cache.lastUpdatedAt)
      } catch (fetchError) {
        if (!active) return
        setError(
          fetchError instanceof Error
            ? fetchError.message
            : "岗位总表加载失败，请稍后再试",
        )
      } finally {
        if (active && shouldShowLoading) {
          setLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [apiBase])

  const activeRows = useMemo(
    () => groupedRows[activeSheet] ?? [],
    [activeSheet, groupedRows],
  )

  const activeOptions = useMemo(() => {
    return Object.fromEntries(
      COLUMN_DEFS.map((column) => [
        column.label,
        buildDistinctOptions(activeRows, column),
      ]),
    ) as Record<string, string[]>
  }, [activeRows])

  const activeFilteredRows = useMemo(() => {
    const filters = activeSheetState.filters
    const filtered = activeRows.filter((row) =>
      COLUMN_DEFS.every((column) => {
        const filterValue = filters[column.label] ?? ""
        if (!filterValue) {
          return true
        }
        const cellValue = toDisplayText(getColumnValue(row, column))
        return normalizeText(cellValue).includes(normalizeText(filterValue))
      }),
    )
    const sorted = [...filtered]
    sorted.sort((left, right) =>
      compareValues(
        left,
        right,
        activeSheetState.sortKey,
        activeSheetState.sortDirection,
      ),
    )
    return sorted
  }, [
    activeRows,
    activeSheetState.filters,
    activeSheetState.sortDirection,
    activeSheetState.sortKey,
  ])

  const activePageSize =
    activeSheetState.pageSize > 0
      ? activeSheetState.pageSize
      : DEFAULT_PAGE_SIZE
  const activePageCount = Math.max(
    1,
    Math.ceil(activeFilteredRows.length / activePageSize),
  )
  const activePageNumber = Math.min(
    Math.max(1, activeSheetState.pageNumber || 1),
    activePageCount,
  )
  const shouldPaginate =
    activeFilteredRows.length > LARGE_SHEET_RENDER_THRESHOLD
  const activeVisibleRows = shouldPaginate
    ? activeFilteredRows.slice(
        (activePageNumber - 1) * activePageSize,
        activePageNumber * activePageSize,
      )
    : activeFilteredRows

  const activeFilteredCount = activeFilteredRows.length
  const activeSavedSnapshot = pageState.savedSnapshots[activeSheet] ?? null
  const activeAnalysisRows = useMemo(() => {
    if (!activeSavedSnapshot) {
      return activeFilteredRows.slice(0, ANALYZE_LIMIT)
    }
    const selectedIds = new Set(activeSavedSnapshot.rowIds)
    const snapshotRows = rows.filter((row) => selectedIds.has(row.id))
    return snapshotRows.slice(0, ANALYZE_LIMIT)
  }, [activeFilteredRows, activeSavedSnapshot, rows])
  const activeTruncated =
    (activeSavedSnapshot?.rowCount ?? activeFilteredRows.length) > ANALYZE_LIMIT

  const analysisQuery = useMemo(() => {
    const appliedFilters = COLUMN_DEFS.map((column) => {
      const value = activeSheetState.filters[column.label]
      return value ? `${column.label}：${value}` : null
    }).filter(Boolean)
    const snapshotLabel = activeSavedSnapshot
      ? `${activeSheet}（已保存 ${activeSavedSnapshot.rowCount} 条）`
      : `${activeSheet}（当前筛选）`
    if (appliedFilters.length === 0) {
      return `请基于 ${snapshotLabel} 岗位筛选状态和用户补充信息，结合往年的录取分数、招录人数和风险提示，生成岗位匹配报告。`
    }
    return `请基于 ${snapshotLabel} 岗位筛选条件（${appliedFilters.join("；")}），结合往年的录取分数、招录人数和用户补充内容，生成岗位匹配报告，输出推荐顺序、匹配理由、风险提示和最终推荐。`
  }, [activeSavedSnapshot, activeSheet, activeSheetState.filters])

  const fetchPositions = async (force = false) => {
    const controller = new AbortController()
    try {
      const cached = getPositionsGridCache()
      if (!force && cached) {
        setRows(cached.rows)
        setLastUpdatedAt(cached.lastUpdatedAt)
        return
      }
      const cache = await loadPositionsGridFromApi(apiBase, controller.signal)
      writePositionsGridCache({
        rows: cache.rows,
        lastUpdatedAt: cache.lastUpdatedAt,
      })
      setRows(cache.rows)
      setLastUpdatedAt(cache.lastUpdatedAt)
    } catch (fetchError) {
      if (controller.signal.aborted) return
      setError(
        fetchError instanceof Error
          ? fetchError.message
          : "岗位总表加载失败，请稍后再试",
      )
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }

  const refresh = async () => {
    setLoading(true)
    setError(null)
    setAnalysisError(null)
    await fetchPositions(true)
  }

  const resetCurrentSheet = () => {
    setPageState((current) => {
      const nextSheets = { ...current.sheets }
      nextSheets[current.activeSheet] = {
        ...defaultSheetState(),
        pageNumber: 1,
        pageSize: DEFAULT_PAGE_SIZE,
      }
      return { ...current, sheets: nextSheets }
    })
    const viewport = viewportRef.current
    if (viewport) {
      viewport.scrollTop = 0
      viewport.scrollLeft = 0
    }
  }

  const saveCurrentSheetState = () => {
    const currentRows = activeFilteredRows.slice(0, ANALYZE_LIMIT)
    const currentSheet = pageState.sheets[pageState.activeSheet]
    const nextState: PageState = {
      ...pageState,
      savedSnapshots: {
        ...pageState.savedSnapshots,
        [pageState.activeSheet]: {
          savedAt: new Date().toLocaleString("zh-CN"),
          rowCount: activeFilteredRows.length,
          rowIds: currentRows.map((row) => row.id),
          filters: { ...currentSheet.filters },
          sortKey: currentSheet.sortKey,
          sortDirection: currentSheet.sortDirection,
        },
      },
    }
    setPageState(nextState)
    void fetch(`${apiBase}/api/v1/gwy/positions/page-state`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(nextState),
    }).catch((saveError) => {
      console.warn("Failed to persist Gwy positions page state", saveError)
    })
    return nextState
  }

  const handleScroll = () => {
    const viewport = viewportRef.current
    if (!viewport) return
    if (isSyncingScrollRef.current) return
    const nextTop = viewport.scrollTop
    const nextLeft = viewport.scrollLeft
    const horizontalScroll = horizontalScrollRef.current
    if (horizontalScroll && horizontalScroll.scrollLeft !== nextLeft) {
      isSyncingScrollRef.current = true
      horizontalScroll.scrollLeft = nextLeft
      window.requestAnimationFrame(() => {
        isSyncingScrollRef.current = false
      })
    }
    pendingScrollStateRef.current = { top: nextTop, left: nextLeft }
    if (scrollSaveTimerRef.current !== null) {
      window.clearTimeout(scrollSaveTimerRef.current)
    }
    scrollSaveTimerRef.current = window.setTimeout(() => {
      const pending = pendingScrollStateRef.current
      if (!pending) return
      setPageState((current) => {
        const nextSheets = { ...current.sheets }
        nextSheets[current.activeSheet] = {
          ...current.sheets[current.activeSheet],
          scrollTop: pending.top,
          scrollLeft: pending.left,
        }
        return { ...current, sheets: nextSheets }
      })
    }, 120)
  }

  const handleHorizontalScroll = () => {
    const horizontalScroll = horizontalScrollRef.current
    if (!horizontalScroll) return
    if (isSyncingScrollRef.current) return
    const nextLeft = horizontalScroll.scrollLeft
    const viewport = viewportRef.current
    if (viewport && viewport.scrollLeft !== nextLeft) {
      isSyncingScrollRef.current = true
      viewport.scrollLeft = nextLeft
      window.requestAnimationFrame(() => {
        isSyncingScrollRef.current = false
      })
    }
    pendingScrollStateRef.current = {
      top: viewport?.scrollTop ?? 0,
      left: nextLeft,
    }
    if (scrollSaveTimerRef.current !== null) {
      window.clearTimeout(scrollSaveTimerRef.current)
    }
    scrollSaveTimerRef.current = window.setTimeout(() => {
      const pending = pendingScrollStateRef.current
      if (!pending) return
      setPageState((current) => {
        const nextSheets = { ...current.sheets }
        nextSheets[current.activeSheet] = {
          ...current.sheets[current.activeSheet],
          scrollTop: pending.top,
          scrollLeft: pending.left,
        }
        return { ...current, sheets: nextSheets }
      })
    }, 120)
  }

  const analyzeCurrentSheet = async () => {
    const nextState = saveCurrentSheetState()
    const savedSnapshot = nextState.savedSnapshots[nextState.activeSheet]
    if (!savedSnapshot || savedSnapshot.rowIds.length === 0) {
      setAnalysisError(
        "已保存状态下没有可分析的岗位，请先放宽筛选条件后重新保存。",
      )
      return
    }
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const response = await GwyAnalysisService.createPositionAnalysisTask({
        requestBody: {
          snapshot: {
            title: `${nextState.activeSheet}岗位分析快照`,
            source_sheet: nextState.activeSheet,
            filters_json: savedSnapshot.filters,
            snapshot_json: {
              active_sheet: nextState.activeSheet,
              saved_snapshot: savedSnapshot,
              selected_position_ids: savedSnapshot.rowIds,
              visible_columns: COLUMN_DEFS.map((column) => column.label),
              generated_at: new Date().toISOString(),
            },
            selected_position_ids: savedSnapshot.rowIds,
            visible_columns: COLUMN_DEFS.map((column) => column.label),
            notes: analysisQuery,
          },
          title: `${nextState.activeSheet}岗位分析报告`,
          source_sheet: nextState.activeSheet,
          notes: analysisQuery,
        },
      })
      await navigate({
        to: "/gwy/analysis",
        search: {
          task_id: String(response.task_id),
        },
      })
    } catch (analysisFetchError) {
      setAnalysisError(
        analysisFetchError instanceof Error
          ? analysisFetchError.message
          : "宀椾綅鍒嗘瀽澶辫触锛岃绋嶅悗鍐嶈瘯",
      )
    } finally {
      setAnalysisLoading(false)
    }
  }

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
              按 Excel 简章的 4 个 sheet
              原样展示岗位，支持列级下拉筛选、排序和横向滚动。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant="outline" className="bg-white">
              总计 {rows.length} 条
            </Badge>
            <Badge variant="outline" className="bg-white">
              当前表 {activeRows.length} 条
            </Badge>
            <Badge variant="outline" className="bg-white">
              当前筛选 {activeFilteredCount} 条
            </Badge>
            <Badge variant="outline" className="bg-white">
              最近同步 {lastUpdatedAt || "未加载"}
            </Badge>
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => void refresh()}
            variant="outline"
            className="gap-2"
          >
            <RefreshCw className="h-4 w-4" />
            重新加载
          </Button>
          <Button
            onClick={saveCurrentSheetState}
            variant="outline"
            className="gap-2"
          >
            <Sparkles className="h-4 w-4" />
            保存当前表状态
          </Button>
          <Button
            onClick={() => void analyzeCurrentSheet()}
            disabled={analysisLoading || activeAnalysisRows.length === 0}
            className="gap-2"
          >
            <Search className="h-4 w-4" />
            {analysisLoading ? "分析中..." : "生成分析报告"}
          </Button>
          <Button
            onClick={resetCurrentSheet}
            variant="outline"
            className="gap-2"
          >
            <X className="h-4 w-4" />
            重置当前筛选
          </Button>
          <Button
            onClick={() => setTableDialogOpen(true)}
            variant="outline"
            className="gap-2"
          >
            <Maximize2 className="h-4 w-4" />
            放大表格
          </Button>
          {activeTruncated ? (
            <span className="text-xs text-amber-600">
              当前筛选结果超过 {ANALYZE_LIMIT} 条，已按前 {ANALYZE_LIMIT}{" "}
              条生成报告。
            </span>
          ) : null}
        </div>

        {error ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}
        {analysisError ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {analysisError}
          </div>
        ) : null}

        <Tabs
          value={activeSheet}
          onValueChange={(value) => {
            if (SHEET_NAMES.includes(value as SheetName)) {
              setPageState((current) => ({
                ...current,
                activeSheet: value as SheetName,
              }))
            }
          }}
          className="flex min-h-0 flex-1 flex-col gap-3"
        >
          <TabsList className="grid h-auto w-full grid-cols-2 gap-2 rounded-2xl bg-slate-100 p-2 xl:grid-cols-4">
            {SHEET_NAMES.map((sheet) => (
              <TabsTrigger
                key={sheet}
                value={sheet}
                className="rounded-xl px-3 py-2 text-sm data-[state=active]:bg-white"
              >
                <span className="truncate">{sheet}</span>
                <Badge
                  variant="secondary"
                  className="ml-2 rounded-full px-2 py-0.5 text-xs"
                >
                  {sheetSummary.get(sheet) ?? 0}
                </Badge>
              </TabsTrigger>
            ))}
          </TabsList>

          {SHEET_NAMES.map((sheet) => {
            const sheetRows = groupedRows[sheet] ?? []
            const sheetState = pageState.sheets[sheet]
            const filteredRows = sheet === activeSheet ? activeFilteredRows : []
            const savedSnapshot = pageState.savedSnapshots[sheet] ?? null
            return (
              <TabsContent key={sheet} value={sheet} className="min-h-0 flex-1">
                <div className="flex min-h-0 flex-1 flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
                  <div className="border-b border-slate-200 px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-base font-semibold text-slate-900">
                          {sheet}
                        </div>
                        <div className="text-sm text-slate-500">
                          这一页显示的是该 sheet 的原始岗位数据，表头与 Excel
                          简章保持一致。
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 text-sm text-slate-500">
                        <Badge variant="outline" className="bg-white">
                          原始 {sheetRows.length} 条
                        </Badge>
                        <Badge variant="outline" className="bg-white">
                          当前筛选{" "}
                          {sheet === activeSheet
                            ? filteredRows.length
                            : sheetRows.length}{" "}
                          条
                        </Badge>
                        {sheet === activeSheet ? (
                          <Badge variant="outline" className="bg-white">
                            第 {activePageNumber}/{activePageCount} 页
                          </Badge>
                        ) : null}
                        {savedSnapshot ? (
                          <Badge variant="outline" className="bg-white">
                            已保存 {savedSnapshot.savedAt || "快照"}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="bg-white">
                            未保存快照
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    {loading ? (
                      <div className="px-4 py-10 text-center text-sm text-slate-500">
                        正在加载岗位数据...
                      </div>
                    ) : sheet !== activeSheet ? (
                      <div className="px-4 py-10 text-center text-sm text-slate-500">
                        切换到此标签页后会自动恢复筛选和滚动位置。
                      </div>
                    ) : (
                      <>
                        <div
                          ref={viewportRef}
                          onScroll={handleScroll}
                          className="flex-none overflow-x-hidden overflow-y-auto"
                          style={{ height: "clamp(560px, 60vh, 760px)" }}
                        >
                          <div className="w-max min-w-full">
                            <table
                              className="w-max table-fixed border-0 text-xs"
                              style={{ minWidth: `${TABLE_MIN_WIDTH}px` }}
                            >
                              <TableHeader className="sticky top-0 z-20 bg-slate-50">
                                <TableRow>
                                  {COLUMN_DEFS.map((column) => {
                                    const active =
                                      sheetState.sortKey === column.label
                                    const direction = sheetState.sortDirection
                                    return (
                                      <TableHead
                                        key={column.label}
                                        className={cn(
                                          "align-middle bg-slate-50 px-1 py-1 text-center",
                                          column.width,
                                          active && "text-sky-700",
                                        )}
                                      >
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setPageState((current) => {
                                              const nextSheets = {
                                                ...current.sheets,
                                              }
                                              const currentSheet =
                                                nextSheets[sheet]
                                              const nextDirection =
                                                currentSheet.sortKey ===
                                                column.label
                                                  ? currentSheet.sortDirection ===
                                                    "asc"
                                                    ? "desc"
                                                    : "asc"
                                                  : "asc"
                                              nextSheets[sheet] = {
                                                ...currentSheet,
                                                sortKey: column.label,
                                                sortDirection: nextDirection,
                                                pageNumber: 1,
                                              }
                                              return {
                                                ...current,
                                                activeSheet: sheet,
                                                sheets: nextSheets,
                                              }
                                            })
                                          }}
                                          className="flex w-full items-center justify-center gap-1 overflow-hidden whitespace-normal text-center text-[11px] font-semibold leading-tight text-slate-700"
                                        >
                                          <span className="min-w-0 flex-1 whitespace-normal break-words">
                                            {column.label}
                                          </span>
                                          <ArrowUpDown
                                            className={cn(
                                              "h-3.5 w-3.5 text-slate-400",
                                              active && "text-sky-600",
                                              active &&
                                                direction === "desc" &&
                                                "rotate-180",
                                            )}
                                          />
                                        </button>
                                      </TableHead>
                                    )
                                  })}
                                </TableRow>
                                <TableRow className="border-b-0">
                                  {COLUMN_DEFS.map((column) => (
                                    <TableHead
                                      key={`${sheet}-${column.label}-filter`}
                                      className={cn(
                                        "align-middle bg-slate-50 px-1 pb-1 pt-1 text-center",
                                        column.width,
                                      )}
                                    >
                                      <Select
                                        value={
                                          sheetState.filters[column.label] ||
                                          ALL_VALUE
                                        }
                                        onValueChange={(value) => {
                                          setPageState((current) => {
                                            const nextSheets = {
                                              ...current.sheets,
                                            }
                                            nextSheets[sheet] = {
                                              ...current.sheets[sheet],
                                              filters: {
                                                ...current.sheets[sheet]
                                                  .filters,
                                                [column.label]:
                                                  value === ALL_VALUE
                                                    ? ""
                                                    : value,
                                              },
                                              pageNumber: 1,
                                            }
                                            return {
                                              ...current,
                                              activeSheet: sheet,
                                              sheets: nextSheets,
                                            }
                                          })
                                        }}
                                      >
                                        <SelectTrigger className="h-7 w-full border-dashed bg-white px-1 text-center text-[10px] font-normal">
                                          <SelectValue placeholder="全部" />
                                        </SelectTrigger>
                                        <SelectContent
                                          align="start"
                                          className="max-h-72"
                                        >
                                          <SelectItem value={ALL_VALUE}>
                                            全部
                                          </SelectItem>
                                          {activeOptions[column.label]?.map(
                                            (option) => (
                                              <SelectItem
                                                key={option}
                                                value={option}
                                              >
                                                {option}
                                              </SelectItem>
                                            ),
                                          )}
                                        </SelectContent>
                                      </Select>
                                    </TableHead>
                                  ))}
                                </TableRow>
                              </TableHeader>

                              <TableBody>
                                {activeVisibleRows.length === 0 ? (
                                  <TableRow>
                                    <TableCell
                                      colSpan={COLUMN_DEFS.length}
                                      className="py-10 text-center text-xs text-slate-500"
                                    >
                                      没有匹配到岗位，请尝试放宽筛选条件。
                                    </TableCell>
                                  </TableRow>
                                ) : (
                                  activeVisibleRows.map((row) => (
                                    <TableRow
                                      key={row.id}
                                      className="hover:bg-slate-50 align-middle"
                                    >
                                      {COLUMN_DEFS.map((column) => {
                                        const value =
                                          toDisplayText(
                                            getColumnValue(row, column),
                                          ) || "—"
                                        return (
                                          <TableCell
                                            key={`${row.id}-${column.label}`}
                                            className={cn(
                                              "px-1 py-1 align-middle whitespace-normal break-words text-center leading-5 text-slate-700",
                                              column.width,
                                              column.key ===
                                                "department_name" &&
                                                "font-medium text-slate-900",
                                              column.key === "recruit_count" &&
                                                "text-center",
                                            )}
                                            style={{
                                              overflowWrap: "anywhere",
                                            }}
                                            title={value}
                                          >
                                            {value}
                                          </TableCell>
                                        )
                                      })}
                                    </TableRow>
                                  ))
                                )}
                              </TableBody>
                            </table>
                          </div>
                        </div>
                        <div className="shrink-0 border-t border-slate-200 bg-slate-50 px-4 py-2">
                          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                            <div className="text-xs text-slate-500">
                              {shouldPaginate ? (
                                <span>
                                  当前启用分页渲染，避免超大 sheet 卡顿。 每页{" "}
                                  {activePageSize} 条，共{" "}
                                  {activeFilteredRows.length}
                                  条。
                                </span>
                              ) : (
                                <span>
                                  当前 sheet 数据量较小，保持全量展示。
                                </span>
                              )}
                            </div>
                            {shouldPaginate ? (
                              <div className="flex flex-wrap items-center gap-2">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={activePageNumber <= 1}
                                  onClick={() => {
                                    setPageState((current) => {
                                      const nextSheets = { ...current.sheets }
                                      nextSheets[sheet] = {
                                        ...current.sheets[sheet],
                                        pageNumber: Math.max(
                                          1,
                                          activePageNumber - 1,
                                        ),
                                      }
                                      return {
                                        ...current,
                                        activeSheet: sheet,
                                        sheets: nextSheets,
                                      }
                                    })
                                  }}
                                >
                                  上一页
                                </Button>
                                <span className="text-xs text-slate-600">
                                  第 {activePageNumber} / {activePageCount} 页
                                </span>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={activePageNumber >= activePageCount}
                                  onClick={() => {
                                    setPageState((current) => {
                                      const nextSheets = { ...current.sheets }
                                      nextSheets[sheet] = {
                                        ...current.sheets[sheet],
                                        pageNumber: Math.min(
                                          activePageCount,
                                          activePageNumber + 1,
                                        ),
                                      }
                                      return {
                                        ...current,
                                        activeSheet: sheet,
                                        sheets: nextSheets,
                                      }
                                    })
                                  }}
                                >
                                  下一页
                                </Button>
                                <Select
                                  value={String(activePageSize)}
                                  onValueChange={(value) => {
                                    const nextPageSize = Number(value)
                                    if (!Number.isFinite(nextPageSize)) return
                                    setPageState((current) => {
                                      const nextSheets = { ...current.sheets }
                                      nextSheets[sheet] = {
                                        ...current.sheets[sheet],
                                        pageNumber: 1,
                                        pageSize: nextPageSize,
                                      }
                                      return {
                                        ...current,
                                        activeSheet: sheet,
                                        sheets: nextSheets,
                                      }
                                    })
                                  }}
                                >
                                  <SelectTrigger className="h-8 w-[110px] bg-white text-xs">
                                    <SelectValue placeholder="每页条数" />
                                  </SelectTrigger>
                                  <SelectContent align="end">
                                    {PAGE_SIZE_OPTIONS.map((size) => (
                                      <SelectItem
                                        key={size}
                                        value={String(size)}
                                      >
                                        每页 {size} 条
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            ) : null}
                          </div>
                          <div
                            ref={horizontalScrollRef}
                            onScroll={handleHorizontalScroll}
                            className="mt-2 h-4 overflow-x-scroll overflow-y-hidden"
                          >
                            <div
                              className="h-px"
                              style={{ width: `${TABLE_MIN_WIDTH}px` }}
                            />
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </TabsContent>
            )
          })}
        </Tabs>
      </div>

      <Dialog open={tableDialogOpen} onOpenChange={setTableDialogOpen}>
        <DialogContent className="h-[92vh] w-[96vw] max-w-none overflow-hidden rounded-3xl border border-slate-200 bg-slate-50 p-4 shadow-2xl sm:max-w-none">
          <DialogHeader className="sr-only">
            <DialogTitle>岗位表放大视图</DialogTitle>
          </DialogHeader>
          <div className="flex h-full min-h-0 flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-base font-semibold text-slate-900">
                    {activeSheet}
                  </div>
                  <div className="text-sm text-slate-500">
                    当前仅放大这一块岗位表区域，方便查看、筛选和横向滚动。
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 text-sm text-slate-500">
                  <Badge variant="outline" className="bg-white">
                    原始 {activeRows.length} 条
                  </Badge>
                  <Badge variant="outline" className="bg-white">
                    当前筛选 {activeFilteredCount} 条
                  </Badge>
                  <Badge variant="outline" className="bg-white">
                    第 {activePageNumber}/{activePageCount} 页
                  </Badge>
                  {activeSavedSnapshot ? (
                    <Badge variant="outline" className="bg-white">
                      已保存 {activeSavedSnapshot.savedAt || "快照"}
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="bg-white">
                      未保存快照
                    </Badge>
                  )}
                </div>
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="flex-1 overflow-auto">
                <div className="w-max min-w-full">
                  <table
                    className="w-max table-fixed border-0 text-xs"
                    style={{ minWidth: `${TABLE_MIN_WIDTH}px` }}
                  >
                    <TableHeader className="sticky top-0 z-20 bg-slate-50">
                      <TableRow>
                        {COLUMN_DEFS.map((column) => {
                          const active =
                            activeSheetState.sortKey === column.label
                          const direction = activeSheetState.sortDirection
                          return (
                            <TableHead
                              key={column.label}
                              className={cn(
                                "align-middle bg-slate-50 px-1 py-1 text-center",
                                column.width,
                                active && "text-sky-700",
                              )}
                            >
                              <button
                                type="button"
                                onClick={() => {
                                  setPageState((current) => {
                                    const nextSheets = { ...current.sheets }
                                    const currentSheet = nextSheets[activeSheet]
                                    const nextDirection =
                                      currentSheet.sortKey === column.label
                                        ? currentSheet.sortDirection === "asc"
                                          ? "desc"
                                          : "asc"
                                        : "asc"
                                    nextSheets[activeSheet] = {
                                      ...currentSheet,
                                      sortKey: column.label,
                                      sortDirection: nextDirection,
                                      pageNumber: 1,
                                    }
                                    return {
                                      ...current,
                                      activeSheet,
                                      sheets: nextSheets,
                                    }
                                  })
                                }}
                                className="flex w-full items-center justify-center gap-1 overflow-hidden whitespace-normal text-center text-[11px] font-semibold leading-tight text-slate-700"
                              >
                                <span className="min-w-0 flex-1 whitespace-normal break-words">
                                  {column.label}
                                </span>
                                <ArrowUpDown
                                  className={cn(
                                    "h-3.5 w-3.5 text-slate-400",
                                    active && "text-sky-600",
                                    active &&
                                      direction === "desc" &&
                                      "rotate-180",
                                  )}
                                />
                              </button>
                            </TableHead>
                          )
                        })}
                      </TableRow>
                      <TableRow className="border-b-0">
                        {COLUMN_DEFS.map((column) => (
                          <TableHead
                            key={`dialog-${column.label}-filter`}
                            className={cn(
                              "align-middle bg-slate-50 px-1 pb-1 pt-1 text-center",
                              column.width,
                            )}
                          >
                            <Select
                              value={
                                activeSheetState.filters[column.label] ||
                                ALL_VALUE
                              }
                              onValueChange={(value) => {
                                setPageState((current) => {
                                  const nextSheets = { ...current.sheets }
                                  nextSheets[activeSheet] = {
                                    ...current.sheets[activeSheet],
                                    filters: {
                                      ...current.sheets[activeSheet].filters,
                                      [column.label]:
                                        value === ALL_VALUE ? "" : value,
                                    },
                                    pageNumber: 1,
                                  }
                                  return {
                                    ...current,
                                    activeSheet,
                                    sheets: nextSheets,
                                  }
                                })
                              }}
                            >
                              <SelectTrigger className="h-7 w-full border-dashed bg-white px-1 text-center text-[10px] font-normal">
                                <SelectValue placeholder="全部" />
                              </SelectTrigger>
                              <SelectContent align="start" className="max-h-72">
                                <SelectItem value={ALL_VALUE}>全部</SelectItem>
                                {activeOptions[column.label]?.map((option) => (
                                  <SelectItem key={option} value={option}>
                                    {option}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>

                    <TableBody>
                      {activeVisibleRows.length === 0 ? (
                        <TableRow>
                          <TableCell
                            colSpan={COLUMN_DEFS.length}
                            className="py-10 text-center text-xs text-slate-500"
                          >
                            没有匹配到岗位，请尝试放宽筛选条件。
                          </TableCell>
                        </TableRow>
                      ) : (
                        activeVisibleRows.map((row) => (
                          <TableRow
                            key={row.id}
                            className="hover:bg-slate-50 align-middle"
                          >
                            {COLUMN_DEFS.map((column) => {
                              const value =
                                toDisplayText(getColumnValue(row, column)) ||
                                "—"
                              return (
                                <TableCell
                                  key={`${row.id}-${column.label}`}
                                  className={cn(
                                    "px-1 py-1 align-middle whitespace-normal break-words text-center leading-5 text-slate-700",
                                    column.width,
                                    column.key === "department_name" &&
                                      "font-medium text-slate-900",
                                    column.key === "recruit_count" &&
                                      "text-center",
                                  )}
                                  style={{
                                    overflowWrap: "anywhere",
                                  }}
                                  title={value}
                                >
                                  {value}
                                </TableCell>
                              )
                            })}
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </table>
                </div>
              </div>

              <div className="shrink-0 border-t border-slate-200 bg-slate-50 px-4 py-2">
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                  <div className="text-xs text-slate-500">
                    {shouldPaginate ? (
                      <span>
                        当前启用分页渲染，避免超大 sheet 卡顿。每页{" "}
                        {activePageSize} 条，共 {activeFilteredRows.length} 条。
                      </span>
                    ) : (
                      <span>当前 sheet 数据量较小，保持全量展示。</span>
                    )}
                  </div>
                  {shouldPaginate ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={activePageNumber <= 1}
                        onClick={() => {
                          setPageState((current) => {
                            const nextSheets = { ...current.sheets }
                            nextSheets[activeSheet] = {
                              ...current.sheets[activeSheet],
                              pageNumber: Math.max(1, activePageNumber - 1),
                            }
                            return {
                              ...current,
                              activeSheet,
                              sheets: nextSheets,
                            }
                          })
                        }}
                      >
                        上一页
                      </Button>
                      <span className="text-xs text-slate-600">
                        第 {activePageNumber} / {activePageCount} 页
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={activePageNumber >= activePageCount}
                        onClick={() => {
                          setPageState((current) => {
                            const nextSheets = { ...current.sheets }
                            nextSheets[activeSheet] = {
                              ...current.sheets[activeSheet],
                              pageNumber: Math.min(
                                activePageCount,
                                activePageNumber + 1,
                              ),
                            }
                            return {
                              ...current,
                              activeSheet,
                              sheets: nextSheets,
                            }
                          })
                        }}
                      >
                        下一页
                      </Button>
                      <Select
                        value={String(activePageSize)}
                        onValueChange={(value) => {
                          const nextPageSize = Number(value)
                          if (!Number.isFinite(nextPageSize)) return
                          setPageState((current) => {
                            const nextSheets = { ...current.sheets }
                            nextSheets[activeSheet] = {
                              ...current.sheets[activeSheet],
                              pageNumber: 1,
                              pageSize: nextPageSize,
                            }
                            return {
                              ...current,
                              activeSheet,
                              sheets: nextSheets,
                            }
                          })
                        }}
                      >
                        <SelectTrigger className="h-8 w-[110px] bg-white text-xs">
                          <SelectValue placeholder="每页条数" />
                        </SelectTrigger>
                        <SelectContent align="end">
                          {PAGE_SIZE_OPTIONS.map((size) => (
                            <SelectItem key={size} value={String(size)}>
                              每页 {size} 条
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
