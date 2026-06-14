import {
  createFileRoute,
  Link as RouterLink,
  useNavigate,
} from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronLeft,
  FileText,
  History,
  Sparkles,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { z } from "zod"

import {
  GwyAnalysisService,
  type PositionAnalysisSnapshotResponse,
  type PositionAnalysisTaskResponse,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const searchSchema = z.object({
  task_id: z.string().catch(""),
})

export const Route = createFileRoute("/_layout/gwy/analysis")({
  validateSearch: searchSchema,
  component: GwyAnalysisReportPage,
  head: () => ({
    meta: [
      {
        title: "岗位分析报告 - GwyPilot",
      },
    ],
  }),
})

type AnalysisEvidence = {
  id: string
  doc_title: string
  source_file: string
  content: string
  score: number
}

type AnalysisTraceEntry = {
  step: string
  status: string
  detail: string
  elapsed_ms: number
  inputs_summary: Record<string, unknown>
  outputs_summary: Record<string, unknown>
  evidence_refs: AnalysisEvidence[]
  query?: string
  query_index?: number
  attempt_index?: number
  hit_count?: number
  fetched_count?: number
  browser_fallback_count?: number
  result_count?: number
  retry_count?: number
}

type AnalysisHistoryItem = {
  task_id: string
  snapshot_id: string
  title: string
  finished_at: string
  created_at: string
  status: string
  stage: string
}

type AnalysisJourneyEntry = {
  phase?: string
  step: string
  status: string
  detail: string
  elapsed_ms: number
  summary_lines?: string[]
  position_label?: string
  history_years?: string[]
  latest_recruit_count?: number | string | null
  latest_interview_ratio?: number | string | null
  web_hit_count?: number
}

type AnalysisPositionResearch = {
  index: number
  position_id: string
  department_name: string
  office_name: string
  job_title: string
  position_code: string
  history: Record<string, unknown>
  history_records: Array<Record<string, unknown>>
  web_results: Array<Record<string, unknown>>
  web_search_attempts: Array<Record<string, unknown>>
  analysis_text: string
  research_plan: Record<string, unknown>
  strategy_target: AnalysisStrategyTarget | null
}

type AnalysisStrategyTarget = {
  index: number
  position_id: string
  department_name: string
  office_name: string
  job_title: string
  position_code: string
  history_priority: string
  needs_web_search: boolean
  focus: string[]
  search_queries?: string[]
  retry_queries?: string[]
  observation_questions?: string[]
  evidence_focus?: string[]
  reason?: string
  history_summary: Record<string, unknown>
}

type StudyPlanPhase = {
  id: string
  phase_order: number
  phase_name: string
  phase_goal: string
  week_start: number
  week_end: number
  focus_subjects: string[]
  study_hours_per_day: number | string | null
}

type StudyPlanSubject = {
  id: string
  subject_name: string
  subject_category: string
  weight_percent: number | string | null
  total_hours: number | string | null
  checklist_items: string[]
  resources: string[]
}

type StudyPlanTask = {
  id: string
  week_number: number
  day_of_week: number
  subject: string
  task_title: string
  task_description: string
  estimated_minutes: number | string | null
  priority: number | string | null
  completed: boolean
}

type StudyPlanPlan = {
  id: string
  title: string
  exam_type: string
  exam_year: number | string | null
  status: string
  study_hours_per_day: number | string | null
  total_weeks: number | string | null
}

type StudyPlanData = {
  status: string
  plan: StudyPlanPlan
  phases: StudyPlanPhase[]
  subjects: StudyPlanSubject[]
  tasks: StudyPlanTask[]
  markdown: string
}

type AnalysisStrategy = {
  strategy_name: string
  planning_strategy: string
  evidence_strategy: string
  decision_style: string
  strategy_source?: string
  analysis_goal: string
  query: string
  research_budget: Record<string, unknown>
  priority_sources: string[]
  research_targets: AnalysisStrategyTarget[]
  summary_lines: string[]
}

type AnalysisDecisionFocus = {
  position_id?: string
  position_label?: string
  score?: number
  web_hit_count?: number
  history_years?: Array<string | number>
  gaps?: string[]
}

type AnalysisDecision = {
  focus_position_ids?: string[]
  focus_positions?: AnalysisDecisionFocus[]
  decision_notes?: string[]
  ranked_position_count?: number
  observation_count?: number
  search_coverage?: {
    with_web_evidence?: number
    without_web_evidence?: number
  }
}

type AnalysisRecommendationContext = {
  status?: string
  query?: string
  year?: number | string
  exam_type?: string
  top_k?: number | string
  need_more_info?: boolean
  missing_fields?: string[]
  answer?: string
  summary?: Record<string, unknown>
  recommendations?: Array<Record<string, unknown>>
  retrieval_trace?: Array<Record<string, unknown>>
}

type AnalysisPositionFact = {
  index: number
  position_id: string
  department_name: string
  office_name: string
  job_title: string
  position_code: string
  recruit_count: number | null
  score: number | null
  recommend_level: string
  risk_level: string
  need_manual_confirm: boolean
  major_requirement: string
  education_requirement: string
  degree_requirement: string
  political_status_requirement: string
  work_location: string
  remarks: string
  history: Record<string, unknown>
  history_records: Array<Record<string, unknown>>
  web_results: Array<Record<string, unknown>>
  reasons: Array<Record<string, unknown>>
  risks: Array<Record<string, unknown>>
  hard_filter_passed: boolean
  hard_filter_reasons: string[]
  hard_filter_risks: string[]
}

function GwyAnalysisPage() {
  const { task_id: taskId } = Route.useSearch()
  const navigate = useNavigate()
  const [task, setTask] = useState<PositionAnalysisTaskResponse | null>(null)
  const [snapshot, setSnapshot] =
    useState<PositionAnalysisSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [supplementText, setSupplementText] = useState("")
  const [supplementSubmitting, setSupplementSubmitting] = useState(false)
  const [analysisHistory, setAnalysisHistory] = useState<AnalysisHistoryItem[]>(
    [],
  )

  useEffect(() => {
    if (!taskId) {
      setTask(null)
      setSnapshot(null)
      setError(null)
      setLoading(false)
      return
    }

    let active = true

    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const taskResponse = await GwyAnalysisService.getPositionAnalysisTask({
          taskId,
        })
        const snapshotResponse =
          await GwyAnalysisService.getPositionAnalysisSnapshot({
            snapshotId: taskResponse.snapshot_id,
          })
        if (!active) {
          return
        }
        setTask(taskResponse)
        setSnapshot(snapshotResponse)
      } catch (loadError) {
        if (!active) {
          return
        }
        setError(
          loadError instanceof Error
            ? loadError.message
            : "岗位分析报告加载失败，请稍后重试。",
        )
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [taskId])

  const taskOutput = (task?.output_json ?? {}) as Record<string, unknown>
  const reportText = task?.report_text?.trim() ?? ""
  const traceEntries = useMemo(
    () => normalizeTraceEntries(task?.trace_json),
    [task?.trace_json],
  )
  const visibleTraceEntries = useMemo(
    () => traceEntries.filter((item) => !item.step.startsWith("persist_")),
    [traceEntries],
  )
  const evidence = useMemo(() => {
    const rawEvidence = taskOutput.policy_evidence
    if (!Array.isArray(rawEvidence)) {
      return []
    }
    return rawEvidence
      .map((item) => normalizeEvidence(item))
      .filter((item): item is AnalysisEvidence => item !== null)
  }, [taskOutput])

  const reportOutline = useMemo(() => {
    const rawOutline = taskOutput.report_outline
    return Array.isArray(rawOutline)
      ? rawOutline.map((item) => String(item)).filter(Boolean)
      : []
  }, [taskOutput])

  const analysisMeta = isRecord(taskOutput.analysis_meta)
    ? (taskOutput.analysis_meta as Record<string, unknown>)
    : {}
  const positionFacts = isRecord(taskOutput.position_facts)
    ? (taskOutput.position_facts as Record<string, unknown>)
    : {}
  const analysisStrategy = isRecord(taskOutput.analysis_strategy)
    ? normalizeAnalysisStrategy(taskOutput.analysis_strategy)
    : null
  const analysisDecision = isRecord(taskOutput.analysis_decision)
    ? (taskOutput.analysis_decision as AnalysisDecision)
    : {}
  const recommendationContext = isRecord(taskOutput.recommendation_context)
    ? (taskOutput.recommendation_context as AnalysisRecommendationContext)
    : {}
  const feishuPush = isRecord(taskOutput.feishu_push)
    ? (taskOutput.feishu_push as Record<string, unknown>)
    : {}
  const analysisDecisionFocusPositions = Array.isArray(
    analysisDecision.focus_positions,
  )
    ? analysisDecision.focus_positions
    : []
  const analysisDecisionNotes = Array.isArray(analysisDecision.decision_notes)
    ? analysisDecision.decision_notes
        .map((item) => String(item))
        .filter(Boolean)
    : []
  const studyPlan = useMemo(
    () => normalizeStudyPlan(taskOutput.study_plan),
    [taskOutput],
  )
  const analysisSearchCoverage = (analysisDecision.search_coverage ?? {}) as {
    with_web_evidence?: number
    without_web_evidence?: number
  }
  const modelName =
    String(
      analysisMeta.model_name ??
        analysisMeta.refine_model ??
        analysisMeta.draft_model_name ??
        "未记录",
    ) || "未记录"
  const llmUsed = Boolean(
    analysisMeta.used_llm ?? analysisMeta.refine_used_llm ?? false,
  )
  const feishuStatus = String(feishuPush.status ?? "未推送") || "未推送"

  const agentJourney = useMemo(
    () =>
      normalizeJourneyEntries(
        taskOutput.analysis_journey ?? taskOutput.agent_journey,
      ),
    [taskOutput],
  )
  const positionResearches = useMemo(
    () => normalizePositionResearches(taskOutput.position_researches),
    [taskOutput],
  )
  const selectedPositionFacts = useMemo(
    () => normalizePositionFacts(positionFacts.selected_positions),
    [positionFacts],
  )
  const recommendationFacts = useMemo(
    () => normalizePositionFacts(positionFacts.recommendations),
    [positionFacts],
  )
  const strategyTargets = analysisStrategy?.research_targets ?? []
  const strategySummaryLines = analysisStrategy?.summary_lines ?? []
  const recommendationContextRecommendations = useMemo(
    () =>
      Array.isArray(recommendationContext.recommendations)
        ? recommendationContext.recommendations
            .map((item) => normalizePositionFact(item))
            .filter((item): item is AnalysisPositionFact => item !== null)
        : [],
    [recommendationContext],
  )
  const snapshotFilters = snapshot?.filters_json ?? {}
  const snapshotColumns = snapshot?.visible_columns ?? []
  const snapshotSelected = snapshot?.selected_position_ids ?? []
  const isClarification =
    task?.status === "needs_more_info" || Boolean(taskOutput.needs_more_info)
  const clarifyingQuestions = toStringList(taskOutput.clarifying_questions)
  const missingFields = toStringList(taskOutput.missing_fields)
  const taskInput = isRecord(task?.input_json)
    ? (task?.input_json as Record<string, unknown>)
    : {}
  const userProfile = isRecord(taskInput.user_profile)
    ? (taskInput.user_profile as Record<string, unknown>)
    : {}
  const reportGeneratedAt =
    formatDateTime(task?.finished_at ?? task?.started_at ?? task?.created_at) ||
    "无法确认"
  const recommendationBuckets = useMemo(
    () => buildRecommendationBuckets(selectedPositionFacts),
    [selectedPositionFacts],
  )
  const historyYearStats = useMemo(
    () => buildHistoryYearStats(positionResearches),
    [positionResearches],
  )
  const topRecommendations = useMemo(
    () =>
      [...recommendationFacts]
        .sort((left, right) => (right.score ?? 0) - (left.score ?? 0))
        .slice(0, 10),
    [recommendationFacts],
  )
  const topResearches = useMemo(
    () => positionResearches.slice(0, 5),
    [positionResearches],
  )
  const analysisDecisionFocusById = useMemo(() => {
    const entries = Array.isArray(analysisDecisionFocusPositions)
      ? analysisDecisionFocusPositions
      : []
    return new Map(
      entries
        .filter((item) => Boolean(item.position_id))
        .map((item) => [String(item.position_id), item]),
    )
  }, [analysisDecisionFocusPositions])
  const selectedFactById = useMemo(() => {
    return new Map(
      selectedPositionFacts.map((item) => [item.position_id, item]),
    )
  }, [selectedPositionFacts])
  const reportBodyPreview = useMemo(() => {
    if (!reportText) {
      return "暂无报告正文。"
    }
    const lines = reportText
      .split(/\r?\n/)
      .map((item) => item.trimEnd())
      .filter(Boolean)
    if (lines.length > 0) {
      return lines.slice(0, 18).join("\n")
    }
    return reportText.slice(0, 1200)
  }, [reportText])
  const feishuStatusRaw = String(feishuPush.status ?? "未推送")
  const feishuStatusLower = feishuStatusRaw.toLowerCase()
  const feishuStatusLabel =
    feishuStatusLower === "sent"
      ? "已成功推送"
      : feishuStatusLower === "pushed"
        ? "已推送"
        : feishuStatusLower === "skipped"
          ? "未触发"
          : feishuStatusLower === "failed"
            ? "推送失败"
            : feishuStatusRaw
  const feishuStatusHint =
    feishuStatusLower === "skipped"
      ? String(
          feishuPush.error_message ??
            "当前用户未配置个人认证的飞书 webhook，所以没有发送。",
        )
      : feishuStatusLower === "failed"
        ? String(feishuPush.error_message ?? "飞书推送失败")
        : ""
  const scrollToFullReport = () => {
    document.getElementById("full-report-body")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    })
  }
  const openAnalysisTask = (taskIdToOpen: string) => {
    void navigate({
      to: "/gwy/analysis",
      search: { task_id: taskIdToOpen },
    })
  }
  const downloadCurrentReport = () => {
    if (!task) {
      return
    }
    const safeTitle =
      (snapshot?.title || "岗位分析报告")
        .replace(/[\\/:*?"<>|]+/g, "_")
        .trim() || "岗位分析报告"
    const timestamp = (
      task.finished_at ||
      task.created_at ||
      new Date().toISOString()
    )
      .replace(/[:.]/g, "-")
      .replace(/\s+/g, "_")
    const payload = [
      `${snapshot?.title || "岗位分析报告"}`,
      `任务ID: ${task.id}`,
      `快照ID: ${snapshot?.id || task.snapshot_id}`,
      `生成时间: ${reportGeneratedAt}`,
      `任务状态: ${task.status}`,
      `任务阶段: ${task.stage}`,
      "",
      reportText || "暂无报告正文。",
    ].join("\n")
    const blob = new Blob([payload], { type: "text/plain;charset=utf-8" })
    const url = window.URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${safeTitle}_${timestamp}.txt`
    anchor.click()
    window.URL.revokeObjectURL(url)
  }
  const distributionStats = useMemo(
    () => [
      {
        label: "部门分布",
        field: "department_name" as const,
        items: selectedPositionFacts,
      },
      {
        label: "学历要求分布",
        field: "education_requirement" as const,
        items: selectedPositionFacts,
      },
      {
        label: "政治面貌要求分布",
        field: "political_status_requirement" as const,
        items: selectedPositionFacts,
      },
      {
        label: "专业限制强弱分布",
        field: "major_requirement" as const,
        items: selectedPositionFacts,
      },
    ],
    [selectedPositionFacts],
  )
  const progressPercent = task
    ? task.status === "completed"
      ? 100
      : task.status === "failed"
        ? 100
        : Math.min(92, 20 + traceEntries.length * 8)
    : 0

  useEffect(() => {
    if (!taskId) {
      return
    }
    const isRunning =
      task?.status === "running" ||
      task?.status === "pending" ||
      task?.status === "queued"
    if (!isRunning) {
      return
    }

    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const taskResponse = await GwyAnalysisService.getPositionAnalysisTask(
            {
              taskId,
            },
          )
          if (taskResponse.snapshot_id !== snapshot?.id) {
            const snapshotResponse =
              await GwyAnalysisService.getPositionAnalysisSnapshot({
                snapshotId: taskResponse.snapshot_id,
              })
            setSnapshot(snapshotResponse)
          }
          setTask(taskResponse)
        } catch {
          // Best effort polling only.
        }
      })()
    }, 2500)

    return () => window.clearInterval(timer)
  }, [snapshot?.id, task?.status, taskId])

  useEffect(() => {
    if (typeof window === "undefined") {
      return
    }
    const raw = window.localStorage.getItem("gwy.analysis.history")
    if (!raw) {
      return
    }
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        setAnalysisHistory(
          parsed
            .map((item) => normalizeAnalysisHistoryItem(item))
            .filter((item): item is AnalysisHistoryItem => item !== null),
        )
      }
    } catch {
      // Ignore malformed local cache.
    }
  }, [])

  useEffect(() => {
    if (!task || !snapshot || typeof window === "undefined") {
      return
    }
    const nextEntry: AnalysisHistoryItem = {
      task_id: task.id,
      snapshot_id: snapshot.id,
      title: snapshot.title || "岗位分析报告",
      finished_at: task.finished_at || "",
      created_at: task.created_at || "",
      status: task.status,
      stage: task.stage,
    }
    setAnalysisHistory((current) => {
      const next = [
        nextEntry,
        ...current.filter((item) => item.task_id !== nextEntry.task_id),
      ].slice(0, 12)
      window.localStorage.setItem("gwy.analysis.history", JSON.stringify(next))
      return next
    })
  }, [snapshot, task])

  const submitSupplement = async () => {
    if (!snapshot || !task) {
      return
    }
    const supplemental = supplementText.trim()
    if (!supplemental) {
      setError("请先输入补充信息，再继续分析。")
      return
    }
    setSupplementSubmitting(true)
    setError(null)
    try {
      const payload = buildSupplementedTaskRequest(snapshot, supplemental)
      const response = await GwyAnalysisService.createPositionAnalysisTask({
        requestBody: payload,
      })
      await navigate({
        to: "/gwy/analysis",
        search: { task_id: response.task_id },
      })
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "补充信息提交失败，请稍后重试。",
      )
    } finally {
      setSupplementSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-1 flex-col gap-6 p-4 pb-10 md:p-6">
      <header className="rounded-3xl border border-slate-200 bg-white/90 px-5 py-4 shadow-sm backdrop-blur">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-slate-900">
              <Sparkles className="h-5 w-5 text-sky-600" />
              <h1 className="text-xl font-semibold">岗位分析报告</h1>
            </div>
            <p className="max-w-3xl text-sm leading-6 text-slate-500">
              这里展示独立的分析任务结果、证据引用和可见的 Agent
              执行轨迹。筛选页只负责保存快照和发起任务，报告会在这里集中查看。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" className="gap-2">
              <RouterLink to="/gwy/positions">
                <ChevronLeft className="h-4 w-4" />
                返回筛选页
              </RouterLink>
            </Button>
            {task ? (
              <>
                <Badge variant="outline" className="bg-white">
                  状态 {task.status}
                </Badge>
                <Badge variant="outline" className="bg-white">
                  阶段 {task.stage}
                </Badge>
              </>
            ) : null}
          </div>
        </div>
      </header>

      {isClarification ? (
        <section className="rounded-3xl border border-amber-200 bg-amber-50 px-5 py-4 text-amber-950 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Sparkles className="h-4 w-4" />
            当前需要补充信息，系统先暂停最终报告
          </div>
          <div className="mt-2 text-sm leading-6 text-amber-900/90">
            这一步还缺少足够的报考约束信息，先把下面的问题补充给我，再继续生成完整分析。
          </div>
          {missingFields.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {missingFields.map((item) => (
                <Badge key={item} variant="outline" className="bg-white">
                  {item}
                </Badge>
              ))}
            </div>
          ) : null}
          {clarifyingQuestions.length > 0 ? (
            <div className="mt-3 rounded-2xl border border-amber-200 bg-white/70 px-4 py-3 text-sm text-slate-800">
              <div className="font-medium text-slate-900">追问列表</div>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                {clarifyingQuestions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ol>
            </div>
          ) : null}
          <div className="mt-3 rounded-2xl border border-amber-200 bg-white px-4 py-3">
            <div className="text-sm font-medium text-slate-900">
              直接补充信息
            </div>
            <div className="mt-1 text-xs leading-5 text-slate-500">
              可以直接输入 `专业=计算机类，学历=本科，学位=学士`
              这样的格式，系统会把内容回填后重新分析。
            </div>
            <textarea
              value={supplementText}
              onChange={(event) => setSupplementText(event.target.value)}
              className="mt-3 min-h-[112px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
              placeholder="例如：专业=计算机类，学历=本科，学位=学士。也可以补充地区、政治面貌、备注等。"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                onClick={() => {
                  void submitSupplement()
                }}
                disabled={supplementSubmitting}
                className="gap-2"
              >
                {supplementSubmitting ? "正在重新分析..." : "补充并重新分析"}
              </Button>
              <Button
                variant="outline"
                onClick={() => setSupplementText("")}
                disabled={supplementSubmitting}
              >
                清空
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      <section className="rounded-3xl border border-slate-200 bg-white/90 px-5 py-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">历史报告</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">
              这里会保留本机浏览器里的最近分析任务，重新登录后也能继续查看和下载。
            </div>
          </div>
          <Badge variant="outline" className="bg-white">
            {analysisHistory.length} 条
          </Badge>
        </div>
        <div className="mt-3 space-y-2">
          {analysisHistory.length > 0 ? (
            analysisHistory.map((item) => (
              <button
                key={item.task_id}
                type="button"
                onClick={() => openAnalysisTask(item.task_id)}
                className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition hover:border-sky-300 hover:bg-sky-50"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900">
                      {item.title}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {formatDateTime(item.finished_at || item.created_at)}
                    </div>
                  </div>
                  <Badge variant="outline" className="bg-white">
                    {item.status}
                  </Badge>
                </div>
              </button>
            ))
          ) : (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
              暂无历史报告，生成一次分析后会自动记录。
            </div>
          )}
        </div>
      </section>

      {task ? (
        <section className="rounded-[28px] border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="text-xs uppercase tracking-[0.2em] text-slate-400">
                Report Summary
              </div>
              <div className="text-xl font-semibold text-slate-900">
                {snapshot?.title || "岗位智能分析报告"}
              </div>
              <div className="max-w-4xl text-sm leading-6 text-slate-500">
                先看用户画像和候选池，再看历史趋势和推荐排序，最后再看 Agent
                轨迹与证据引用。这个区域就是报告页的“摘要首页”。
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className="bg-white">
                当前岗位池 {recommendationBuckets.total} 条
              </Badge>
              <Badge variant="outline" className="bg-white">
                完全匹配 {recommendationBuckets.exact} 条
              </Badge>
              <Badge variant="outline" className="bg-white">
                风险岗位{" "}
                {recommendationBuckets.risk +
                  recommendationBuckets.notRecommended}{" "}
                条
              </Badge>
            </div>
            <div className="text-xs text-slate-500">
              报告生成于 {reportGeneratedAt}
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">
                    用户画像摘要
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    本次分析使用的核心条件一目了然。
                  </div>
                </div>
                <Badge variant="outline" className="bg-white">
                  {Object.keys(userProfile).length > 0 ? "已配置" : "未提供"}
                </Badge>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {(
                  [
                    ["专业", userProfile.major],
                    ["学历", userProfile.education],
                    ["学位", userProfile.degree],
                    ["政治面貌", userProfile.political_status],
                    ["基层年限", userProfile.grassroots_experience_years],
                    [
                      "应届身份",
                      userProfile.is_fresh_graduate ? "应届" : "非应届",
                    ],
                    [
                      "地区偏好",
                      toStringList(userProfile.target_regions).join("、"),
                    ],
                    [
                      "部门偏好",
                      toStringList(userProfile.desired_departments).join("、"),
                    ],
                  ] as Array<[string, unknown]>
                ).map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm"
                  >
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                      {label}
                    </div>
                    <div className="mt-2 text-sm leading-6 text-slate-900">
                      {formatUnknown(value)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">
                    候选岗位池概览
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    这里先看整体，再决定要不要继续缩小范围。
                  </div>
                </div>
                <Badge variant="outline" className="bg-white">
                  {recommendationBuckets.total} 条
                </Badge>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="完全匹配"
                  value={String(recommendationBuckets.exact)}
                />
                <MetricCard
                  label="基本匹配"
                  value={String(recommendationBuckets.basic)}
                />
                <MetricCard
                  label="风险岗位"
                  value={String(recommendationBuckets.risk)}
                />
                <MetricCard
                  label="不建议"
                  value={String(recommendationBuckets.notRecommended)}
                />
              </div>
              <div className="mt-4 grid gap-3 xl:grid-cols-2">
                {distributionStats.slice(0, 2).map((entry) => (
                  <div
                    key={entry.label}
                    className="rounded-2xl border border-white bg-white px-4 py-4 shadow-sm"
                  >
                    <div className="text-sm font-medium text-slate-900">
                      {entry.label}
                    </div>
                    <div className="mt-3 grid gap-3 lg:grid-cols-[160px_minmax(0,1fr)]">
                      <MiniDonutChart
                        entries={buildDistributionEntries(
                          entry.items,
                          entry.field,
                        )}
                      />
                      <div className="space-y-2">
                        {buildDistributionEntries(entry.items, entry.field)
                          .slice(0, 4)
                          .map((item) => (
                            <div
                              key={item.label}
                              className="flex items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2 text-sm"
                            >
                              <span className="truncate text-slate-700">
                                {item.label}
                              </span>
                              <span className="font-medium text-slate-900">
                                {item.count}
                              </span>
                            </div>
                          ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <TrendCard
              title="2024-2026 招录人数"
              note="观察是否扩招或缩招"
              data={historyYearStats.map((item) => ({
                label: String(item.year),
                value: item.recruitCount,
              }))}
            />
            <TrendCard
              title="报录比 / 竞争热度"
              note="2026 若无最终报名，只展示当前热度"
              data={historyYearStats.map((item) => ({
                label: String(item.year),
                value: item.ratio ?? 0,
              }))}
            />
            <TrendCard
              title="进面分数趋势"
              note="若缺少核验数据，会明确标注无法确认"
              data={historyYearStats.map((item) => ({
                label: String(item.year),
                value: item.score ?? 0,
              }))}
            />
          </div>

          <div className="mt-4 rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-900">
                  报告正文预览
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  先直接看正文摘录，不用往下滑；点右侧按钮可跳到全文。
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="bg-white"
                  onClick={scrollToFullReport}
                >
                  跳到全文
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="bg-white"
                  onClick={downloadCurrentReport}
                  disabled={!task}
                >
                  下载报告
                </Button>
              </div>
            </div>
            <pre className="mt-3 max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-2xl border border-white bg-white px-4 py-4 text-[14px] leading-7 text-slate-800 shadow-sm">
              {reportBodyPreview}
            </pre>
          </div>

          <StudyPlanPanel studyPlan={studyPlan} />

          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">
                    推荐结论总览
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    先看哪个最值得投递，再看哪些适合冲刺或备选。
                  </div>
                </div>
                <Badge variant="outline" className="bg-white">
                  {topRecommendations.length} 条
                </Badge>
              </div>
              <div className="mt-3 space-y-2">
                {topRecommendations.slice(0, 5).map((item) => (
                  <div
                    key={`${item.position_id}-${item.index}`}
                    className="flex items-center justify-between gap-3 rounded-2xl border border-white bg-white px-4 py-3 shadow-sm"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-900">
                        {item.department_name || item.job_title || "未知岗位"}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {item.office_name || "无办公处信息"}
                      </div>
                    </div>
                    <Badge variant="outline" className="bg-slate-50">
                      {recommendationLabel(
                        item.recommend_level,
                        item.risk_level,
                      )}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">
                    重点岗位预览
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    用研究结果和推荐结果对上，方便快速判断。
                  </div>
                </div>
                <Badge variant="outline" className="bg-white">
                  {topResearches.length} 条
                </Badge>
              </div>
              <div className="mt-3 space-y-2">
                {topResearches.slice(0, 5).map((item) => {
                  const fact = selectedFactById.get(item.position_id)
                  return (
                    <div
                      key={`${item.position_id}-${item.index}`}
                      className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-slate-900">
                            {item.department_name ||
                              item.job_title ||
                              "未知岗位"}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            {item.job_title || "未知职位"}
                          </div>
                        </div>
                        <Badge
                          variant="outline"
                          className={
                            fact
                              ? "bg-slate-50"
                              : "border-amber-200 bg-amber-50 text-amber-700"
                          }
                        >
                          {fact
                            ? recommendationLabel(
                                fact.recommend_level,
                                fact.risk_level,
                              )
                            : "待补证"}
                        </Badge>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          <div className="mt-4 rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-900">
                  总体进度
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  用一个简洁的进度条把 Agent 处理状态直观展示出来。
                </div>
              </div>
              <Badge variant="outline" className="bg-white">
                {progressPercent}%
              </Badge>
            </div>
            <div className="mt-3">
              <ProgressBar percent={progressPercent} />
            </div>
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_380px]">
        <section className="flex flex-col rounded-3xl border border-slate-200 bg-white/90 shadow-sm">
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <History className="h-4 w-4 text-sky-600" />
              任务信息
            </div>
          </div>
          <div className="space-y-4 px-5 py-4 text-sm">
            {loading ? (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-slate-500">
                正在加载分析任务...
              </div>
            ) : error ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-rose-700">
                {error}
              </div>
            ) : task ? (
              <>
                <InfoRow label="任务ID" value={task.id} />
                <InfoRow label="快照ID" value={task.snapshot_id} />
                <InfoRow
                  label="创建时间"
                  value={formatDateTime(task.created_at)}
                />
                <InfoRow
                  label="开始时间"
                  value={formatDateTime(task.started_at)}
                />
                <InfoRow
                  label="结束时间"
                  value={formatDateTime(task.finished_at)}
                />
                <InfoRow label="状态" value={task.status} />
                <InfoRow label="阶段" value={task.stage} />
                <InfoRow
                  label="快照标题"
                  value={snapshot?.title || "未命名快照"}
                />
                <InfoRow
                  label="选中岗位"
                  value={`${snapshotSelected.length} 条`}
                />
                <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    列信息
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {snapshotColumns.length > 0 ? (
                      snapshotColumns.slice(0, 10).map((column) => (
                        <Badge key={column} variant="secondary">
                          {column}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-sm text-slate-500">未配置</span>
                    )}
                  </div>
                </section>
                <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    筛选条件
                  </div>
                  <div className="mt-2 space-y-2">
                    {Object.entries(snapshotFilters).length > 0 ? (
                      Object.entries(snapshotFilters).map(([key, value]) => (
                        <div
                          key={key}
                          className="flex items-start justify-between gap-3"
                        >
                          <span className="text-slate-500">{key}</span>
                          <span className="text-right text-slate-900">
                            {formatCompactValue(value)}
                          </span>
                        </div>
                      ))
                    ) : (
                      <span className="text-sm text-slate-500">
                        未设置筛选条件
                      </span>
                    )}
                  </div>
                </section>
                {clarifyingQuestions.length > 0 ? (
                  <section className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
                    <div className="text-xs font-medium uppercase tracking-wide text-amber-700">
                      追问信息
                    </div>
                    <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-6 text-slate-800">
                      {clarifyingQuestions.map((question) => (
                        <li key={question}>{question}</li>
                      ))}
                    </ol>
                  </section>
                ) : null}
              </>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-slate-500">
                还没有分析任务，回到岗位筛选页后保存快照并生成报告。
              </div>
            )}
          </div>
        </section>

        <section
          id="full-report-body"
          className="flex flex-col rounded-3xl border border-slate-200 bg-white/95 shadow-sm"
        >
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <FileText className="h-4 w-4 text-sky-600" />
              报告正文
            </div>
          </div>
          <div className="max-h-[78vh] overflow-y-auto px-5 py-5 pr-3">
            {loading ? (
              <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
                正在加载报告...
              </div>
            ) : task ? (
              <div className="space-y-4">
                <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-slate-900">
                        Agent 进度
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        默认展示摘要，点击右侧轨迹可以查看每一步的输入、输出和证据。
                      </div>
                    </div>
                    <Badge variant="outline" className="bg-white">
                      {agentJourney.length} 步
                    </Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {agentJourney.slice(-8).map((item) => (
                      <Badge
                        key={`${item.step}-${item.status}-${item.elapsed_ms}`}
                        variant="outline"
                        className="bg-white"
                      >
                        {item.step}
                        {item.elapsed_ms ? ` · ${item.elapsed_ms}ms` : ""}
                      </Badge>
                    ))}
                  </div>
                </section>

                {reportOutline.length > 0 ? (
                  <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">
                      报告提纲
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {reportOutline.map((item) => (
                        <Badge
                          key={item}
                          variant="outline"
                          className="bg-white"
                        >
                          {item}
                        </Badge>
                      ))}
                    </div>
                  </section>
                ) : null}

                {recommendationContext.query ||
                recommendationContextRecommendations.length > 0 ? (
                  <section className="rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          前置推荐与规划
                        </div>
                        <div className="mt-1 text-xs leading-5 text-slate-500">
                          这里展示推荐 Agent
                          在进入岗位分析前先做了什么规划，以及它给出的初筛结论。
                        </div>
                      </div>
                      <Badge variant="outline" className="bg-slate-50">
                        {String(recommendationContext.status ?? "completed")}
                      </Badge>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                      <InfoRow
                        label="推荐查询"
                        value={recommendationContext.query ?? ""}
                      />
                      <InfoRow
                        label="推荐范围"
                        value={`年份 ${recommendationContext.year ?? "未知"} / ${recommendationContext.exam_type ?? "未知"} / Top ${recommendationContext.top_k ?? "未知"}`}
                      />
                    </div>
                    {recommendationContext.answer ? (
                      <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700">
                        {recommendationContext.answer}
                      </div>
                    ) : null}
                    {recommendationContext.summary &&
                    Object.keys(recommendationContext.summary).length > 0 ? (
                      <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600">
                        <div className="font-medium text-slate-900">
                          推荐摘要
                        </div>
                        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words">
                          {JSON.stringify(
                            recommendationContext.summary,
                            null,
                            2,
                          )}
                        </pre>
                      </div>
                    ) : null}
                    {recommendationContextRecommendations.length > 0 ? (
                      <div className="mt-3 grid gap-3">
                        {recommendationContextRecommendations
                          .slice(0, 3)
                          .map((item, index) => (
                            <div
                              key={`${item.position_id}-${index}`}
                              className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
                            >
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                  <div className="text-sm font-medium text-slate-900">
                                    {item.department_name ||
                                      item.job_title ||
                                      "未知岗位"}
                                  </div>
                                  <div className="mt-1 text-xs text-slate-500">
                                    {item.office_name || "未知科室"} /{" "}
                                    {item.job_title || "未知职务"}
                                  </div>
                                </div>
                                <Badge
                                  variant="outline"
                                  className="bg-slate-50"
                                >
                                  {recommendationLabel(
                                    String(item.recommend_level ?? ""),
                                    String(item.risk_level ?? ""),
                                  )}
                                </Badge>
                              </div>
                              <div className="mt-2 grid gap-2 text-xs text-slate-600 md:grid-cols-3">
                                <div>分数: {formatUnknown(item.score)}</div>
                                <div>
                                  风险: {formatUnknown(item.risk_level)}
                                </div>
                                <div>
                                  招录: {formatUnknown(item.recruit_count)}
                                </div>
                              </div>
                            </div>
                          ))}
                      </div>
                    ) : null}
                  </section>
                ) : null}

                {analysisStrategy ? (
                  <section className="overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 px-4 py-4 text-white shadow-lg shadow-slate-900/10">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-white">
                          Agent 策略地图
                        </div>
                        <div className="mt-1 text-xs leading-5 text-slate-300">
                          先计划，再探索，再验证。这里展示的是这次分析到底走了什么路线。
                        </div>
                      </div>
                      <Badge
                        variant="outline"
                        className="border-white/20 bg-white/10 text-white"
                      >
                        {analysisStrategy.strategy_name || "unknown"}
                      </Badge>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge
                        variant="outline"
                        className="border-white/20 bg-white/10 text-white"
                      >
                        {analysisStrategy.planning_strategy || "plan_and_solve"}
                      </Badge>
                      <Badge
                        variant="outline"
                        className="border-white/20 bg-white/10 text-white"
                      >
                        {analysisStrategy.evidence_strategy || "react"}
                      </Badge>
                      <Badge
                        variant="outline"
                        className="border-white/20 bg-white/10 text-white"
                      >
                        {analysisStrategy.decision_style || "strategy"}
                      </Badge>
                      <Badge
                        variant="outline"
                        className="border-white/20 bg-white/10 text-white"
                      >
                        {analysisStrategy.strategy_source || "deterministic"}
                      </Badge>
                    </div>

                    {strategySummaryLines.length > 0 ? (
                      <ul className="mt-4 space-y-2 text-sm leading-6 text-slate-100">
                        {strategySummaryLines.map((line) => (
                          <li key={line} className="flex gap-2">
                            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-300" />
                            <span>{line}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}

                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                        <div className="text-xs uppercase tracking-wide text-slate-300">
                          优先来源
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {(analysisStrategy.priority_sources || []).length >
                          0 ? (
                            analysisStrategy.priority_sources.map((source) => (
                              <Badge
                                key={source}
                                variant="outline"
                                className="border-white/20 bg-white/10 text-white"
                              >
                                {source}
                              </Badge>
                            ))
                          ) : (
                            <span className="text-sm text-slate-300">暂无</span>
                          )}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                        <div className="text-xs uppercase tracking-wide text-slate-300">
                          研究预算
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-slate-100">
                          <div className="rounded-xl bg-white/5 px-3 py-2">
                            <div className="text-[11px] text-slate-400">
                              岗位数
                            </div>
                            <div className="mt-1 font-medium">
                              {String(
                                analysisStrategy.research_budget
                                  ?.selected_count ?? "0",
                              )}
                            </div>
                          </div>
                          <div className="rounded-xl bg-white/5 px-3 py-2">
                            <div className="text-[11px] text-slate-400">
                              补证
                            </div>
                            <div className="mt-1 font-medium">
                              {analysisStrategy.research_budget
                                ?.web_search_enabled
                                ? "启用"
                                : "关闭"}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {strategyTargets.length > 0 ? (
                      <div className="mt-4 space-y-3">
                        <div className="text-xs uppercase tracking-wide text-slate-300">
                          研究目标
                        </div>
                        <div className="grid gap-3">
                          {strategyTargets.slice(0, 3).map((target) => (
                            <div
                              key={`${target.position_id}-${target.index}`}
                              className="rounded-2xl border border-white/10 bg-white/5 p-3"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="truncate text-sm font-medium text-white">
                                    {target.department_name ||
                                      target.job_title ||
                                      "未命名岗位"}
                                  </div>
                                  <div className="mt-1 text-xs text-slate-300">
                                    {target.job_title || "岗位名称未知"}
                                    {target.position_code
                                      ? ` · ${target.position_code}`
                                      : ""}
                                  </div>
                                </div>
                                <Badge
                                  variant="outline"
                                  className="border-white/20 bg-white/10 text-white"
                                >
                                  {target.history_priority || "unknown"}
                                </Badge>
                              </div>
                              <div className="mt-2 flex flex-wrap gap-2">
                                <Badge
                                  variant="outline"
                                  className="border-cyan-300/40 bg-cyan-300/10 text-cyan-50"
                                >
                                  {target.needs_web_search
                                    ? "需要外网补证"
                                    : "本地历史优先"}
                                </Badge>
                                {(target.focus || [])
                                  .slice(0, 4)
                                  .map((item) => (
                                    <Badge
                                      key={item}
                                      variant="outline"
                                      className="border-white/20 bg-white/10 text-white"
                                    >
                                      {item}
                                    </Badge>
                                  ))}
                                {(target.search_queries || [])
                                  .slice(0, 3)
                                  .map((item) => (
                                    <Badge
                                      key={`${target.position_id}-query-${item}`}
                                      variant="outline"
                                      className="border-emerald-300/40 bg-emerald-300/10 text-emerald-50"
                                    >
                                      查询: {item}
                                    </Badge>
                                  ))}
                                {(target.retry_queries || [])
                                  .slice(0, 2)
                                  .map((item) => (
                                    <Badge
                                      key={`${target.position_id}-retry-${item}`}
                                      variant="outline"
                                      className="border-amber-300/40 bg-amber-300/10 text-amber-50"
                                    >
                                      重试: {item}
                                    </Badge>
                                  ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </section>
                ) : null}

                {analysisDecisionFocusPositions.length > 0 ||
                analysisDecisionNotes.length > 0 ? (
                  <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          Agent 决策摘要
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          先观察缺口，再补证，最后决定哪些岗位作为主分析对象。
                        </div>
                      </div>
                      <Badge variant="outline" className="bg-white">
                        {analysisDecisionFocusPositions.length} 个重点岗位
                      </Badge>
                    </div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <div className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm">
                        <div className="text-xs uppercase tracking-wide text-slate-500">
                          搜索覆盖
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                          <div className="rounded-xl bg-slate-50 px-3 py-2">
                            <div className="text-[11px] text-slate-500">
                              有证据
                            </div>
                            <div className="mt-1 font-medium text-slate-900">
                              {Number(
                                analysisSearchCoverage.with_web_evidence ?? 0,
                              )}
                            </div>
                          </div>
                          <div className="rounded-xl bg-slate-50 px-3 py-2">
                            <div className="text-[11px] text-slate-500">
                              无证据
                            </div>
                            <div className="mt-1 font-medium text-slate-900">
                              {Number(
                                analysisSearchCoverage.without_web_evidence ??
                                  0,
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm">
                        <div className="text-xs uppercase tracking-wide text-slate-500">
                          决策说明
                        </div>
                        <div className="mt-2 space-y-2 text-sm leading-6 text-slate-700">
                          {analysisDecisionNotes.length > 0 ? (
                            analysisDecisionNotes.slice(0, 4).map((note) => (
                              <div
                                key={note}
                                className="rounded-xl bg-slate-50 px-3 py-2"
                              >
                                {note}
                              </div>
                            ))
                          ) : (
                            <div className="rounded-xl bg-slate-50 px-3 py-2">
                              当前报告按补证后的重点岗位生成。
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 space-y-2">
                      {analysisDecisionFocusPositions
                        .slice(0, 4)
                        .map((item) => (
                          <div
                            key={`${item.position_id || item.position_label}-${item.score}`}
                            className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-medium text-slate-900">
                                  {item.position_label || "未知岗位"}
                                </div>
                                <div className="mt-1 text-xs text-slate-500">
                                  重点分值 {Number(item.score ?? 0).toFixed(1)}{" "}
                                  · 外网命中 {Number(item.web_hit_count ?? 0)}{" "}
                                  条
                                </div>
                              </div>
                              <Badge variant="outline" className="bg-slate-50">
                                {Array.isArray(item.gaps) &&
                                item.gaps.length > 0
                                  ? `缺口 ${item.gaps.length} 项`
                                  : "补证完成"}
                              </Badge>
                            </div>
                          </div>
                        ))}
                    </div>
                  </section>
                ) : null}

                <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-slate-900">
                        候选岗位池概览
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        这里基于岗位池和历史数据汇总出一个更接近报告的全局视角。
                      </div>
                    </div>
                    <Badge variant="outline" className="bg-white">
                      {selectedPositionFacts.length} 条候选
                    </Badge>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    <MetricCard
                      label="完全匹配"
                      value={String(
                        selectedPositionFacts.filter((item) =>
                          ["strong_match", "good_match"].includes(
                            String(item.recommend_level || "").toLowerCase(),
                          ),
                        ).length,
                      )}
                    />
                    <MetricCard
                      label="风险岗位"
                      value={String(
                        selectedPositionFacts.filter(
                          (item) =>
                            String(item.risk_level || "").toLowerCase() ===
                              "high" || Boolean(item.need_manual_confirm),
                        ).length,
                      )}
                    />
                    <MetricCard
                      label="推荐结果"
                      value={String(recommendationFacts.length)}
                    />
                  </div>
                  <div className="mt-3 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
                    <div className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm">
                      <div className="font-medium text-slate-900">部门分布</div>
                      <div className="mt-2 leading-6">
                        {summarizeCounter(
                          selectedPositionFacts,
                          "department_name",
                        )}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm">
                      <div className="font-medium text-slate-900">
                        学历要求分布
                      </div>
                      <div className="mt-2 leading-6">
                        {summarizeCounter(
                          selectedPositionFacts,
                          "education_requirement",
                        )}
                      </div>
                    </div>
                  </div>
                </section>

                {false && positionResearches.length > 0 ? (
                  <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          重点岗位逐项分析
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          展示每个候选岗位的历史招录、报录比和补证情况。
                        </div>
                      </div>
                      <Badge variant="outline" className="bg-white">
                        {positionResearches.length} 项
                      </Badge>
                    </div>
                    <div className="mt-3 grid gap-3">
                      {positionResearches.slice(0, 5).map((item) => {
                        const history = item.history || {}
                        const historyYears = Array.isArray(
                          history.history_years,
                        )
                          ? history.history_years.map((year) => String(year))
                          : []
                        const snippet =
                          item.analysis_text
                            ?.split("\n")
                            .map((line) => line.trim())
                            .find(
                              (line) => line.length > 0 && !line.startsWith("#"),
                            ) || "暂无分析摘要"
                        const firstQuery = String(
                          item.web_search_attempts[0]?.query ||
                            item.web_search_attempts[0]?.search_query ||
                            "",
                        ).trim()
                        const browserFallbackCount = countBrowserFallbacks(
                          item.web_search_attempts,
                        )
                        const webTopTitles = item.web_results
                          .slice(0, 3)
                          .map((result) =>
                            String(
                              result.title ||
                                result.doc_title ||
                                result.source ||
                                "",
                            ).trim(),
                          )
                          .filter(Boolean)
                        return (
                          <div
                            key={`${item.position_id}-${item.index}`}
                            className="rounded-2xl border border-white bg-white px-4 py-4 shadow-sm"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <div className="text-sm font-semibold text-slate-900">
                                  {item.department_name ||
                                    item.job_title ||
                                    "未命名岗位"}
                                </div>
                                <div className="mt-1 text-xs text-slate-500">
                                  {item.office_name || "无办公处室"} ·{" "}
                                  {item.job_title || "岗位名称未知"}
                                  {item.position_code
                                    ? ` · ${item.position_code}`
                                    : ""}
                                </div>
                              </div>
                              <Badge variant="outline" className="bg-slate-50">
                                {historyYears.length > 0
                                  ? historyYears.join("、")
                                  : "无历史年份"}
                              </Badge>
                            </div>
                            <div className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                              <div>
                                历史招录:{" "}
                                {formatUnknown(history.latest_recruit_count)}
                              </div>
                              <div>
                                历史报录比:{" "}
                                {formatUnknown(history.latest_interview_ratio)}
                              </div>
                              <div>外网补证: {item.web_results.length} 条</div>
                              <div>
                                风险偏好:{" "}
                                {formatUnknown(history.recruit_count_trend)}
                              </div>
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                              <Badge variant="outline" className="bg-white">
                                检索尝试 {item.web_search_attempts.length} 次
                              </Badge>
                              <Badge variant="outline" className="bg-white">
                                重试{" "}
                                {countWebSearchRetries(
                                  item.web_search_attempts,
                                )}{" "}
                                次
                              </Badge>
                              <Badge variant="outline" className="bg-white">
                                外网命中 {item.web_results.length} 条
                              </Badge>
                            </div>
                            {firstQuery || webTopTitles.length > 0 ? (
                              <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50/80 px-3 py-3 text-xs leading-5 text-slate-700">
                                <div className="font-medium text-amber-800">
                                  外网补证摘要
                                </div>
                                {firstQuery ? (
                                  <div className="mt-1">
                                    查询词：{firstQuery}
                                  </div>
                                ) : null}
                                <div className="mt-1">
                                  回填方式：
                                  {browserFallbackCount > 0
                                    ? ` 浏览器回填 ${browserFallbackCount} 次`
                                    : " 主要依赖搜索结果正文抓取"}
                                </div>
                                {webTopTitles.length > 0 ? (
                                  <div className="mt-1">
                                    主要来源：{webTopTitles.join("、")}
                                  </div>
                                ) : null}
                              </div>
                            ) : null}
                            <div className="mt-3 rounded-xl bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-700">
                              {snippet}
                            </div>
                            {item.web_results.length > 0 ? (
                              <div className="mt-3 rounded-xl border border-sky-100 bg-sky-50/70 px-3 py-3">
                                <div className="text-xs font-medium text-sky-700">
                                  外网补证预览
                                </div>
                                <div className="mt-2 max-h-32 space-y-2 overflow-y-auto pr-1 text-xs leading-5 text-slate-600">
                                  {item.web_results
                                    .slice(0, 3)
                                    .map((result, resultIndex) => {
                                      const resultTitle = String(
                                        result.title ||
                                          result.doc_title ||
                                          result.source ||
                                          "未命名线索",
                                      ).trim()
                                      const resultSource = String(
                                        result.source ||
                                          result.retrieved_via ||
                                          result.final_url ||
                                          "",
                                      ).trim()
                                      const resultSnippet = String(
                                        result.snippet ||
                                          result.content ||
                                          result.summary ||
                                          "",
                                      ).trim()
                                      const resultUrl = String(
                                        result.url ||
                                          result.final_url ||
                                          result.link ||
                                          "",
                                      ).trim()
                                      return (
                                        <div
                                          key={`${item.position_id}-${item.index}-web-${resultIndex}`}
                                          className="rounded-lg border border-sky-100 bg-white px-2 py-2"
                                        >
                                          <div className="font-medium text-slate-800">
                                            {resultTitle}
                                          </div>
                                          <div className="mt-1 text-[11px] text-slate-500">
                                            {resultSource
                                              ? `来源：${resultSource}`
                                              : "来源：未记录"}
                                            {resultUrl
                                              ? ` · ${truncateUrl(resultUrl)}`
                                              : ""}
                                          </div>
                                          {resultSnippet ? (
                                            <div className="mt-1 text-[11px] leading-5 text-slate-600">
                                              {resultSnippet}
                                            </div>
                                          ) : null}
                                        </div>
                                      )
                                    })}
                                  {item.web_results.length > 3 ? (
                                    <div className="text-[11px] text-slate-400">
                                      还有 {item.web_results.length - 3}{" "}
                                      条外网证据未展开
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  </section>
                ) : null}

                {positionResearches.length > 0 ? (
                  <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          缺口 / 搜索目标 / 搜索结果
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          这部分只展示每个岗位真正缺了什么、Agent 具体搜了什么、最后拿到了什么证据。
                        </div>
                      </div>
                      <Badge variant="outline" className="bg-white">
                        {positionResearches.length} 个岗位
                      </Badge>
                    </div>
                    <div className="mt-3 space-y-3">
                      {positionResearches.slice(0, 5).map((item) => {
                        const focusItem =
                          analysisDecisionFocusById.get(item.position_id) || null
                        const strategyTarget = item.strategy_target
                        const gapLabels = toStringList(focusItem?.gaps)
                          .map((gap) => describeResearchGap(gap))
                          .filter(Boolean)
                        const targetQueries = Array.from(
                          new Set([
                            ...toStringList(strategyTarget?.search_queries),
                            ...toStringList(strategyTarget?.retry_queries),
                          ]),
                        )
                        const resultCards = item.web_results.slice(0, 3)
                        return (
                          <div
                            key={`research-path-${item.position_id}-${item.index}`}
                            className="rounded-2xl border border-white bg-white px-4 py-4 shadow-sm"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-semibold text-slate-900">
                                  {item.department_name ||
                                    item.job_title ||
                                    "未知岗位"}
                                </div>
                                <div className="mt-1 text-xs text-slate-500">
                                  {item.office_name || "未知单位"} ·{" "}
                                  {item.job_title || "未知职位"}
                                  {item.position_code
                                    ? ` · ${item.position_code}`
                                    : ""}
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <Badge variant="outline" className="bg-slate-50">
                                  {item.history_records.length > 0
                                    ? `历史 ${item.history_records.length} 条`
                                    : "历史缺失"}
                                </Badge>
                                <Badge variant="outline" className="bg-slate-50">
                                  外网 {item.web_results.length} 条
                                </Badge>
                              </div>
                            </div>

                            <div className="mt-3 grid gap-3 lg:grid-cols-3">
                              <div className="rounded-xl border border-rose-100 bg-rose-50/70 px-3 py-3">
                                <div className="text-xs font-medium text-rose-700">
                                  当前缺口
                                </div>
                                <div className="mt-2 flex flex-wrap gap-2">
                                  {gapLabels.length > 0 ? (
                                    gapLabels.map((gap) => (
                                      <Badge
                                        key={`${item.position_id}-${gap}`}
                                        variant="outline"
                                        className="border-rose-200 bg-white text-rose-700"
                                      >
                                        {gap}
                                      </Badge>
                                    ))
                                  ) : (
                                    <span className="text-xs text-slate-400">
                                      暂无显式缺口
                                    </span>
                                  )}
                                </div>
                              </div>

                              <div className="rounded-xl border border-emerald-100 bg-emerald-50/70 px-3 py-3">
                                <div className="text-xs font-medium text-emerald-700">
                                  搜索目标
                                </div>
                                <div className="mt-2 space-y-2">
                                  {strategyTarget?.reason ? (
                                    <div className="rounded-lg bg-white px-3 py-2 text-xs leading-5 text-slate-700">
                                      {strategyTarget.reason}
                                    </div>
                                  ) : null}
                                  <div className="flex flex-wrap gap-2">
                                    {(strategyTarget?.focus || [])
                                      .slice(0, 4)
                                      .map((focus) => (
                                        <Badge
                                          key={`${item.position_id}-focus-${focus}`}
                                          variant="outline"
                                          className="border-emerald-300/40 bg-white text-emerald-800"
                                        >
                                          {focus}
                                        </Badge>
                                      ))}
                                    {strategyTarget?.needs_web_search ? (
                                      <Badge
                                        variant="outline"
                                        className="border-emerald-300/40 bg-emerald-300/10 text-emerald-800"
                                      >
                                        需要外网补证
                                      </Badge>
                                    ) : (
                                      <Badge
                                        variant="outline"
                                        className="border-slate-300 bg-white text-slate-600"
                                      >
                                        本地历史优先
                                      </Badge>
                                    )}
                                  </div>
                                  {targetQueries.length > 0 ? (
                                    <div className="flex flex-wrap gap-2">
                                      {targetQueries.slice(0, 4).map((query) => (
                                        <Badge
                                          key={`${item.position_id}-query-${query}`}
                                          variant="outline"
                                          className="border-cyan-300/40 bg-cyan-300/10 text-cyan-800"
                                        >
                                          {query}
                                        </Badge>
                                      ))}
                                      {targetQueries.length > 4 ? (
                                        <Badge
                                          variant="outline"
                                          className="border-cyan-300/40 bg-cyan-300/10 text-cyan-800"
                                        >
                                          还有 {targetQueries.length - 4} 条
                                        </Badge>
                                      ) : null}
                                    </div>
                                  ) : null}
                                  {toStringList(
                                    strategyTarget?.observation_questions,
                                  ).length > 0 ? (
                                    <div className="space-y-2">
                                      {toStringList(
                                        strategyTarget?.observation_questions,
                                      )
                                        .slice(0, 2)
                                        .map((question) => (
                                          <div
                                            key={`${item.position_id}-question-${question}`}
                                            className="rounded-lg bg-white px-3 py-2 text-xs leading-5 text-slate-700"
                                          >
                                            {question}
                                          </div>
                                        ))}
                                    </div>
                                  ) : null}
                                </div>
                              </div>

                              <div className="rounded-xl border border-sky-100 bg-sky-50/70 px-3 py-3">
                                <div className="text-xs font-medium text-sky-700">
                                  搜索结果
                                </div>
                                <div className="mt-2 space-y-2">
                                  {resultCards.length > 0 ? (
                                    resultCards.map((result, resultIndex) => {
                                      const title = String(
                                        result.title ||
                                          result.doc_title ||
                                          result.source ||
                                          "未命名来源",
                                      ).trim()
                                      const snippet = String(
                                        result.snippet ||
                                          result.content ||
                                          result.summary ||
                                          "",
                                      ).trim()
                                      const url = String(
                                        result.url ||
                                          result.final_url ||
                                          result.link ||
                                          "",
                                      ).trim()
                                      return (
                                        <div
                                          key={`${item.position_id}-result-${resultIndex}`}
                                          className="rounded-lg border border-sky-100 bg-white px-3 py-2"
                                        >
                                          <div className="text-sm font-medium text-slate-800">
                                            {title}
                                          </div>
                                          <div className="mt-1 text-[11px] text-slate-500">
                                            {url ? truncateUrl(url) : "暂无链接"}
                                          </div>
                                          {snippet ? (
                                            <div className="mt-1 text-[11px] leading-5 text-slate-600">
                                              {snippet}
                                            </div>
                                          ) : null}
                                        </div>
                                      )
                                    })
                                  ) : (
                                    <div className="rounded-lg border border-dashed border-sky-200 bg-white px-3 py-3 text-xs text-slate-400">
                                      暂无外网命中
                                    </div>
                                  )}
                                </div>
                              </div>
                            </div>

                            <div className="mt-3 rounded-xl bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-700">
                              {item.analysis_text
                                ?.split("\n")
                                .map((line) => line.trim())
                                .find(
                                  (line) =>
                                    line.length > 0 && !line.startsWith("#"),
                                ) || "暂无分析摘要"}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </section>
                ) : null}

                <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-slate-900">
                        模型与推送
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        这里直接显示这次分析是否走了模型，以及飞书是否成功推送。
                      </div>
                    </div>
                    <Badge variant="outline" className="bg-white">
                      {llmUsed ? "已启用模型" : "未启用模型"}
                    </Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Badge variant="outline" className="bg-white">
                      模型: {modelName}
                    </Badge>
                    <Badge variant="outline" className="bg-white">
                      飞书: {feishuStatus}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={
                        feishuStatusHint
                          ? "border-amber-200 bg-amber-50 text-amber-700"
                          : "bg-white"
                      }
                    >
                      飞书状态: {feishuStatusLabel}
                    </Badge>
                    <Badge variant="outline" className="bg-white">
                      最终长度:{" "}
                      {String(analysisMeta.refine_final_length ?? "未知")}
                    </Badge>
                  </div>
                  {feishuStatusHint ? (
                    <div className="mt-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                      {feishuStatusHint}
                    </div>
                  ) : null}
                </section>

                <section className="rounded-2xl border border-slate-200 bg-slate-50/50 px-4 py-4">
                  <pre className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words text-[15px] leading-8 text-slate-800">
                    {reportText || "暂无报告正文。"}
                  </pre>
                </section>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
                这里会显示岗位分析报告正文。
              </div>
            )}
          </div>
        </section>

        <section className="flex flex-col rounded-3xl border border-slate-200 bg-white/90 shadow-sm">
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <History className="h-4 w-4 text-sky-600" />
              轨迹与证据
            </div>
          </div>
          <div className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-4 pr-3">
            <div className="space-y-4">
              <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-medium text-slate-900">
                    可见轨迹摘要
                  </div>
                  <Badge variant="outline" className="bg-white">
                    {traceEntries.length} 步
                  </Badge>
                </div>
                <div className="mt-3 space-y-2">
                  {agentJourney.length > 0 ? (
                    agentJourney.slice(-6).map((item) => (
                      <div
                        key={`${item.step}-${item.status}-${item.elapsed_ms}`}
                        className="flex items-start gap-3 rounded-xl border border-white bg-white px-3 py-2 shadow-sm"
                      >
                        <div className="mt-1 h-2 w-2 rounded-full bg-sky-500" />
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-slate-900">
                            {item.step}
                          </div>
                          <div className="mt-1 text-xs leading-5 text-slate-500">
                            {item.detail}
                            {item.elapsed_ms ? ` · ${item.elapsed_ms}ms` : ""}
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                      暂无轨迹摘要
                    </div>
                  )}
                </div>
              </section>

              <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="text-sm font-medium text-slate-900">
                  执行轨迹
                </div>
                <div className="mt-3 space-y-3">
                  {visibleTraceEntries.length > 0 ? (
                    visibleTraceEntries.map((item, index) => (
                      <details
                        key={`${item.step}-${index}`}
                        className="group rounded-2xl border border-white bg-white shadow-sm"
                      >
                        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-slate-900">
                                {item.step}
                              </span>
                              <Badge variant="outline" className="bg-slate-50">
                                {item.status}
                              </Badge>
                              {item.query ? (
                                <Badge
                                  variant="outline"
                                  className="bg-slate-50"
                                >
                                  {item.query.length > 16
                                    ? `${item.query.slice(0, 16)}...`
                                    : item.query}
                                </Badge>
                              ) : null}
                            </div>
                            <div className="mt-1 text-xs leading-5 text-slate-500">
                              {describeTraceEntry(item)} · {item.elapsed_ms} ms
                            </div>
                          </div>
                          <ChevronDown className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
                        </summary>
                        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-600">
                          <TraceSummaryCards item={item} />
                          <TraceField
                            label="输入"
                            value={item.inputs_summary}
                          />
                          <TraceField
                            label="输出"
                            value={item.outputs_summary}
                          />
                          <TraceEvidenceRefs refs={item.evidence_refs} />
                        </div>
                      </details>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                      暂无轨迹
                    </div>
                  )}
                </div>
              </section>

              <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="text-sm font-medium text-slate-900">
                  证据引用
                </div>
                <div className="mt-3 space-y-3">
                  {evidence.length > 0 ? (
                    <div className="max-h-[34rem] space-y-3 overflow-y-auto pr-1">
                      {evidence.map((item) => (
                        <div
                          key={`${item.id}-${item.doc_title}-${item.source_file}`}
                          className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm"
                        >
                          <div className="text-sm font-medium text-slate-900">
                            {item.doc_title || item.source_file || "未命名证据"}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            {item.score.toFixed(2)}
                          </div>
                          <div className="mt-2 text-sm leading-6 text-slate-600">
                            {item.content || "暂无内容摘要"}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                      暂无证据引用
                    </div>
                  )}
                </div>
              </section>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

function GwyAnalysisReportPage() {
  return <GwyAnalysisPage />
}

function InfoRow({
  label,
  value,
}: {
  label: string
  value: string | null | undefined
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 break-all text-sm text-slate-900">
        {value || "暂无"}
      </div>
    </section>
  )
}

function TraceField({
  label,
  value,
}: {
  label: string
  value: Record<string, unknown>
}) {
  const entries = Object.entries(value)
  if (entries.length === 0) {
    return <div className="mt-2 text-slate-400">{label}：暂无</div>
  }
  return (
    <div className="mt-2">
      <div className="font-medium text-slate-700">{label}</div>
      <div className="mt-1 grid gap-2">
        {entries.slice(0, 6).map(([key, raw]) => (
          <div
            key={key}
            className="rounded-xl bg-slate-50 px-3 py-2 text-[11px] leading-5 text-slate-700"
          >
            <span className="font-medium text-slate-800">{key}：</span>
            <span>{formatTraceValue(raw)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TraceSummaryCards({ item }: { item: AnalysisTraceEntry }) {
  const items = [
    item.query ? `查询词: ${item.query}` : null,
    item.query_index !== undefined ? `检索组: ${item.query_index}` : null,
    item.attempt_index !== undefined ? `尝试: ${item.attempt_index}` : null,
    item.hit_count !== undefined ? `命中: ${item.hit_count}` : null,
    item.fetched_count !== undefined ? `抓取: ${item.fetched_count}` : null,
    item.browser_fallback_count !== undefined
      ? `浏览器回填: ${item.browser_fallback_count}`
      : null,
    item.result_count !== undefined ? `结果: ${item.result_count}` : null,
    item.retry_count !== undefined ? `重试: ${item.retry_count}` : null,
  ].filter(Boolean) as string[]
  if (items.length === 0) {
    return null
  }
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {items.map((label) => (
        <Badge key={label} variant="outline" className="bg-slate-50">
          {label}
        </Badge>
      ))}
    </div>
  )
}

function TraceEvidenceRefs({ refs }: { refs: AnalysisEvidence[] }) {
  if (refs.length === 0) {
    return null
  }
  return (
    <div className="mt-3">
      <div className="font-medium text-slate-700">证据</div>
      <div className="mt-2 space-y-2">
        {refs.slice(0, 2).map((ref, index) => (
          <div
            key={`${ref.id}-${index}`}
            className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2"
          >
            <div className="font-medium text-slate-800">
              {ref.doc_title || ref.source_file || "证据"}
            </div>
            <div className="mt-1 line-clamp-3 text-slate-600">
              {ref.content || "无正文摘要"}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function describeTraceEntry(entry: AnalysisTraceEntry): string {
  const detail = entry.detail.trim()
  if (detail) {
    return detail
  }
  const parts: string[] = []
  if (entry.step === "web_verification_search") {
    if (entry.query) {
      parts.push(`搜索“${entry.query}”`)
    }
    if (entry.hit_count !== undefined) {
      parts.push(`命中 ${entry.hit_count} 条`)
    }
    if (entry.browser_fallback_count !== undefined) {
      parts.push(`浏览器回填 ${entry.browser_fallback_count} 次`)
    }
  } else if (entry.step === "web_verification_plan") {
    if (
      entry.outputs_summary &&
      entry.outputs_summary.query_count !== undefined
    ) {
      parts.push(`规划 ${String(entry.outputs_summary.query_count)} 条查询`)
    }
  } else if (entry.step === "web_verification_observe") {
    if (entry.result_count !== undefined) {
      parts.push(`整理 ${entry.result_count} 条结果`)
    }
    if (entry.retry_count !== undefined) {
      parts.push(`重试 ${entry.retry_count} 次`)
    }
  }
  if (parts.length > 0) {
    return parts.join(" · ")
  }
  const inputCount = Object.keys(entry.inputs_summary || {}).length
  const outputCount = Object.keys(entry.outputs_summary || {}).length
  if (inputCount || outputCount) {
    return `输入 ${inputCount} 项 · 输出 ${outputCount} 项`
  }
  return "无详细描述"
}

function formatTraceValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "暂无"
  }
  if (Array.isArray(value)) {
    const normalized = value
      .map((item) => formatTraceValue(item))
      .filter((item) => item && item !== "暂无")
    return normalized.length > 0 ? normalized.join("、") : "暂无"
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
      .slice(0, 4)
      .map(([key, item]) => `${key}:${formatTraceValue(item)}`)
    return entries.join("，") || "对象"
  }
  return String(value)
}

function MiniDonutChart({
  entries,
}: {
  entries: Array<{ label: string; count: number; percent: number }>
}) {
  const palette = ["#0ea5e9", "#22c55e", "#f59e0b", "#f97316", "#a855f7"]
  const segments: string[] = []
  let cursor = 0
  for (const [index, entry] of entries.entries()) {
    const start = cursor * 100
    const end = (cursor + entry.percent) * 100
    segments.push(`${palette[index % palette.length]} ${start}% ${end}%`)
    cursor += entry.percent
  }
  const background =
    segments.length > 0 ? `conic-gradient(${segments.join(", ")})` : "#e2e8f0"
  return (
    <div className="flex items-center justify-center">
      <div className="relative h-36 w-36 rounded-full" style={{ background }}>
        <div className="absolute inset-8 rounded-full border border-slate-100 bg-white shadow-inner" />
        <div className="absolute inset-0 grid place-items-center">
          <div className="text-center">
            <div className="text-lg font-semibold text-slate-900">
              {entries.length > 0 ? entries[0].count : 0}
            </div>
            <div className="text-[11px] text-slate-500">Top 类别</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function TrendCard({
  title,
  note,
  data,
}: {
  title: string
  note: string
  data: Array<{ label: string; value: number }>
}) {
  const normalized = data.filter((item) => Number.isFinite(item.value))
  const max = Math.max(1, ...normalized.map((item) => Math.abs(item.value)))
  return (
    <div className="rounded-[24px] border border-white bg-white px-4 py-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-900">{title}</div>
          <div className="mt-1 text-xs text-slate-500">{note}</div>
        </div>
        <Badge variant="outline" className="bg-slate-50">
          {normalized.length > 0 ? "有数据" : "无法确认"}
        </Badge>
      </div>
      <div className="mt-4 flex h-44 items-end gap-3">
        {normalized.length > 0 ? (
          normalized.map((item) => (
            <div
              key={item.label}
              className="flex flex-1 flex-col items-center gap-2"
            >
              <div className="flex h-32 w-full items-end">
                <div
                  className="w-full rounded-t-2xl bg-gradient-to-t from-sky-500 to-cyan-400 shadow-sm"
                  style={{
                    height: `${Math.max(12, (item.value / max) * 100)}%`,
                  }}
                />
              </div>
              <div className="text-xs font-medium text-slate-900">
                {formatTrendValue(item.value)}
              </div>
              <div className="text-[11px] text-slate-500">{item.label}</div>
            </div>
          ))
        ) : (
          <div className="flex h-full w-full items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
            暂无可核验数据
          </div>
        )}
      </div>
    </div>
  )
}

function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
      <div
        className="h-full rounded-full bg-gradient-to-r from-sky-500 to-cyan-400 transition-all"
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  )
}

function recommendationLabel(
  recommendLevel?: string | null,
  riskLevel?: string | null,
): string {
  const level = String(recommendLevel || "").toLowerCase()
  const risk = String(riskLevel || "").toLowerCase()
  if (risk === "high") {
    return "谨慎报考"
  }
  if (level === "strong_match") {
    return "优先报考"
  }
  if (level === "good_match") {
    return "冲刺岗位"
  }
  if (level === "weak_match") {
    return "备选岗位"
  }
  return "待确认"
}

function truncateUrl(url: string): string {
  const value = String(url || "").trim()
  if (!value) {
    return ""
  }
  return value.length > 72 ? `${value.slice(0, 69)}...` : value
}

function describeResearchGap(code: string): string {
  const value = String(code || "").trim()
  if (!value) {
    return ""
  }
  if (value === "missing_recruit_count") {
    return "招录人数缺口"
  }
  if (value === "missing_competition_ratio") {
    return "报录比缺口"
  }
  if (value === "missing_interview_score") {
    return "进面分缺口"
  }
  if (value === "no_web_evidence") {
    return "外网证据不足"
  }
  if (value === "web_retry_failed") {
    return "外网重试失败"
  }
  if (value === "history_sparse") {
    return "历史数据稀疏"
  }
  if (value.includes("interview")) {
    return "进面信息缺口"
  }
  if (value.includes("recruit")) {
    return "招录人数缺口"
  }
  return value
}

function formatTrendValue(value: number) {
  if (!Number.isFinite(value)) {
    return "0"
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function normalizeEvidence(item: unknown): AnalysisEvidence | null {
  if (!item || typeof item !== "object") {
    return null
  }
  const candidate = item as Record<string, unknown>
  return {
    id: String(candidate.id ?? ""),
    doc_title: String(candidate.doc_title ?? ""),
    source_file: String(candidate.source_file ?? ""),
    content: String(candidate.content ?? ""),
    score: Number(candidate.score ?? 0),
  }
}

function normalizeTraceEntries(value: unknown): AnalysisTraceEntry[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => normalizeTraceEntry(item))
    .filter((item): item is AnalysisTraceEntry => item !== null)
}

function normalizeTraceEntry(item: unknown): AnalysisTraceEntry | null {
  if (!item || typeof item !== "object") {
    return null
  }
  const candidate = item as Record<string, unknown>
  const evidenceRefs = Array.isArray(candidate.evidence_refs)
    ? candidate.evidence_refs
        .map((ref) => normalizeEvidence(ref))
        .filter((ref): ref is AnalysisEvidence => ref !== null)
    : []
  return {
    step: String(candidate.step ?? ""),
    status: String(candidate.status ?? ""),
    detail: String(candidate.detail ?? ""),
    elapsed_ms: Number(candidate.elapsed_ms ?? 0),
    query:
      candidate.query === undefined ? undefined : String(candidate.query ?? ""),
    query_index:
      candidate.query_index === undefined
        ? undefined
        : Number(candidate.query_index),
    attempt_index:
      candidate.attempt_index === undefined
        ? undefined
        : Number(candidate.attempt_index),
    hit_count:
      candidate.hit_count === undefined
        ? undefined
        : Number(candidate.hit_count),
    fetched_count:
      candidate.fetched_count === undefined
        ? undefined
        : Number(candidate.fetched_count),
    browser_fallback_count:
      candidate.browser_fallback_count === undefined
        ? undefined
        : Number(candidate.browser_fallback_count),
    result_count:
      candidate.result_count === undefined
        ? undefined
        : Number(candidate.result_count),
    retry_count:
      candidate.retry_count === undefined
        ? undefined
        : Number(candidate.retry_count),
    inputs_summary: isRecord(candidate.inputs_summary)
      ? (candidate.inputs_summary as Record<string, unknown>)
      : {},
    outputs_summary: isRecord(candidate.outputs_summary)
      ? (candidate.outputs_summary as Record<string, unknown>)
      : {},
    evidence_refs: evidenceRefs,
  }
}

function normalizeJourneyEntries(value: unknown): AnalysisJourneyEntry[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => normalizeJourneyEntry(item))
    .filter((item): item is AnalysisJourneyEntry => item !== null)
}

function normalizeJourneyEntry(item: unknown): AnalysisJourneyEntry | null {
  if (!item || typeof item !== "object") {
    return null
  }
  const candidate = item as Record<string, unknown>
  return {
    phase: String(candidate.phase ?? ""),
    step: String(candidate.step ?? ""),
    status: String(candidate.status ?? ""),
    detail: String(candidate.detail ?? ""),
    elapsed_ms: Number(candidate.elapsed_ms ?? 0),
    summary_lines: toStringList(candidate.summary_lines),
    position_label: String(candidate.position_label ?? ""),
    history_years: toStringList(candidate.history_years),
    latest_recruit_count: candidate.latest_recruit_count as
      | number
      | string
      | null
      | undefined,
    latest_interview_ratio: candidate.latest_interview_ratio as
      | number
      | string
      | null
      | undefined,
    web_hit_count:
      candidate.web_hit_count === null || candidate.web_hit_count === undefined
        ? undefined
        : Number(candidate.web_hit_count),
  }
}

function normalizeAnalysisStrategy(value: unknown): AnalysisStrategy | null {
  if (!isRecord(value)) {
    return null
  }
  return {
    strategy_name: String(value.strategy_name ?? ""),
    planning_strategy: String(value.planning_strategy ?? ""),
    evidence_strategy: String(value.evidence_strategy ?? ""),
    decision_style: String(value.decision_style ?? ""),
    strategy_source: String(value.strategy_source ?? ""),
    analysis_goal: String(value.analysis_goal ?? ""),
    query: String(value.query ?? ""),
    research_budget: isRecord(value.research_budget)
      ? (value.research_budget as Record<string, unknown>)
      : {},
    priority_sources: toStringList(value.priority_sources),
    research_targets: Array.isArray(value.research_targets)
      ? value.research_targets
          .map((item) => normalizeAnalysisStrategyTarget(item))
          .filter((item): item is AnalysisStrategyTarget => item !== null)
      : [],
    summary_lines: toStringList(value.summary_lines),
  }
}

function normalizeAnalysisStrategyTarget(
  item: unknown,
): AnalysisStrategyTarget | null {
  if (!item || typeof item !== "object") {
    return null
  }
  const candidate = item as Record<string, unknown>
  return {
    index: Number(candidate.index ?? 0),
    position_id: String(candidate.position_id ?? ""),
    department_name: String(candidate.department_name ?? ""),
    office_name: String(candidate.office_name ?? ""),
    job_title: String(candidate.job_title ?? ""),
    position_code: String(candidate.position_code ?? ""),
    history_priority: String(candidate.history_priority ?? ""),
    needs_web_search: Boolean(candidate.needs_web_search ?? false),
    focus: toStringList(candidate.focus),
    search_queries: toStringList(candidate.search_queries),
    retry_queries: toStringList(candidate.retry_queries),
    observation_questions: toStringList(candidate.observation_questions),
    evidence_focus: toStringList(candidate.evidence_focus),
    reason: String(candidate.reason ?? ""),
    history_summary: isRecord(candidate.history_summary)
      ? (candidate.history_summary as Record<string, unknown>)
      : {},
  }
}

function normalizeStudyPlan(value: unknown): StudyPlanData | null {
  if (!isRecord(value)) {
    return null
  }
  const plan = isRecord(value.plan) ? value.plan : {}
  return {
    status: String(value.status ?? "completed"),
    plan: {
      id: String(plan.id ?? ""),
      title: String(plan.title ?? ""),
      exam_type: String(plan.exam_type ?? ""),
      exam_year: normalizeStudyPlanScalar(plan.exam_year),
      status: String(plan.status ?? ""),
      study_hours_per_day: normalizeStudyPlanScalar(plan.study_hours_per_day),
      total_weeks: normalizeStudyPlanScalar(plan.total_weeks),
    },
    phases: Array.isArray(value.phases)
      ? value.phases
          .map((item) => normalizeStudyPlanPhase(item))
          .filter((item): item is StudyPlanPhase => item !== null)
      : [],
    subjects: Array.isArray(value.subjects)
      ? value.subjects
          .map((item) => normalizeStudyPlanSubject(item))
          .filter((item): item is StudyPlanSubject => item !== null)
      : [],
    tasks: Array.isArray(value.tasks)
      ? value.tasks
          .map((item) => normalizeStudyPlanTask(item))
          .filter((item): item is StudyPlanTask => item !== null)
      : [],
    markdown: String(value.markdown ?? ""),
  }
}

function normalizeStudyPlanPhase(item: unknown): StudyPlanPhase | null {
  if (!isRecord(item)) {
    return null
  }
  return {
    id: String(item.id ?? ""),
    phase_order: Number(item.phase_order ?? 0),
    phase_name: String(item.phase_name ?? ""),
    phase_goal: String(item.phase_goal ?? ""),
    week_start: Number(item.week_start ?? 0),
    week_end: Number(item.week_end ?? 0),
    focus_subjects: toStringList(item.focus_subjects),
    study_hours_per_day: normalizeStudyPlanScalar(item.study_hours_per_day),
  }
}

function normalizeStudyPlanSubject(item: unknown): StudyPlanSubject | null {
  if (!isRecord(item)) {
    return null
  }
  return {
    id: String(item.id ?? ""),
    subject_name: String(item.subject_name ?? ""),
    subject_category: String(item.subject_category ?? ""),
    weight_percent: normalizeStudyPlanScalar(item.weight_percent),
    total_hours: normalizeStudyPlanScalar(item.total_hours),
    checklist_items: toStringList(item.checklist_items),
    resources: toStringList(item.resources),
  }
}

function normalizeStudyPlanTask(item: unknown): StudyPlanTask | null {
  if (!isRecord(item)) {
    return null
  }
  return {
    id: String(item.id ?? ""),
    week_number: Number(item.week_number ?? 0),
    day_of_week: Number(item.day_of_week ?? 0),
    subject: String(item.subject ?? ""),
    task_title: String(item.task_title ?? ""),
    task_description: String(item.task_description ?? ""),
    estimated_minutes: normalizeStudyPlanScalar(item.estimated_minutes),
    priority: normalizeStudyPlanScalar(item.priority),
    completed: Boolean(item.completed ?? false),
  }
}

function normalizePositionResearches(
  value: unknown,
): AnalysisPositionResearch[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => normalizePositionResearch(item))
    .filter((item): item is AnalysisPositionResearch => item !== null)
}

function normalizePositionResearch(
  item: unknown,
): AnalysisPositionResearch | null {
  if (!isRecord(item)) {
    return null
  }
  return {
    index: Number(item.index ?? 0),
    position_id: String(item.position_id ?? ""),
    department_name: String(item.department_name ?? ""),
    office_name: String(item.office_name ?? ""),
    job_title: String(item.job_title ?? ""),
    position_code: String(item.position_code ?? ""),
    history: isRecord(item.history)
      ? (item.history as Record<string, unknown>)
      : {},
    history_records: Array.isArray(item.history_records)
      ? (item.history_records.filter(isRecord) as Array<
          Record<string, unknown>
        >)
      : [],
    web_results: Array.isArray(item.web_results)
      ? (item.web_results.filter(isRecord) as Array<Record<string, unknown>>)
      : [],
    web_search_attempts: Array.isArray(item.web_search_attempts)
      ? (item.web_search_attempts.filter(isRecord) as Array<
          Record<string, unknown>
        >)
      : [],
    analysis_text: String(item.analysis_text ?? ""),
    research_plan: isRecord(item.research_plan)
      ? (item.research_plan as Record<string, unknown>)
      : {},
    strategy_target: isRecord(item.strategy_target)
      ? normalizeAnalysisStrategyTarget(item.strategy_target)
      : null,
  }
}

function normalizePositionFacts(value: unknown): AnalysisPositionFact[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => normalizePositionFact(item))
    .filter((item): item is AnalysisPositionFact => item !== null)
}

function normalizePositionFact(item: unknown): AnalysisPositionFact | null {
  if (!isRecord(item)) {
    return null
  }
  return {
    index: Number(item.index ?? 0),
    position_id: String(item.position_id ?? ""),
    department_name: String(item.department_name ?? ""),
    office_name: String(item.office_name ?? ""),
    job_title: String(item.job_title ?? ""),
    position_code: String(item.position_code ?? ""),
    recruit_count:
      item.recruit_count === null || item.recruit_count === undefined
        ? null
        : Number(item.recruit_count),
    score:
      item.score === null || item.score === undefined
        ? null
        : Number(item.score),
    recommend_level: String(item.recommend_level ?? ""),
    risk_level: String(item.risk_level ?? ""),
    need_manual_confirm: Boolean(item.need_manual_confirm ?? false),
    major_requirement: String(item.major_requirement ?? ""),
    education_requirement: String(item.education_requirement ?? ""),
    degree_requirement: String(item.degree_requirement ?? ""),
    political_status_requirement: String(
      item.political_status_requirement ?? "",
    ),
    work_location: String(
      item.work_location ??
        item.position_distribution ??
        item.household_registration_location ??
        "",
    ),
    remarks: String(item.remarks ?? ""),
    history: isRecord(item.history)
      ? (item.history as Record<string, unknown>)
      : {},
    history_records: Array.isArray(item.history_records)
      ? (item.history_records.filter(isRecord) as Array<
          Record<string, unknown>
        >)
      : [],
    web_results: Array.isArray(item.web_results)
      ? (item.web_results.filter(isRecord) as Array<Record<string, unknown>>)
      : [],
    reasons: Array.isArray(item.reasons)
      ? (item.reasons.filter(isRecord) as Array<Record<string, unknown>>)
      : [],
    risks: Array.isArray(item.risks)
      ? (item.risks.filter(isRecord) as Array<Record<string, unknown>>)
      : [],
    hard_filter_passed: Boolean(item.hard_filter_passed ?? false),
    hard_filter_reasons: toStringList(item.hard_filter_reasons),
    hard_filter_risks: toStringList(item.hard_filter_risks),
  }
}

function formatUnknown(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "无法确认"
  }
  if (typeof value === "number") {
    if (Number.isNaN(value)) {
      return "无法确认"
    }
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否"
  }
  if (Array.isArray(value)) {
    return value.length > 0
      ? value.map((item) => String(item)).join("、")
      : "无法确认"
  }
  const text = String(value).trim()
  return text || "无法确认"
}

function summarizeCounter(
  items: AnalysisPositionFact[],
  fieldName:
    | "department_name"
    | "education_requirement"
    | "degree_requirement"
    | "political_status_requirement"
    | "major_requirement"
    | "risk_level",
): string {
  if (items.length === 0) {
    return "暂无数据"
  }
  const counts = new Map<string, number>()
  for (const item of items) {
    const value = formatUnknown(item[fieldName])
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return Array.from(counts.entries())
    .sort((left, right) => right[1] - left[1])
    .slice(0, 4)
    .map(([label, count]) => `${label} ${count} 条`)
    .join("，")
}

function StudyPlanPanel({ studyPlan }: { studyPlan: StudyPlanData | null }) {
  const [expanded, setExpanded] = useState(false)
  const phases = [...(studyPlan?.phases ?? [])].sort(
    (left, right) =>
      (left.phase_order ?? 0) - (right.phase_order ?? 0) ||
      (left.week_start ?? 0) - (right.week_start ?? 0),
  )
  const subjects = [...(studyPlan?.subjects ?? [])].sort((left, right) => {
    const leftWeight = Number(left.weight_percent ?? 0)
    const rightWeight = Number(right.weight_percent ?? 0)
    return rightWeight - leftWeight || left.subject_name.localeCompare(right.subject_name)
  })
  const tasks = [...(studyPlan?.tasks ?? [])].sort((left, right) => {
    return (
      (left.week_number ?? 0) - (right.week_number ?? 0) ||
      (left.day_of_week ?? 0) - (right.day_of_week ?? 0) ||
      Number(left.priority ?? 0) - Number(right.priority ?? 0)
    )
  })
  const title = studyPlan?.plan.title?.trim() || "复习规划"
  const examYear = formatUnknown(studyPlan?.plan.exam_year)
  const examType = formatStudyPlanExamType(studyPlan?.plan.exam_type)
  const totalWeeks = formatUnknown(studyPlan?.plan.total_weeks)
  const hoursPerDay = formatUnknown(studyPlan?.plan.study_hours_per_day)
  const markdown = studyPlan?.markdown?.trim() ?? ""
  const planStatus = String(studyPlan?.status ?? "").toLowerCase()
  const isUnavailable = !studyPlan || planStatus === "failed"
  const unavailableReason = !studyPlan
    ? "当前任务未返回复习规划，可能是旧任务、任务未完成，或后端生成尚未成功。"
    : planStatus === "failed"
      ? "复习规划生成失败，但岗位分析报告仍然可用。"
      : ""

  return (
    <section className="mt-4 overflow-hidden rounded-[24px] border border-emerald-200 bg-gradient-to-br from-emerald-50 via-white to-cyan-50 px-4 py-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-emerald-950">复习规划</div>
          <div className="mt-1 text-xs leading-5 text-emerald-800">
            将岗位分析结论直接转换成可执行的备考节奏，方便用户从“看报告”进入“做计划”。
          </div>
        </div>
        <Badge
          variant="outline"
          className={
            isUnavailable
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : "border-emerald-200 bg-white text-emerald-700"
          }
        >
          {isUnavailable ? "规划暂不可用" : "规划已生成"}
        </Badge>
      </div>

      {isUnavailable ? (
        <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm leading-6 text-amber-900">
          {unavailableReason}
        </div>
      ) : (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <PlanStat label="规划标题" value={title} />
            <PlanStat label="考试年份 / 类型" value={`${examYear} · ${examType}`} />
            <PlanStat label="总周数" value={`${totalWeeks} 周`} />
            <PlanStat label="每日学习时长" value={`${hoursPerDay} 小时`} />
          </div>

          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            <div className="rounded-2xl border border-emerald-100 bg-white px-4 py-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-emerald-700">
                阶段安排
              </div>
              <div className="mt-3 space-y-3">
                {phases.length > 0 ? (
                  phases.slice(0, 4).map((phase) => (
                    <div
                      key={phase.id || `${phase.phase_order}-${phase.phase_name}`}
                      className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-slate-900">
                            {phase.phase_name || `第 ${phase.phase_order} 阶段`}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            第 {formatUnknown(phase.week_start)}-{formatUnknown(phase.week_end)} 周
                          </div>
                        </div>
                        <Badge variant="outline" className="bg-white">
                          {formatUnknown(phase.study_hours_per_day)} 小时/天
                        </Badge>
                      </div>
                      <div className="mt-2 text-sm leading-6 text-slate-700">
                        {phase.phase_goal || "阶段目标暂未说明"}
                      </div>
                      {phase.focus_subjects.length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {phase.focus_subjects.map((item) => (
                            <Badge key={item} variant="outline" className="bg-white">
                              {item}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    暂无阶段安排。
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-emerald-100 bg-white px-4 py-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-emerald-700">
                科目重点
              </div>
              <div className="mt-3 space-y-3">
                {subjects.length > 0 ? (
                  subjects.slice(0, 4).map((subject) => (
                    <div
                      key={subject.id || subject.subject_name}
                      className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-slate-900">
                            {subject.subject_name || "未命名科目"}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            {subject.subject_category || "未分类"}
                          </div>
                        </div>
                        <Badge variant="outline" className="bg-white">
                          {formatUnknown(subject.weight_percent)}%
                        </Badge>
                      </div>
                      <div className="mt-2 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                        <div>总时长: {formatUnknown(subject.total_hours)} 小时</div>
                        <div>清单: {subject.checklist_items.length} 项</div>
                      </div>
                      {subject.checklist_items.length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {subject.checklist_items.slice(0, 4).map((item) => (
                            <Badge
                              key={item}
                              variant="outline"
                              className="border-cyan-200 bg-cyan-50 text-cyan-800"
                            >
                              {item}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                      {subject.resources.length > 0 ? (
                        <div className="mt-2 text-xs text-slate-500">
                          资源: {subject.resources.slice(0, 3).join("，")}
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    暂无科目重点。
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            <div className="rounded-2xl border border-emerald-100 bg-white px-4 py-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-emerald-700">
                任务预览
              </div>
              <div className="mt-3 space-y-2">
                {tasks.length > 0 ? (
                  tasks.slice(0, 5).map((task) => (
                    <div
                      key={task.id || `${task.week_number}-${task.day_of_week}-${task.task_title}`}
                      className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-sm font-medium text-slate-900">
                          第 {formatUnknown(task.week_number)} 周 · 第 {formatUnknown(task.day_of_week)} 天
                        </div>
                        <Badge variant="outline" className="bg-white">
                          {task.completed ? "已完成" : "待执行"}
                        </Badge>
                      </div>
                      <div className="mt-1 text-sm text-slate-700">
                        {task.subject || "未指定科目"} · {cleanStudyPlanText(task.task_title) || "未命名任务"}
                      </div>
                      {cleanStudyPlanText(task.task_description) ? (
                        <div className="mt-1 text-xs leading-5 text-slate-500">
                          {cleanStudyPlanText(task.task_description)}
                        </div>
                      ) : null}
                      <div className="mt-2 text-xs text-slate-500">
                        预计 {formatUnknown(task.estimated_minutes)} 分钟 · 优先级 {formatUnknown(task.priority)}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    暂无任务预览。
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-emerald-100 bg-white px-4 py-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-xs font-medium uppercase tracking-wide text-emerald-700">
                    完整规划预览
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    默认展示完整 Markdown，可折叠查看。
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="bg-white"
                  onClick={() => setExpanded((value) => !value)}
                  disabled={!markdown}
                >
                  {expanded ? "收起" : "展开"}
                  <ChevronDown
                    className={`ml-2 h-4 w-4 transition-transform ${
                      expanded ? "rotate-180" : ""
                    }`}
                  />
                </Button>
              </div>
              {markdown ? (
                <pre
                  className={`mt-3 whitespace-pre-wrap break-words rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-800 shadow-sm ${
                    expanded ? "" : "max-h-72 overflow-hidden"
                  }`}
                >
                  {markdown}
                </pre>
              ) : (
                <div className="mt-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                  规划已生成，但暂无 Markdown 预览内容。
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function cleanStudyPlanText(value: string | null | undefined): string {
  const text = String(value ?? "").trim()
  if (!text) {
    return ""
  }
  if (/[?？]{3,}/.test(text)) {
    return ""
  }
  return text
}

function PlanStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-emerald-100 bg-white px-4 py-3 shadow-sm">
      <div className="text-[11px] uppercase tracking-wide text-emerald-700">
        {label}
      </div>
      <div className="mt-1 break-words text-sm font-medium text-slate-900">
        {value}
      </div>
    </div>
  )
}

function formatStudyPlanExamType(value: unknown): string {
  const text = String(value ?? "").trim().toLowerCase()
  if (!text) {
    return "未说明"
  }
  if (text === "national" || text === "gwy") {
    return "国考"
  }
  if (text === "provincial") {
    return "省考"
  }
  if (text === "municipal") {
    return "市考"
  }
  return String(value)
}

function normalizeStudyPlanScalar(value: unknown): number | string | null {
  if (value === null || value === undefined || value === "") {
    return null
  }
  if (typeof value === "number") {
    return Number.isNaN(value) ? null : value
  }
  if (typeof value === "string") {
    return value
  }
  const asNumber = Number(value)
  return Number.isNaN(asNumber) ? String(value) : asNumber
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
      {hint ? (
        <div className="mt-1 text-xs leading-5 text-slate-500">{hint}</div>
      ) : null}
    </div>
  )
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "暂无"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString("zh-CN")
}

function formatCompactValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "暂无"
  }
  if (typeof value === "string") {
    return value
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  try {
    const text = JSON.stringify(value)
    return text.length > 64 ? `${text.slice(0, 61)}...` : text
  } catch {
    return String(value)
  }
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => String(item)).filter(Boolean)
}

function countWebSearchRetries(
  attempts: Array<Record<string, unknown>>,
): number {
  return attempts.reduce((count, attempt) => {
    const isRetry = Boolean(attempt.is_retry ?? attempt.retry ?? false)
    return count + (isRetry ? 1 : 0)
  }, 0)
}

function countBrowserFallbacks(
  attempts: Array<Record<string, unknown>>,
): number {
  return attempts.reduce((count, attempt) => {
    const fallbackCount = Number(attempt.browser_fallback_count ?? 0)
    return count + (Number.isFinite(fallbackCount) ? fallbackCount : 0)
  }, 0)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function buildRecommendationBuckets(items: AnalysisPositionFact[]) {
  const exact = items.filter((item) => {
    const level = item.recommend_level.toLowerCase()
    return level === "strong_match" && item.risk_level.toLowerCase() !== "high"
  }).length
  const basic = items.filter((item) => {
    const level = item.recommend_level.toLowerCase()
    return level === "good_match" || level === "weak_match"
  }).length
  const risk = items.filter((item) =>
    ["medium", "high"].includes(item.risk_level.toLowerCase()),
  ).length
  const notRecommended = Math.max(0, items.length - exact - basic)
  return {
    total: items.length,
    exact,
    basic,
    risk,
    notRecommended,
  }
}

function buildDistributionEntries(
  items: AnalysisPositionFact[],
  field:
    | "department_name"
    | "education_requirement"
    | "political_status_requirement"
    | "major_requirement",
) {
  const counts = new Map<string, number>()
  for (const item of items) {
    const label = normalizeDistributionLabel(item[field], field)
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  const total = items.length || 1
  return Array.from(counts.entries())
    .map(([label, count]) => ({
      label,
      count,
      percent: count / total,
    }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 5)
}

function normalizeDistributionLabel(
  value: string,
  field:
    | "department_name"
    | "education_requirement"
    | "political_status_requirement"
    | "major_requirement",
) {
  const text = String(value || "").trim()
  if (!text) {
    return "未填写"
  }
  if (field === "major_requirement") {
    const normalized = text.toLowerCase()
    if (text.includes("不限") || normalized.includes("不限")) {
      return "不限"
    }
    if (text.includes("类") || text.includes("相关") || text.includes("大类")) {
      return "专业相关"
    }
    return "强限制"
  }
  return text
}

function buildHistoryYearStats(positionResearches: AnalysisPositionResearch[]) {
  const yearMap = new Map<
    number,
    {
      year: number
      recruitCount: number
      ratioValues: number[]
      scoreValues: number[]
    }
  >()

  for (const research of positionResearches) {
    for (const record of research.history_records || []) {
      const year = extractYearFromRecord(record)
      if (!year) {
        continue
      }
      const current = yearMap.get(year) ?? {
        year,
        recruitCount: 0,
        ratioValues: [],
        scoreValues: [],
      }
      current.recruitCount += safeNumber(record.recruit_count)
      const ratio = parseRatioLike(record.interview_ratio)
      if (ratio !== null) {
        current.ratioValues.push(ratio)
      }
      const score = extractScoreLike(record)
      if (score !== null) {
        current.scoreValues.push(score)
      }
      yearMap.set(year, current)
    }
  }

  return Array.from(yearMap.values())
    .sort((left, right) => left.year - right.year)
    .map((item) => ({
      year: item.year,
      recruitCount: item.recruitCount,
      ratio: item.ratioValues.length > 0 ? average(item.ratioValues) : null,
      score: item.scoreValues.length > 0 ? average(item.scoreValues) : null,
    }))
}

function extractYearFromRecord(record: Record<string, unknown>): number | null {
  const candidates = [
    record.year,
    record.source_year,
    record.batch_year,
    record.source_file,
  ]
  for (const candidate of candidates) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate
    }
    const match = String(candidate ?? "").match(/(20\d{2})/)
    if (match) {
      return Number(match[1])
    }
  }
  return null
}

function extractScoreLike(record: Record<string, unknown>): number | null {
  const keys = [
    "lowest_score",
    "interview_score",
    "minimum_interview_score",
    "min_score",
    "score",
  ]
  for (const key of keys) {
    const value = record[key]
    const parsed = safeMaybeNumber(value)
    if (parsed !== null) {
      return parsed
    }
  }
  return null
}

function parseRatioLike(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return value
  }
  const text = String(value)
  const match = text.match(/(\d+(?:\.\d+)?)/)
  if (!match) {
    return null
  }
  return Number(match[1])
}

function safeNumber(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function safeMaybeNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function average(values: number[]): number {
  if (values.length === 0) {
    return 0
  }
  return values.reduce((sum, item) => sum + item, 0) / values.length
}

function buildSupplementedTaskRequest(
  snapshot: PositionAnalysisSnapshotResponse,
  supplementText: string,
) {
  const parsed = parseSupplementText(supplementText)
  const currentFilters = isRecord(snapshot.filters_json)
    ? (snapshot.filters_json as Record<string, unknown>)
    : {}
  const mergedFilters: Record<string, unknown> = {
    ...currentFilters,
    ...parsed.filters,
  }
  const baseSnapshot = isRecord(snapshot.snapshot_json)
    ? (snapshot.snapshot_json as Record<string, unknown>)
    : {}
  return {
    snapshot: {
      ...baseSnapshot,
      title: snapshot.title,
      source_sheet: snapshot.source_sheet,
      filters_json: mergedFilters,
      selected_position_ids: snapshot.selected_position_ids,
      visible_columns: snapshot.visible_columns,
      notes: [snapshot.notes, parsed.freeText, supplementText]
        .filter(Boolean)
        .join("\n")
        .trim(),
    },
    title: snapshot.title,
    source_sheet: snapshot.source_sheet,
    notes: [snapshot.notes, parsed.freeText, supplementText]
      .filter(Boolean)
      .join("\n")
      .trim(),
  }
}

function parseSupplementText(text: string): {
  filters: Record<string, string>
  freeText: string
} {
  const filters: Record<string, string> = {}
  const parts = text
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  const freeTextParts: string[] = []

  for (const part of parts) {
    const parsed = parseSupplementPart(part)
    if (!parsed) {
      freeTextParts.push(part)
      continue
    }
    const { key, value } = parsed
    if (!value) {
      continue
    }
    filters[key] = value
  }

  return {
    filters,
    freeText: freeTextParts.join(" ").trim(),
  }
}

function parseSupplementPart(
  part: string,
): { key: string; value: string } | null {
  const separatorIndex = part.search(/[:：=＝]/)
  if (separatorIndex > 0) {
    const rawKey = part.slice(0, separatorIndex).trim()
    const value = part.slice(separatorIndex + 1).trim()
    const key = normalizeSupplementKey(rawKey)
    return key ? { key, value } : null
  }

  const matched = part.match(
    /^(专业|学历|学位|政治面貌|政治|地区|区域|部门|岗位|岗位名称)\s*(是|为|=|：|:)\s*(.+)$/,
  )
  if (!matched) {
    return null
  }
  const key = normalizeSupplementKey(matched[1])
  const value = matched[3]?.trim() ?? ""
  return key ? { key, value } : null
}

function normalizeSupplementKey(key: string): string | null {
  const normalized = key.replace(/\s+/g, "").toLowerCase()
  if (["专业", "major", "专业类别"].includes(normalized)) return "major"
  if (["学历", "education"].includes(normalized)) return "education"
  if (["学位", "degree"].includes(normalized)) return "degree"
  if (["政治面貌", "政治", "political_status"].includes(normalized))
    return "political_status"
  if (["地区", "区域", "region"].includes(normalized)) return "region"
  if (["部门", "department"].includes(normalized)) return "department"
  if (["岗位", "岗位名称", "job", "job_title"].includes(normalized))
    return "job_title"
  return null
}
function normalizeAnalysisHistoryItem(
  item: unknown,
): AnalysisHistoryItem | null {
  if (!item || typeof item !== "object") {
    return null
  }
  const candidate = item as Record<string, unknown>
  const taskId = String(candidate.task_id ?? candidate.id ?? "").trim()
  if (!taskId) {
    return null
  }
  return {
    task_id: taskId,
    snapshot_id: String(candidate.snapshot_id ?? "").trim(),
    title: String(candidate.title ?? "岗位分析报告").trim() || "岗位分析报告",
    finished_at: String(candidate.finished_at ?? "").trim(),
    created_at: String(candidate.created_at ?? "").trim(),
    status: String(candidate.status ?? "").trim() || "unknown",
    stage: String(candidate.stage ?? "").trim() || "",
  }
}
