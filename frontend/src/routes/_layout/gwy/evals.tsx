import { createFileRoute } from "@tanstack/react-router"
import {
  Activity,
  BarChart3,
  Database,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { OpenAPI } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export const Route = createFileRoute("/_layout/gwy/evals")({
  component: EvaluationPage,
})

type EvalRun = {
  id: string
  source_type: string
  task_type: string
  status: string
  query: string
  summary: Record<string, unknown>
  created_at?: string | null
}

type EvalDataset = {
  id: string
  name: string
  version: string
  split: string
  task_type: string
  status: string
  case_count: number
}

type EvalScore = {
  passed: boolean
  metrics: Record<string, unknown>
  failure_reasons?: string[]
  details?: Record<string, unknown>
}

type EvalCase = {
  id?: string
  case_id: string
  status: string
  passed?: boolean
  scores?: Record<string, EvalScore>
  observation?: Record<string, unknown>
  failure_reasons?: string[]
  trace?: Record<string, unknown>[]
  critical_gate?: {
    passed?: boolean
    blocked?: boolean
    trace_complete?: boolean
    failed_scores?: string[]
    failure_reasons?: string[]
  }
  quality_overview?: Record<string, Record<string, unknown>>
  execution_quality?: Record<string, unknown>
  score_cards?: Record<string, EvalScore>
}

type RunSummary = {
  overall_status?: string
  case_count?: number
  passed_count?: number
  failed_count?: number
  blocked_count?: number
  task_success_rate?: number
  critical_gate?: {
    passed_rate?: number
    passed_count?: number
    failed_count?: number
    blocked_count?: number
  }
  quality_overview?: Record<string, Record<string, unknown>>
  score_cards?: Record<
    string,
    {
      case_count?: number
      passed_count?: number
      pass_rate?: number
      metrics?: Record<string, unknown>
      failure_reasons?: Record<string, number>
    }
  >
  failure_taxonomy?: Record<string, number>
  trace_complete_count?: number
}

function EvaluationPage() {
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [selected, setSelected] = useState<EvalRun | null>(null)
  const [cases, setCases] = useState<EvalCase[]>([])
  const [selectedCaseIndex, setSelectedCaseIndex] = useState(0)
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [datasetId, setDatasetId] = useState("")
  const [datasetName, setDatasetName] = useState("我的评测集")
  const [datasetText, setDatasetText] = useState("[]")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const configuredBase = (OpenAPI.BASE || "").replace(/\/$/, "")
    const apiBase = configuredBase.endsWith("/api/v1")
      ? configuredBase
      : `${configuredBase}/api/v1`
    let response: Response
    try {
      response = await fetch(`${apiBase}/gwy/evals${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
          "Content-Type": "application/json",
          ...(init?.headers || {}),
        },
      })
    } catch {
      throw new Error(
        "无法连接后端 API。请先启动后端（http://localhost:8000），并重启前端开发服务器。",
      )
    }
    if (!response.ok) {
      const detail = await response.text()
      if (response.status === 401 || response.status === 403) {
        throw new Error("登录状态已失效，请重新登录后再打开评测分析。")
      }
      if (response.status >= 500 && detail.includes("gwy_eval_dataset")) {
        throw new Error(
          "评测数据库表尚未创建，请在 backend 目录执行：uv run alembic upgrade head，然后重启后端。",
        )
      }
      throw new Error(detail || `后端请求失败（${response.status}）`)
    }
    return response.json()
  }, [])

  const loadRuns = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextRuns = (await request("/runs")) as EvalRun[]
      setRuns(nextRuns)
      setSelected((current) => {
        if (current && nextRuns.some((run) => run.id === current.id)) {
          return current
        }
        return nextRuns[0] ?? null
      })
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "评测记录加载失败",
      )
    } finally {
      setLoading(false)
    }
  }, [request])

  const loadDatasets = useCallback(async () => {
    setError(null)
    try {
      let data = (await request("/datasets")) as EvalDataset[]
      if (data.length === 0) {
        data = (await request("/datasets/import-defaults", {
          method: "POST",
        })) as EvalDataset[]
      }
      setDatasets(data)
      if (!datasetId && data[0]) setDatasetId(data[0].id)
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "数据集加载失败",
      )
    }
  }, [datasetId, request])

  const loadCases = useCallback(async () => {
    if (!selected) {
      setCases([])
      setSelectedCaseIndex(0)
      return
    }
    try {
      const nextCases = (await request(
        `/runs/${selected.id}/cases`,
      )) as EvalCase[]
      setCases(nextCases)
      setSelectedCaseIndex(0)
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "评测详情加载失败",
      )
    }
  }, [request, selected])

  useEffect(() => {
    void Promise.all([loadRuns(), loadDatasets()])
  }, [loadRuns, loadDatasets])

  useEffect(() => {
    void loadCases()
  }, [loadCases])

  const summary = (selected?.summary || {}) as RunSummary
  const qualitySections = summary.quality_overview || {}
  const scoreCards = summary.score_cards || {}
  const criticalGate = summary.critical_gate
  const selectedCase = cases[selectedCaseIndex] ?? null
  const selectedCaseScores =
    selectedCase?.score_cards || selectedCase?.scores || {}

  const runBadges = useMemo(
    () => [
      {
        label: "Overall",
        value: summary.overall_status || selected?.status || "unknown",
      },
      {
        label: "Critical",
        value:
          criticalGate?.passed_rate === undefined
            ? "n/a"
            : `${Math.round((criticalGate.passed_rate || 0) * 100)}%`,
      },
      {
        label: "Cases",
        value: `${summary.passed_count ?? 0}/${summary.case_count ?? cases.length}`,
      },
      {
        label: "Trace",
        value:
          summary.trace_complete_count === undefined
            ? "n/a"
            : String(summary.trace_complete_count),
      },
    ],
    [
      cases.length,
      criticalGate?.passed_rate,
      selected?.status,
      summary.case_count,
      summary.passed_count,
      summary.overall_status,
      summary.trace_complete_count,
    ],
  )

  const importDefaults = async () => {
    try {
      const data = (await request("/datasets/import-defaults", {
        method: "POST",
      })) as EvalDataset[]
      setDatasets(data)
      if (data[0]) setDatasetId(data[0].id)
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "内置数据集导入失败",
      )
    }
  }

  const createDataset = async () => {
    try {
      const casesValue = JSON.parse(datasetText)
      if (!Array.isArray(casesValue))
        throw new Error("数据集内容必须是 JSON 数组")
      const created = (await request("/datasets", {
        method: "POST",
        body: JSON.stringify({ name: datasetName, cases: casesValue }),
      })) as EvalDataset
      setDatasets((current) => [created, ...current])
      setDatasetId(created.id)
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "数据集创建失败",
      )
    }
  }

  const runDataset = async () => {
    if (!datasetId) return
    try {
      const run = (await request(`/datasets/${datasetId}/runs`, {
        method: "POST",
      })) as EvalRun
      setRuns((current) => [run, ...current])
      setSelected(run)
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "数据集评测失败",
      )
    }
  }

  return (
    <main className="flex min-h-screen flex-1 flex-col gap-4 bg-slate-50 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <div className="flex items-center gap-2 text-slate-900">
            <BarChart3 className="h-5 w-5 text-sky-600" />
            <h1 className="text-xl font-semibold">评测分析</h1>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            查看 Run / Case / Trace / Score / Failure Reason 的分层评测结果。
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void Promise.all([loadRuns(), loadDatasets()])}
          disabled={loading}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </header>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <Card className="border-slate-200">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4 text-sky-600" />
            数据集评测
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span>已加载 {datasets.length} 个数据集</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void importDefaults()}
            >
              导入内置数据集
            </Button>
          </div>
          <div className="grid gap-3 md:grid-cols-[180px_1fr_auto]">
            <input
              value={datasetName}
              onChange={(event) => setDatasetName(event.target.value)}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm"
              placeholder="数据集名称"
            />
            <textarea
              value={datasetText}
              onChange={(event) => setDatasetText(event.target.value)}
              className="min-h-20 rounded-md border border-slate-200 px-3 py-2 font-mono text-xs"
              placeholder="JSON case 数组"
            />
            <div className="flex flex-col gap-2">
              <Button variant="outline" onClick={() => void createDataset()}>
                保存自定义数据集
              </Button>
              <select
                value={datasetId}
                onChange={(event) => setDatasetId(event.target.value)}
                className="rounded-md border border-slate-200 px-2 py-2 text-sm"
              >
                <option value="">选择数据集</option>
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}（{dataset.case_count} 条）
                  </option>
                ))}
              </select>
              <Button onClick={() => void runDataset()} disabled={!datasetId}>
                运行数据集
              </Button>
            </div>
          </div>
          {datasets.length > 0 ? (
            <div className="grid gap-2 md:grid-cols-2">
              {datasets.map((dataset) => (
                <div
                  key={dataset.id}
                  className="rounded-md border border-slate-200 px-3 py-2 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">
                      {dataset.name}
                    </span>
                    <Badge variant="outline">{dataset.case_count} 条</Badge>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    split: {dataset.split} · task: {dataset.task_type} ·{" "}
                    {dataset.status}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="min-h-0 border-slate-200">
          <CardHeader>
            <CardTitle className="text-base">评测记录</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {runs.length === 0 ? (
              <p className="text-sm text-slate-500">
                暂无评测记录。执行一次 Agent 后再来查看。
              </p>
            ) : null}
            {runs.map((run) => (
              <button
                key={run.id}
                type="button"
                onClick={() => setSelected(run)}
                className={`w-full rounded-lg border p-3 text-left transition ${
                  selected?.id === run.id
                    ? "border-sky-400 bg-sky-50"
                    : "border-slate-200 hover:bg-slate-50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">
                    {run.query || run.source_type}
                  </span>
                  <Badge
                    variant={
                      run.status === "passed" ? "default" : "destructive"
                    }
                  >
                    {run.status}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {run.task_type} ·{" "}
                  {run.created_at
                    ? new Date(run.created_at).toLocaleString("zh-CN")
                    : ""}
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-4 w-4 text-sky-600" />
                Run 总览
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {!selected ? (
                <p className="text-sm text-slate-500">
                  选择一条评测记录查看详情。
                </p>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {runBadges.map((item) => (
                      <Stat
                        key={item.label}
                        label={item.label}
                        value={String(item.value)}
                      />
                    ))}
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <Stat label="run id" value={selected.id} />
                    <Stat label="task type" value={selected.task_type} />
                    <Stat label="source" value={selected.source_type} />
                    <Stat label="query" value={selected.query || "暂无"} />
                  </div>

                  <div className="grid gap-3 lg:grid-cols-2">
                    {Object.entries(qualitySections).map(
                      ([sectionName, payload]) => (
                        <section
                          key={sectionName}
                          className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                        >
                          <div className="flex items-center gap-2 text-sm font-semibold capitalize">
                            <Activity className="h-4 w-4 text-sky-600" />
                            {sectionName}
                          </div>
                          <div className="mt-2 grid gap-2 sm:grid-cols-2">
                            {Object.entries(payload || {}).map(
                              ([key, value]) => (
                                <Stat
                                  key={key}
                                  label={key}
                                  value={String(value ?? "不可用")}
                                />
                              ),
                            )}
                          </div>
                        </section>
                      ),
                    )}
                  </div>

                  {summary.failure_taxonomy ? (
                    <section className="rounded-lg border border-slate-200 p-3">
                      <h2 className="text-sm font-semibold">
                        Failure Taxonomy
                      </h2>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {Object.entries(summary.failure_taxonomy).map(
                          ([name, value]) => (
                            <Badge key={name} variant="outline">
                              {name}: {String(value)}
                            </Badge>
                          ),
                        )}
                      </div>
                    </section>
                  ) : null}
                </>
              )}
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle className="text-base">Case 列表</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {cases.length > 0 ? (
                  cases.map((item, index) => (
                    <button
                      key={item.id || item.case_id}
                      type="button"
                      onClick={() => setSelectedCaseIndex(index)}
                      className={`w-full rounded-md border p-3 text-left transition ${
                        selectedCaseIndex === index
                          ? "border-sky-400 bg-sky-50"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">
                          {item.case_id}
                        </span>
                        <Badge
                          variant={item.passed ? "default" : "destructive"}
                        >
                          {item.status}
                        </Badge>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {item.failure_reasons?.length ?? 0} 条失败原因 ·{" "}
                        {
                          Object.keys(item.scores || item.score_cards || {})
                            .length
                        }{" "}
                        个 score
                      </div>
                    </button>
                  ))
                ) : (
                  <p className="text-sm text-slate-500">暂无 case 结果。</p>
                )}
              </CardContent>
            </Card>

            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  {selectedCase?.status === "passed" ? (
                    <ShieldCheck className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <TriangleAlert className="h-4 w-4 text-amber-600" />
                  )}
                  当前 Case 详情
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {!selectedCase ? (
                  <p className="text-sm text-slate-500">
                    选择一个 case 查看评分细节。
                  </p>
                ) : (
                  <>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Stat label="case_id" value={selectedCase.case_id} />
                      <Stat
                        label="passed"
                        value={String(selectedCase.passed ?? false)}
                      />
                      <Stat
                        label="trace steps"
                        value={String(selectedCase.trace?.length ?? 0)}
                      />
                    </div>

                    <section className="rounded-lg border border-slate-200 p-3">
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <ShieldCheck className="h-4 w-4 text-sky-600" />
                        Critical Gate
                      </div>
                      <div className="mt-2 grid gap-2 sm:grid-cols-3">
                        <Stat
                          label="passed"
                          value={String(
                            selectedCase.critical_gate?.passed ?? "n/a",
                          )}
                        />
                        <Stat
                          label="trace_complete"
                          value={String(
                            selectedCase.critical_gate?.trace_complete ?? "n/a",
                          )}
                        />
                        <Stat
                          label="blocked"
                          value={String(
                            selectedCase.critical_gate?.blocked ?? "n/a",
                          )}
                        />
                      </div>
                    </section>

                    <section className="rounded-lg border border-slate-200 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <h2 className="text-sm font-semibold">Score Cards</h2>
                        <Badge variant="outline">
                          {Object.keys(selectedCaseScores || {}).length} 个
                        </Badge>
                      </div>
                      <div className="mt-3 space-y-3">
                        {Object.entries(selectedCaseScores || {}).map(
                          ([name, score]) => (
                            <section
                              key={name}
                              className="rounded-md border border-slate-100 bg-slate-50 p-3"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2 text-sm font-semibold">
                                  <Activity className="h-4 w-4 text-sky-600" />
                                  {name}
                                </div>
                                <Badge
                                  variant={
                                    score.passed ? "default" : "destructive"
                                  }
                                >
                                  {score.passed ? "passed" : "failed"}
                                </Badge>
                              </div>
                              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                                <Stat
                                  label="failure_reasons"
                                  value={String(
                                    score.failure_reasons?.length ?? 0,
                                  )}
                                />
                                <Stat
                                  label="metrics"
                                  value={String(
                                    Object.keys(score.metrics || {}).length,
                                  )}
                                />
                                <Stat
                                  label="passed"
                                  value={String(score.passed)}
                                />
                              </div>
                              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                {Object.entries(score.metrics || {}).map(
                                  ([key, value]) => (
                                    <Stat
                                      key={key}
                                      label={key}
                                      value={String(value ?? "不可用")}
                                    />
                                  ),
                                )}
                              </div>
                              {score.failure_reasons?.length ? (
                                <div className="mt-2 text-xs text-rose-700">
                                  {score.failure_reasons.join("；")}
                                </div>
                              ) : null}
                            </section>
                          ),
                        )}
                      </div>
                    </section>

                    <section className="rounded-lg border border-slate-200 p-3">
                      <h2 className="text-sm font-semibold">Observation</h2>
                      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs text-slate-600">
                        {JSON.stringify(
                          selectedCase.observation ?? {},
                          null,
                          2,
                        )}
                      </pre>
                    </section>

                    <section className="rounded-lg border border-slate-200 p-3">
                      <h2 className="text-sm font-semibold">Trace</h2>
                      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs text-slate-600">
                        {JSON.stringify(selectedCase.trace ?? [], null, 2)}
                      </pre>
                    </section>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          {summary.score_cards ? (
            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle className="text-base">Run Score Cards</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {Object.entries(scoreCards).map(([name, score]) => (
                  <section
                    key={name}
                    className="rounded-md border border-slate-100 bg-slate-50 p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <Activity className="h-4 w-4 text-sky-600" />
                        {name}
                      </div>
                      <Badge
                        variant={
                          score.pass_rate && score.pass_rate >= 1
                            ? "default"
                            : "outline"
                        }
                      >
                        {Math.round((score.pass_rate || 0) * 100)}%
                      </Badge>
                    </div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-3">
                      <Stat
                        label="case_count"
                        value={String(score.case_count ?? 0)}
                      />
                      <Stat
                        label="passed_count"
                        value={String(score.passed_count ?? 0)}
                      />
                      <Stat
                        label="pass_rate"
                        value={String(score.pass_rate ?? 0)}
                      />
                    </div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      {Object.entries(score.metrics || {}).map(
                        ([key, value]) => (
                          <Stat
                            key={key}
                            label={key}
                            value={String(value ?? "不可用")}
                          />
                        ),
                      )}
                    </div>
                  </section>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </main>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-medium text-slate-900">
        {value}
      </div>
    </div>
  )
}
