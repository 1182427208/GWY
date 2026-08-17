import { createFileRoute } from "@tanstack/react-router"
import {
  Activity,
  Bot,
  ChevronDown,
  FileText,
  Image as ImageIcon,
  Mic,
  MicOff,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
} from "lucide-react"
import {
  type ChangeEvent,
  type ClipboardEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { OpenAPI } from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

type ChatSession = {
  id: string
  title: string
  last_intent?: string | null
  active_topic?: string | null
  mentioned_docs?: string[]
  summary?: string | null
  summary_updated_at?: string | null
  created_at?: string | null
}

type ChatAttachment = {
  id: string
  session_id: string
  file_name: string
  original_name: string
  attachment_type: string
  mime_type: string
  file_path: string
  size_bytes: number
  summary?: string | null
  extracted_text?: string | null
  extraction_status: string
  metadata_json: Record<string, unknown>
  created_at?: string | null
}

type ChatCitation = {
  source_kind?: string | null
  chunk_id?: string | null
  source_file?: string | null
  doc_title?: string | null
  section?: string | null
  page_start?: number | null
  page_end?: number | null
  content?: string | null
  content_excerpt?: string | null
  score?: number | null
  rerank_score?: number | null
  doc_group?: string | null
  doc_type?: string | null
  year?: number | null
  exam_type?: string | null
  province?: string | null
  attachment_id?: string | null
  file_name?: string | null
  original_name?: string | null
  attachment_type?: string | null
  mime_type?: string | null
  file_path?: string | null
  summary?: string | null
  extracted_text?: string | null
  metadata?: Record<string, unknown> | null
}

type ChatMessage = {
  id: string
  session_id: string
  role: "user" | "assistant"
  content: string
  intent?: string | null
  historical_reference: boolean
  citations: ChatCitation[]
  retrieval_trace: Record<string, unknown>[]
  metadata_json: Record<string, unknown>
  created_at?: string | null
}

type AgentRiskItem = {
  risk_type?: string | null
  risk_level?: string | null
  evidence?: string | null
  explanation?: string | null
  suggestion?: string | null
  need_manual_confirm?: boolean | null
  source?: string | null
}

type AgentRiskReview = {
  risk_level?: string | null
  need_manual_confirm?: boolean | null
  risk_items?: AgentRiskItem[]
  trace?: Record<string, unknown>[]
}

type AgentTodo = {
  content: string
  status: "pending" | "in_progress" | "completed"
}

type ChatRequestMode =
  | "policy_rag"
  | "position_recommendation"
  | "autonomous_agent"

type ChatQueryResponse = {
  answer: string
  intent: string
  need_rag: boolean
  decision_branch?: string | null
  need_more_info?: boolean
  missing_fields?: string[]
  recommendation_task_id?: string | null
  citations: ChatCitation[]
  retrieval_trace: Record<string, unknown>[]
  rewritten_queries: string[]
  metadata_filter?: string | null
  rerank_results: Record<string, unknown>[]
  historical_reference: boolean
  risk_review?: AgentRiskReview
  report?: string | null
  session?: ChatSession | null
  user_message?: ChatMessage | null
  assistant_message?: ChatMessage | null
}

type SessionListResponse = {
  data: ChatSession[]
  count: number
}

type MessageListResponse = {
  data: ChatMessage[]
  count: number
}

type AttachmentListResponse = {
  data: ChatAttachment[]
  count: number
}

type SseEvent = {
  event: string
  data: unknown
}

type StreamStage = {
  step: string
  label: string
  status: "running" | "done" | "error"
  detail?: string
  elapsed_ms?: number
  total_elapsed_ms?: number
}

type StreamState = {
  started_at: string
  stages: StreamStage[]
  total_elapsed_ms?: number
}

const KNOWLEDGE_BASE_OPTIONS = [
  { value: "", label: "全部知识库" },
  { value: "technical_qa", label: "技术问答" },
  { value: "exam_affairs_qa", label: "考务问答" },
  { value: "policy_qa", label: "政策问答" },
  { value: "announcement", label: "招考公告" },
  { value: "exam_outline", label: "考试大纲" },
  { value: "major_catalog", label: "专业目录" },
] as const

const PRESET_QUESTION_POOL = [
  "如何打印准考证？",
  "报名确认后还能修改信息吗？",
  "资格审查没通过怎么办？",
  "公告里的年龄条件怎么理解？",
  "这个职位的专业要求怎么判断？",
  "专业目录中的一级学科如何匹配？",
  "笔试科目和考试大纲在哪里看？",
  "体检和考察有什么注意事项？",
  "违纪违规会怎么处理？",
  "这个岗位是否适合应届生？",
  "如果我上传一份文件，你能帮我读重点吗？",
  "图片里的表格内容如何理解？",
]

const DEFAULT_YEAR = String(new Date().getFullYear())
const DEFAULT_SESSION_TITLE = "AI 小助手"
const _ASSISTANT_NAME = "GwyPilot"
const WELCOME_TITLE = "你好，我是 GwyPilot"
const WELCOME_BODY =
  "你可以把公告、报考指南、截图或题目发给我。我会帮你检索政策、梳理条件并尽量给出可执行的答复。"
const WELCOME_HINT =
  "如果想通过语音提问，可以直接点麦克风；如果想听回答，也可以打开自动播报。"

type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onstart: (() => void) | null
  onresult: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") {
    return null
  }

  const scope = window as Window & {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }

  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null
}

function stripMarkdownForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/[#>*_~=-]/g, " ")
    .replace(/\n{2,}/g, "\n")
    .replace(/[ \t]+/g, " ")
    .trim()
}

async function requestMicrophonePermission(): Promise<boolean> {
  if (
    typeof navigator === "undefined" ||
    !navigator.mediaDevices?.getUserMedia
  ) {
    return false
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((track) => track.stop())
    return true
  } catch {
    return false
  }
}

export const Route = createFileRoute("/_layout/gwy/chat")({
  component: GwyChatPage,
  head: () => ({
    meta: [
      {
        title: "GwyPilot - 政策对话",
      },
    ],
  }),
})

function GwyChatPage() {
  const apiBase = OpenAPI.BASE || ""
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const suppressSessionLoadRef = useRef<string | null>(null)
  const streamFlushTimerRef = useRef<number | null>(null)
  const speechRecognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioUrlRef = useRef<string | null>(null)
  const lastSpokenMessageIdRef = useRef<string | null>(null)
  const speechRecognitionHadErrorRef = useRef(false)
  const speechRecognitionManualStopRef = useRef(false)
  const streamBufferRef = useRef<{
    assistantMessageId: string | null
    answer: string
    reasoning: string
  }>({
    assistantMessageId: null,
    answer: "",
    reasoning: "",
  })
  const speechDraftRef = useRef("")
  const { user: currentUser } = useAuth()

  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [draft, setDraft] = useState("")
  const [year, setYear] = useState(DEFAULT_YEAR)
  const [knowledgeBase, setKnowledgeBase] = useState("")
  const [topK, setTopK] = useState(6)
  const [useRerank, setUseRerank] = useState(true)
  const [evaluationEnabled, setEvaluationEnabled] = useState(false)
  const [voiceInputSupported, setVoiceInputSupported] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [autoSpeak, setAutoSpeak] = useState(true)
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [loadingAttachments, setLoadingAttachments] = useState(false)
  const [sending, setSending] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null,
  )
  const [deletingAttachmentId, setDeletingAttachmentId] = useState<
    string | null
  >(null)
  const [error, setError] = useState<string | null>(null)

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? null,
    [activeSessionId, sessions],
  )

  const presetQuestions = useMemo(
    () =>
      buildPresetQuestions(
        activeSessionId || activeSession?.title || "default",
      ),
    [activeSession?.title, activeSessionId],
  )

  const knowledgeBaseLabel =
    KNOWLEDGE_BASE_OPTIONS.find((option) => option.value === knowledgeBase)
      ?.label ?? "全部知识库"
  const currentUserLabel = useMemo(() => {
    const fullName = currentUser?.full_name?.trim()
    if (fullName) {
      return fullName
    }

    const email = currentUser?.email?.trim()
    if (email) {
      return email.split("@")[0] || email
    }

    return "我"
  }, [currentUser?.email, currentUser?.full_name])

  const authHeaders = useCallback(
    () => ({
      Authorization: `Bearer ${localStorage.getItem("access_token") || ""}`,
    }),
    [],
  )

  const requestJson = useCallback(
    async <T,>(path: string, options: RequestInit = {}): Promise<T> => {
      const method = (options.method || "GET").toUpperCase()
      const response = await fetch(`${apiBase}${path}`, {
        ...options,
        headers: {
          ...authHeaders(),
          ...(options.headers || {}),
          ...(method !== "GET" && method !== "HEAD" && method !== "OPTIONS"
            ? { "Content-Type": "application/json" }
            : {}),
        },
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payload?.detail || `请求失败，状态码 ${response.status}`,
        )
      }
      return (await response.json()) as T
    },
    [apiBase, authHeaders],
  )

  const requestMultipart = useCallback(
    async <T,>(path: string, formData: FormData): Promise<T> => {
      const response = await fetch(`${apiBase}${path}`, {
        method: "POST",
        headers: {
          ...authHeaders(),
        },
        body: formData,
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payload?.detail || `上传失败，状态码 ${response.status}`,
        )
      }
      return (await response.json()) as T
    },
    [apiBase, authHeaders],
  )

  const requestStream = useCallback(
    async (
      path: string,
      body: Record<string, unknown>,
      onDelta: (delta: string) => void,
      onReasoning: (delta: string) => void,
      onStage: (stage: StreamStage) => void,
      onTrace?: (trace: Record<string, unknown>) => void,
      onSources?: (citations: ChatCitation[]) => void,
      onReport?: (report: string) => void,
    ): Promise<ChatQueryResponse> => {
      let lastStage = "init"
      try {
        const response = await fetch(`${apiBase}${path}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders(),
          },
          body: JSON.stringify(body),
        })

        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as {
            detail?: string
          } | null
          throw new Error(
            payload?.detail || `请求失败，状态码 ${response.status}`,
          )
        }

        if (!response.body) {
          throw new Error("浏览器不支持流式响应")
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder("utf-8")
        let buffer = ""
        let finalPayload: ChatQueryResponse | null = null

        while (true) {
          const { value, done } = await reader.read()
          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })
          let separatorIndex = buffer.indexOf("\n\n")
          while (separatorIndex >= 0) {
            const frame = buffer.slice(0, separatorIndex)
            buffer = buffer.slice(separatorIndex + 2)
            const event = parseSseFrame(frame)
            if (event?.event === "delta") {
              const delta = extractDelta(event.data)
              if (delta) {
                onDelta(delta)
              }
            } else if (event?.event === "reasoning") {
              const reasoning = extractDelta(event.data)
              if (reasoning) {
                onReasoning(reasoning)
              }
            } else if (event?.event === "stage") {
              const stage = extractStage(event.data)
              if (stage) {
                lastStage = stage.step
                onStage(stage)
              }
            } else if (event?.event === "trace") {
              const trace = extractTrace(event.data)
              if (trace && onTrace) {
                onTrace(trace)
              }
            } else if (event?.event === "sources") {
              const citations = extractCitations(event.data)
              if (citations.length > 0 && onSources) {
                onSources(citations)
              }
            } else if (event?.event === "report") {
              const report = extractReport(event.data)
              if (report && onReport) {
                onReport(report)
              }
            } else if (event?.event === "done") {
              finalPayload = event.data as ChatQueryResponse
            } else if (event?.event === "error") {
              const detail = extractErrorDetail(event.data) || "流式回答失败"
              const stage = extractErrorStage(event.data)
              throw new Error(
                stage
                  ? `${formatStreamStageLabel(stage)}：${detail}`
                  : `${formatStreamStageLabel(lastStage)}：${detail}`,
              )
            }
            separatorIndex = buffer.indexOf("\n\n")
          }
        }

        if (!finalPayload) {
          throw new Error("流式响应未返回完整结果")
        }
        return finalPayload
      } catch (error) {
        const message = error instanceof Error ? error.message : "流式请求失败"
        if (message.includes("：")) {
          throw error
        }
        throw new Error(`${formatStreamStageLabel(lastStage)}：${message}`)
      }
    },
    [apiBase, authHeaders],
  )

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true)
    setError(null)
    try {
      const payload = await requestJson<SessionListResponse>(
        "/api/v1/gwy/chat/sessions",
      )
      setSessions(payload.data)
      setActiveSessionId((current) => {
        if (current && payload.data.some((session) => session.id === current)) {
          return current
        }
        return payload.data[0]?.id ?? null
      })
      if (payload.data.length === 0) {
        setMessages([])
        setAttachments([])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载会话失败")
    } finally {
      setLoadingSessions(false)
    }
  }, [requestJson])

  const resetConversationState = useCallback(() => {
    setMessages([])
    setAttachments([])
    setError(null)
    setActiveSessionId(null)
    suppressSessionLoadRef.current = null
  }, [])

  const loadMessages = useCallback(
    async (sessionId: string) => {
      setLoadingMessages(true)
      setError(null)
      try {
        const payload = await requestJson<MessageListResponse>(
          `/api/v1/gwy/chat/sessions/${sessionId}/messages`,
        )
        setMessages(payload.data)
      } catch (err) {
        const message = err instanceof Error ? err.message : "加载消息失败"
        if (isMissingSessionError(message)) {
          resetConversationState()
          await loadSessions()
          return
        }
        setMessages([])
        setError(message)
      } finally {
        setLoadingMessages(false)
      }
    },
    [loadSessions, requestJson, resetConversationState],
  )

  const loadAttachments = useCallback(
    async (sessionId: string) => {
      setLoadingAttachments(true)
      setError(null)
      try {
        const payload = await requestJson<AttachmentListResponse>(
          `/api/v1/gwy/chat/sessions/${sessionId}/attachments`,
        )
        setAttachments(payload.data)
      } catch (err) {
        const message = err instanceof Error ? err.message : "加载附件失败"
        if (isMissingSessionError(message)) {
          resetConversationState()
          await loadSessions()
          return
        }
        setAttachments([])
        setError(message)
      } finally {
        setLoadingAttachments(false)
      }
    },
    [loadSessions, requestJson, resetConversationState],
  )

  const createSession = useCallback(
    async (activate = true) => {
      setCreatingSession(true)
      setError(null)
      try {
        const payload = await requestJson<ChatSession>(
          "/api/v1/gwy/chat/sessions",
          {
            method: "POST",
            body: JSON.stringify({
              title: DEFAULT_SESSION_TITLE,
            }),
          },
        )
        setSessions((current) => [
          payload,
          ...current.filter((item) => item.id !== payload.id),
        ])
        if (activate) {
          setActiveSessionId(payload.id)
          setMessages([])
          setAttachments([])
          suppressSessionLoadRef.current = payload.id
        }
        return payload
      } catch (err) {
        setError(err instanceof Error ? err.message : "创建会话失败")
        return null
      } finally {
        setCreatingSession(false)
      }
    },
    [requestJson],
  )

  const ensureSession = useCallback(async () => {
    if (activeSessionId) {
      return activeSessionId
    }
    const created = await createSession(true)
    return created?.id ?? null
  }, [activeSessionId, createSession])

  useEffect(() => {
    void loadSessions()
  }, [loadSessions])

  useEffect(() => {
    if (!activeSessionId) {
      return
    }
    if (suppressSessionLoadRef.current === activeSessionId) {
      suppressSessionLoadRef.current = null
      return
    }
    void loadMessages(activeSessionId)
    void loadAttachments(activeSessionId)
  }, [activeSessionId, loadAttachments, loadMessages])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [])

  useEffect(() => {
    const RecognitionCtor = getSpeechRecognitionConstructor()
    setVoiceInputSupported(Boolean(RecognitionCtor))
    return () => {
      speechRecognitionRef.current?.abort()
      speechRecognitionRef.current = null
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current)
        audioUrlRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    return () => {
      if (streamFlushTimerRef.current !== null) {
        window.clearTimeout(streamFlushTimerRef.current)
      }
    }
  }, [])

  const updateSessionInList = useCallback((nextSession: ChatSession) => {
    setSessions((current) => [
      nextSession,
      ...current.filter((item) => item.id !== nextSession.id),
    ])
  }, [])

  const updateStreamingAssistant = useCallback(
    (
      assistantMessageId: string,
      updater: (message: ChatMessage) => ChatMessage,
    ) => {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessageId ? updater(message) : message,
        ),
      )
    },
    [],
  )

  const flushStreamBuffer = useCallback(
    (assistantMessageId: string) => {
      const buffer = streamBufferRef.current
      if (buffer.assistantMessageId !== assistantMessageId) {
        return
      }

      const answerDelta = buffer.answer
      const reasoningDelta = buffer.reasoning
      if (!answerDelta && !reasoningDelta) {
        return
      }

      buffer.answer = ""
      buffer.reasoning = ""

      updateStreamingAssistant(assistantMessageId, (message) => {
        const nextMetadata = isRecord(message.metadata_json)
          ? message.metadata_json
          : {}
        const currentReasoning =
          typeof nextMetadata.reasoning_content === "string"
            ? nextMetadata.reasoning_content
            : ""
        return {
          ...message,
          content: `${message.content}${answerDelta}`,
          metadata_json: {
            ...nextMetadata,
            streaming: true,
            reasoning_content: `${currentReasoning}${reasoningDelta}`,
          },
        }
      })
    },
    [updateStreamingAssistant],
  )

  const scheduleStreamFlush = useCallback(
    (assistantMessageId: string) => {
      streamBufferRef.current.assistantMessageId = assistantMessageId
      if (streamFlushTimerRef.current !== null) {
        window.clearTimeout(streamFlushTimerRef.current)
      }
      streamFlushTimerRef.current = window.setTimeout(() => {
        streamFlushTimerRef.current = null
        flushStreamBuffer(assistantMessageId)
      }, 40)
    },
    [flushStreamBuffer],
  )

  const queueStreamAnswerDelta = useCallback(
    (assistantMessageId: string, delta: string) => {
      if (!delta) {
        return
      }
      const buffer = streamBufferRef.current
      if (buffer.assistantMessageId !== assistantMessageId) {
        buffer.assistantMessageId = assistantMessageId
      }
      buffer.answer += delta
      scheduleStreamFlush(assistantMessageId)
    },
    [scheduleStreamFlush],
  )

  const queueStreamReasoningDelta = useCallback(
    (assistantMessageId: string, delta: string) => {
      if (!delta) {
        return
      }
      const buffer = streamBufferRef.current
      if (buffer.assistantMessageId !== assistantMessageId) {
        buffer.assistantMessageId = assistantMessageId
      }
      buffer.reasoning += delta
      scheduleStreamFlush(assistantMessageId)
    },
    [scheduleStreamFlush],
  )

  const replaceOptimisticMessages = useCallback(
    (
      tempUserId: string,
      tempAssistantId: string,
      payload: ChatQueryResponse,
    ) => {
      setMessages((current) => {
        const nextMessages = current.filter(
          (message) =>
            message.id !== tempUserId && message.id !== tempAssistantId,
        )
        const optimisticAssistant = current.find(
          (message) => message.id === tempAssistantId,
        )
        const preservedAssistantMetadata =
          optimisticAssistant?.metadata_json || {}
        const optimisticUserIndex = current.findIndex(
          (message) => message.id === tempUserId,
        )
        const assistantIndex = current.findIndex(
          (message) => message.id === tempAssistantId,
        )

        if (payload.user_message) {
          if (optimisticUserIndex >= 0) {
            nextMessages.splice(optimisticUserIndex, 0, payload.user_message)
          } else {
            nextMessages.push(payload.user_message)
          }
        }

        if (payload.assistant_message) {
          const assistantMessage: ChatMessage = {
            ...payload.assistant_message,
            metadata_json: {
              ...payload.assistant_message.metadata_json,
              ...preservedAssistantMetadata,
            },
          }
          if (assistantIndex >= 0) {
            const insertAt = Math.min(
              assistantIndex + (payload.user_message ? 1 : 0),
              nextMessages.length,
            )
            nextMessages.splice(insertAt, 0, assistantMessage)
          } else {
            nextMessages.push(assistantMessage)
          }
        }

        return nextMessages
      })
    },
    [],
  )

  const streamChatResponse = useCallback(
    async (
      sessionId: string,
      query: string,
      assistantMessageId: string,
      options: {
        mode?: ChatRequestMode
        intentHint?: string
        positionProfile?: Record<string, unknown> | null
      } = {},
    ) => {
      streamBufferRef.current = {
        assistantMessageId,
        answer: "",
        reasoning: "",
      }

      const requestBody: Record<string, unknown> = {
        query,
        year: Number(year) || Number(DEFAULT_YEAR),
        exam_type: "national",
        doc_group: knowledgeBase || null,
        top_k: topK,
        use_rerank: useRerank,
        mode: options.mode || null,
        intent_hint: options.intentHint || null,
        position_profile: options.positionProfile || null,
        enable_evaluation: evaluationEnabled,
      }

      try {
        const payload = await requestStream(
          `/api/v1/gwy/chat/sessions/${sessionId}/messages/stream`,
          requestBody,
          (delta) => {
            queueStreamAnswerDelta(assistantMessageId, delta)
          },
          (reasoningDelta) => {
            queueStreamReasoningDelta(assistantMessageId, reasoningDelta)
          },
          (stage) => {
            updateStreamingAssistant(assistantMessageId, (message) =>
              mergeStageIntoMessage(message, stage),
            )
          },
          (trace) => {
            updateStreamingAssistant(assistantMessageId, (message) => ({
              ...message,
              retrieval_trace: [...message.retrieval_trace, trace],
            }))
          },
          (citations) => {
            updateStreamingAssistant(assistantMessageId, (message) => ({
              ...message,
              citations,
            }))
          },
          (report) => {
            updateStreamingAssistant(assistantMessageId, (message) => ({
              ...message,
              metadata_json: {
                ...(isRecord(message.metadata_json)
                  ? message.metadata_json
                  : {}),
                report,
              },
            }))
          },
        )
        flushStreamBuffer(assistantMessageId)
        return payload
      } finally {
        if (streamFlushTimerRef.current !== null) {
          window.clearTimeout(streamFlushTimerRef.current)
          streamFlushTimerRef.current = null
        }
      }
    },
    [
      knowledgeBase,
      flushStreamBuffer,
      requestStream,
      topK,
      queueStreamAnswerDelta,
      queueStreamReasoningDelta,
      updateStreamingAssistant,
      useRerank,
      year,
      evaluationEnabled,
    ],
  )

  async function submitQuery(
    query: string,
    options: {
      mode?: ChatRequestMode
      intentHint?: string
      positionProfile?: Record<string, unknown> | null
    } = {},
    allowRetry = true,
  ) {
    const sessionId = await ensureSession()
    if (!sessionId) {
      throw new Error("无法创建会话")
    }

    const tempUserId = `temp-user-${crypto.randomUUID()}`
    const tempAssistantId = `temp-assistant-${crypto.randomUUID()}`
    const optimisticUserMessage: ChatMessage = {
      id: tempUserId,
      session_id: sessionId,
      role: "user",
      content: query,
      historical_reference: false,
      citations: [],
      retrieval_trace: [],
      metadata_json: {},
      created_at: new Date().toISOString(),
    }
    const optimisticAssistantMessage: ChatMessage = {
      id: tempAssistantId,
      session_id: sessionId,
      role: "assistant",
      content: "",
      historical_reference: false,
      citations: [],
      retrieval_trace: [],
      metadata_json: { streaming: true, reasoning_content: "" },
      created_at: new Date().toISOString(),
    }

    setMessages((current) => [
      ...current,
      optimisticUserMessage,
      optimisticAssistantMessage,
    ])
    setDraft("")
    setError(null)

    try {
      const payload = await streamChatResponse(
        sessionId,
        query,
        tempAssistantId,
        options,
      )
      replaceOptimisticMessages(tempUserId, tempAssistantId, payload)
      if (payload.session) {
        updateSessionInList(payload.session)
        setActiveSessionId(payload.session.id)
      } else {
        void loadSessions()
      }
      void speakLatestAssistant(payload.assistant_message)
      void loadAttachments(sessionId)
    } catch (err) {
      const message = err instanceof Error ? err.message : "发送消息失败"
      if (allowRetry && isMissingSessionError(message)) {
        resetConversationState()
        const replacement = await createSession(true)
        if (replacement?.id) {
          await submitQuery(query, {}, false)
          return
        }
      }
      await loadMessages(sessionId)
      await loadAttachments(sessionId)
      setError(message)
    }
  }

  async function sendQuery(query: string) {
    if (sending) {
      return
    }

    stopAudioPlayback()
    setSending(true)
    try {
      await submitQuery(query, { mode: "autonomous_agent" })
    } finally {
      setSending(false)
    }
  }

  function stopAudioPlayback() {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ""
      audioRef.current = null
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current)
      audioUrlRef.current = null
    }
    setVoiceStatus(null)
  }

  async function speakResponseText(text: string, force = false) {
    if (!text.trim() || (!autoSpeak && !force)) {
      return
    }

    const response = await fetch(`${apiBase}/api/v1/gwy/audio/speech`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({ text }),
    })
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as {
        detail?: string
      } | null
      throw new Error(
        payload?.detail || `语音播报失败，状态码 ${response.status}`,
      )
    }

    const audioBlob = await response.blob()
    const objectUrl = URL.createObjectURL(audioBlob)
    stopAudioPlayback()
    const audio = new Audio(objectUrl)
    audioUrlRef.current = objectUrl
    audioRef.current = audio
    setVoiceStatus("正在播报回答...")

    audio.onended = () => {
      if (audioUrlRef.current === objectUrl) {
        URL.revokeObjectURL(objectUrl)
        audioUrlRef.current = null
      }
      if (audioRef.current === audio) {
        audioRef.current = null
      }
      setVoiceStatus(null)
    }
    audio.onerror = () => {
      if (audioUrlRef.current === objectUrl) {
        URL.revokeObjectURL(objectUrl)
        audioUrlRef.current = null
      }
      if (audioRef.current === audio) {
        audioRef.current = null
      }
      setVoiceStatus("语音播报失败，请点击播报按钮重试。")
    }

    try {
      await audio.play()
    } catch (error) {
      setVoiceStatus(
        error instanceof Error
          ? `浏览器阻止自动播报：${error.message}`
          : "浏览器阻止自动播报，请手动点击播报按钮。",
      )
    }
  }

  async function toggleVoiceInput() {
    if (!voiceInputSupported) {
      setVoiceStatus("当前浏览器不支持语音输入。")
      return
    }

    if (isListening) {
      speechRecognitionManualStopRef.current = true
      speechRecognitionRef.current?.stop()
      return
    }

    const RecognitionCtor = getSpeechRecognitionConstructor()
    if (!RecognitionCtor) {
      setVoiceStatus("当前浏览器不支持语音输入。")
      return
    }

    setVoiceStatus("正在请求麦克风权限...")
    const microphoneGranted = await requestMicrophonePermission()
    if (!microphoneGranted) {
      setVoiceStatus("麦克风未授权或不可用，请先允许浏览器访问麦克风。")
      return
    }

    stopAudioPlayback()
    const recognition = new RecognitionCtor()
    speechDraftRef.current = ""
    speechRecognitionHadErrorRef.current = false
    speechRecognitionManualStopRef.current = false
    recognition.lang = "zh-CN"
    recognition.continuous = false
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setIsListening(true)
      setVoiceStatus("麦克风已开启，正在等待语音输入...")
    }

    recognition.onresult = (event: any) => {
      let interimTranscript = ""
      let finalTranscript = ""
      for (
        let index = event.resultIndex;
        index < event.results.length;
        index += 1
      ) {
        const result = event.results[index]
        const transcript = String(result[0]?.transcript || "").trim()
        if (!transcript) {
          continue
        }
        if (result.isFinal) {
          finalTranscript = `${finalTranscript} ${transcript}`.trim()
        } else {
          interimTranscript = `${interimTranscript} ${transcript}`.trim()
        }
      }
      const bestTranscript = finalTranscript || interimTranscript
      if (bestTranscript) {
        speechDraftRef.current = bestTranscript
      }
      setVoiceStatus(
        interimTranscript ? `识别中：${interimTranscript}` : "识别中...",
      )
    }

    recognition.onerror = (event: any) => {
      setIsListening(false)
      speechRecognitionHadErrorRef.current = true
      speechDraftRef.current = ""
      const errorType = String(event?.error || "")
      if (errorType === "not-allowed" || errorType === "service-not-allowed") {
        setVoiceStatus("麦克风或语音服务被浏览器拦截，请检查权限后重试。")
      } else if (errorType === "no-speech") {
        setVoiceStatus("没有识别到有效语音，请靠近麦克风后再试。")
      } else {
        setVoiceStatus(
          `语音识别失败${event?.error ? `：${String(event.error)}` : ""}`,
        )
      }
      speechRecognitionRef.current = null
    }

    recognition.onend = () => {
      setIsListening(false)
      const hadError = speechRecognitionHadErrorRef.current
      const wasManualStop = speechRecognitionManualStopRef.current
      speechRecognitionHadErrorRef.current = false
      speechRecognitionManualStopRef.current = false

      if (hadError) {
        speechDraftRef.current = ""
        speechRecognitionRef.current = null
        return
      }

      const transcript = speechDraftRef.current.trim()
      if (transcript) {
        setDraft((current) =>
          current.trim().length > 0
            ? `${current.trimEnd()} ${transcript}`
            : transcript,
        )
        setVoiceStatus("语音内容已写入输入框。")
      } else if (!wasManualStop) {
        setVoiceStatus("未识别到有效语音，请再试一次。")
      } else {
        setVoiceStatus("语音输入已停止。")
      }
      speechDraftRef.current = ""
      speechRecognitionRef.current = null
    }

    speechRecognitionRef.current = recognition
    setIsListening(true)
    setVoiceStatus("正在听写，请开始说话...")
    try {
      recognition.start()
    } catch (error) {
      setIsListening(false)
      speechRecognitionHadErrorRef.current = true
      setVoiceStatus(
        error instanceof Error
          ? `无法启动语音输入：${error.message}`
          : "无法启动语音输入。",
      )
      speechRecognitionRef.current = null
    }
  }

  async function speakAssistantMessage(
    message: ChatMessage | null | undefined,
    force = false,
  ) {
    if (!message || message.role !== "assistant") {
      return
    }
    if (!force && !autoSpeak) {
      return
    }
    if (!force && lastSpokenMessageIdRef.current === message.id) {
      return
    }
    lastSpokenMessageIdRef.current = message.id
    try {
      await speakResponseText(stripMarkdownForSpeech(message.content), force)
    } catch (error) {
      setVoiceStatus(error instanceof Error ? error.message : "语音播报失败。")
    }
  }

  function speakLatestAssistant(message: ChatMessage | null | undefined) {
    void speakAssistantMessage(message, false)
  }

  const deleteSession = useCallback(
    async (sessionId: string) => {
      if (
        !window.confirm("确认删除这个会话吗？删除后消息、附件和缓存都会清理。")
      ) {
        return
      }
      setDeletingSessionId(sessionId)
      setError(null)
      try {
        await requestJson<{ message: string }>(
          `/api/v1/gwy/chat/sessions/${sessionId}`,
          { method: "DELETE" },
        )
        setSessions((current) => {
          const nextSessions = current.filter((item) => item.id !== sessionId)
          const nextActive =
            activeSessionId === sessionId
              ? (nextSessions[0]?.id ?? null)
              : activeSessionId
          if (activeSessionId === sessionId) {
            setMessages([])
            setAttachments([])
          }
          setActiveSessionId(nextActive)
          return nextSessions
        })
        if (activeSessionId !== sessionId) {
          void loadSessions()
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除会话失败")
      } finally {
        setDeletingSessionId(null)
      }
    },
    [activeSessionId, loadSessions, requestJson],
  )

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isListening) {
      speechRecognitionManualStopRef.current = true
      speechRecognitionRef.current?.stop()
      setVoiceStatus("语音输入已停止，请确认文本已写入后再发送。")
      return
    }
    stopAudioPlayback()
    const query = draft.trim()
    if (!query) {
      return
    }
    await sendQuery(query)
  }

  const handleQuickAsk = async (query: string) => {
    await sendQuery(query)
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const uploadFiles = useCallback(
    async (files: File[], allowRetry = true) => {
      if (files.length === 0) {
        return
      }

      const sessionId = await ensureSession()
      if (!sessionId) {
        return
      }

      const formData = new FormData()
      files.forEach((file) => {
        formData.append("files", file)
      })

      setUploading(true)
      setError(null)
      try {
        const payload = await requestMultipart<AttachmentListResponse>(
          `/api/v1/gwy/chat/sessions/${sessionId}/attachments`,
          formData,
        )
        setAttachments(payload.data)
        void loadSessions()
      } catch (err) {
        const message = err instanceof Error ? err.message : "上传附件失败"
        if (allowRetry && isMissingSessionError(message)) {
          resetConversationState()
          const replacement = await createSession(true)
          if (replacement?.id) {
            await uploadFiles(files, false)
            return
          }
        }
        setError(message)
      } finally {
        setUploading(false)
      }
    },
    [
      createSession,
      ensureSession,
      loadSessions,
      requestMultipart,
      resetConversationState,
    ],
  )

  const deleteAttachment = useCallback(
    async (attachmentId: string) => {
      if (!window.confirm("确认删除这个附件吗？删除后它会从当前会话中移除。")) {
        return
      }

      const sessionId = await ensureSession()
      if (!sessionId) {
        return
      }

      setDeletingAttachmentId(attachmentId)
      setError(null)
      try {
        await requestJson<{ message: string }>(
          `/api/v1/gwy/chat/sessions/${sessionId}/attachments/${attachmentId}`,
          { method: "DELETE" },
        )
        setAttachments((current) =>
          current.filter((item) => item.id !== attachmentId),
        )
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除附件失败")
      } finally {
        setDeletingAttachmentId(null)
      }
    },
    [ensureSession, requestJson],
  )

  const handleFilesSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ""
    await uploadFiles(files)
  }

  const handlePaste = async (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const clipboardFiles = Array.from(event.clipboardData.files || [])
    const itemFiles = Array.from(event.clipboardData.items || [])
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null)
    const files = [...clipboardFiles, ...itemFiles].filter(
      (file, index, all) =>
        all.findIndex(
          (candidate) =>
            candidate.name === file.name &&
            candidate.size === file.size &&
            candidate.lastModified === file.lastModified,
        ) === index,
    )
    if (files.length === 0) {
      return
    }
    event.preventDefault()
    await uploadFiles(files)
  }

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 overflow-hidden bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] text-slate-900">
      <aside className="flex h-full w-[300px] min-w-[260px] max-w-[340px] flex-col border-r border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="flex items-center justify-between px-4 py-4">
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight text-slate-950">
              GwyPilot
            </h1>
            <p className="mt-1 text-xs text-slate-500">AI 小助手 · 政策对话</p>
          </div>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => {
              void loadSessions()
            }}
            aria-label="刷新会话"
          >
            <RefreshCw
              className={cn("h-4 w-4", loadingSessions && "animate-spin")}
            />
          </Button>
        </div>

        <div className="space-y-3 px-4 pb-3">
          <Button
            className="h-10 w-full rounded-full bg-slate-950 text-white hover:bg-slate-800"
            onClick={() => {
              void createSession()
            }}
            disabled={creatingSession}
          >
            <Plus className="mr-2 h-4 w-4" />
            新建对话
          </Button>

          <button
            type="button"
            className="flex w-full items-center justify-between rounded-full border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            onClick={() => setSettingsOpen((current) => !current)}
          >
            <span>高级设置</span>
            <span className="flex items-center gap-2 text-xs text-slate-500">
              <span>{knowledgeBaseLabel}</span>
              <span>{useRerank ? "重排开启" : "重排关闭"}</span>
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform",
                  settingsOpen && "rotate-180",
                )}
              />
            </span>
          </button>

          {settingsOpen ? (
            <div className="space-y-3 rounded-2xl border border-slate-200/80 bg-slate-50 p-3">
              <label className="block text-xs font-medium text-slate-500">
                知识库
                <select
                  value={knowledgeBase}
                  onChange={(event) => setKnowledgeBase(event.target.value)}
                  className="mt-2 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none transition focus:border-slate-400"
                >
                  {KNOWLEDGE_BASE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                <span>启用重排</span>
                <input
                  checked={useRerank}
                  onChange={(event) => setUseRerank(event.target.checked)}
                  type="checkbox"
                  className="size-4 accent-slate-900"
                />
              </label>

              <div className="grid grid-cols-2 gap-2">
                <Input
                  value={year}
                  type="number"
                  min={2020}
                  max={2100}
                  onChange={(event) => setYear(event.target.value)}
                  className="h-10 bg-white"
                />
                <Input
                  value={topK}
                  type="number"
                  min={1}
                  max={20}
                  onChange={(event) => setTopK(Number(event.target.value || 6))}
                  className="h-10 bg-white"
                />
              </div>
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between px-4 pb-2 pt-1">
          <span className="text-sm font-medium text-slate-700">会话</span>
          <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
            {sessions.length}
          </span>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-2 pb-4">
          {loadingSessions ? (
            <div className="px-3 py-2 text-sm text-slate-500">
              正在加载会话...
            </div>
          ) : sessions.length === 0 ? (
            <div className="px-3 py-2 text-sm text-slate-500">
              还没有会话，点击“新建对话”开始。
            </div>
          ) : (
            sessions.map((session) => (
              <div
                key={session.id}
                className={cn(
                  "group mb-1 flex items-start gap-1 rounded-2xl px-2 py-2 transition",
                  activeSessionId === session.id
                    ? "bg-slate-100 ring-1 ring-slate-200"
                    : "hover:bg-slate-50",
                )}
              >
                <button
                  className="min-w-0 flex-1 text-left"
                  onClick={() => setActiveSessionId(session.id)}
                  type="button"
                >
                  <div className="truncate text-sm font-medium text-slate-900">
                    {displaySessionTitle(session.title)}
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                    {session.summary || "暂无会话摘要"}
                  </div>
                </button>
                <Button
                  size="icon"
                  variant="ghost"
                  className={cn(
                    "mt-0.5 h-8 w-8 shrink-0 text-slate-400 hover:text-rose-600",
                    deletingSessionId === session.id && "opacity-60",
                    "opacity-100 md:opacity-0 md:group-hover:opacity-100",
                  )}
                  disabled={deletingSessionId === session.id}
                  onClick={() => {
                    void deleteSession(session.id)
                  }}
                  aria-label="删除会话"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))
          )}
        </div>
      </aside>

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
        <div className="flex min-w-0 items-start justify-between border-b border-slate-200/70 bg-white/70 px-6 py-4 backdrop-blur">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold tracking-tight text-slate-950">
              {displaySessionTitle(activeSession?.title)}
            </h2>
            <p className="mt-1 truncate text-sm text-slate-500">
              {activeSession?.active_topic ||
                "先提问，系统会在需要时自动检索知识库并在末尾展示来源。"}
            </p>
          </div>
          <div className="hidden flex-wrap items-center gap-2 text-xs text-slate-500 md:flex">
            <span className="rounded-full bg-slate-100 px-2 py-1">
              {knowledgeBaseLabel}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-1">
              {useRerank ? "重排开启" : "重排关闭"}
            </span>
          </div>
        </div>

        {error ? (
          <div className="border-b border-rose-200 bg-rose-50 px-6 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        <div
          ref={scrollRef}
          className="min-h-0 min-w-0 flex-1 overflow-y-auto px-6 py-6"
        >
          {loadingMessages ? (
            <div className="py-2 text-sm text-slate-500">正在加载消息...</div>
          ) : messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-4 text-center">
              <div className="inline-flex size-12 items-center justify-center rounded-full bg-slate-100 text-slate-700">
                <Bot className="h-6 w-6" />
              </div>
              <h3 className="mt-4 text-xl font-semibold text-slate-950">
                AI 小助手已就绪
              </h3>
              <div className="mt-4 max-w-2xl space-y-2 text-sm leading-7 text-slate-600">
                <p className="text-base font-medium text-slate-900">
                  {WELCOME_TITLE}
                </p>
                <p>{WELCOME_BODY}</p>
                <p className="text-slate-500">{WELCOME_HINT}</p>
              </div>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600">
                你可以直接问政策、公告、资格条件、考试安排，也可以上传图片或
                PDF。 普通问题会直接回答，政策问题会先检索后在末尾展示知识来源。
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {presetQuestions.map((question) => (
                  <Button
                    key={question}
                    type="button"
                    variant="outline"
                    className="rounded-full border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      void handleQuickAsk(question)
                    }}
                    disabled={sending}
                  >
                    <Sparkles className="mr-2 h-4 w-4" />
                    {question}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex w-full min-w-0 flex-col gap-6">
              {messages.map((message) => (
                <ChatMessageBubble
                  key={message.id}
                  message={message}
                  userLabel={currentUserLabel}
                  onSpeakMessage={(assistantMessage) => {
                    void speakAssistantMessage(assistantMessage, true)
                  }}
                />
              ))}
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-slate-200 bg-white/90 px-6 py-4 backdrop-blur">
          {loadingAttachments ? (
            <div className="mb-3 text-xs text-slate-500">正在加载附件...</div>
          ) : null}

          {attachments.length > 0 ? (
            <div className="mb-3 flex flex-wrap gap-2">
              {attachments.map((attachment) => (
                <span
                  key={attachment.id}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600"
                >
                  {attachment.attachment_type === "image" ? (
                    <ImageIcon className="h-3.5 w-3.5" />
                  ) : (
                    <FileText className="h-3.5 w-3.5" />
                  )}
                  {attachment.original_name}
                  <span className="text-slate-400">
                    {prettyFileSize(attachment.size_bytes)}
                  </span>
                  {attachment.metadata_json?.context_consumed ? (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                      已使用
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => {
                      void deleteAttachment(attachment.id)
                    }}
                    disabled={deletingAttachmentId === attachment.id}
                    className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-transparent text-slate-400 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label={`删除附件 ${attachment.original_name}`}
                    title="删除附件"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </span>
              ))}
            </div>
          ) : null}

          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            multiple
            onChange={(event) => {
              void handleFilesSelected(event)
            }}
          />

          <form className="space-y-3" onSubmit={handleSend}>
            <div className="rounded-3xl border border-slate-200 bg-white px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={handleUploadClick}
                  disabled={uploading}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs transition",
                    uploading
                      ? "cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                  )}
                >
                  <Upload className="h-3.5 w-3.5" />
                  {uploading ? "上传中..." : "上传文件"}
                </button>
                <button
                  type="button"
                  onClick={() => void toggleVoiceInput()}
                  disabled={!voiceInputSupported && !isListening}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs transition",
                    isListening
                      ? "border-amber-500 bg-amber-500 text-white"
                      : voiceInputSupported
                        ? "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                        : "cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400",
                  )}
                >
                  {isListening ? (
                    <MicOff className="h-3.5 w-3.5" />
                  ) : (
                    <Mic className="h-3.5 w-3.5" />
                  )}
                  {isListening
                    ? "停止听写"
                    : voiceInputSupported
                      ? "语音输入"
                      : "语音不可用"}
                </button>
                <button
                  type="button"
                  onClick={() => setAutoSpeak((current) => !current)}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs transition",
                    autoSpeak
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                  )}
                >
                  {autoSpeak ? (
                    <Volume2 className="h-3.5 w-3.5" />
                  ) : (
                    <VolumeX className="h-3.5 w-3.5" />
                  )}
                  {autoSpeak ? "自动播报开" : "自动播报关"}
                </button>
                <button
                  type="button"
                  onClick={() => setSettingsOpen((current) => !current)}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 transition hover:bg-slate-50"
                >
                  <ChevronDown
                    className={cn(
                      "h-3.5 w-3.5 transition-transform",
                      settingsOpen && "rotate-180",
                    )}
                  />
                  知识库设置
                </button>
                <div className="ml-auto text-[11px] text-slate-400">
                  {voiceStatus ||
                    (autoSpeak
                      ? "回答完成后自动播报"
                      : voiceInputSupported
                        ? "支持语音输入，回答可手动播报"
                        : "当前浏览器不支持语音输入")}
                </div>
              </div>

              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onPaste={handlePaste}
                rows={3}
                placeholder="直接输入政策问题，或者把图片、PDF、文件粘贴/上传上来。"
                className="mt-3 min-h-[104px] w-full resize-none border-0 bg-transparent p-0 pt-3 text-[15px] leading-7 text-slate-800 outline-none placeholder:text-slate-400"
              />

              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <label className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
                    <Checkbox
                      checked={evaluationEnabled}
                      onCheckedChange={(checked) =>
                        setEvaluationEnabled(checked === true)
                      }
                    />
                    评测分析
                  </label>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                    {knowledgeBaseLabel}
                  </span>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                    {useRerank ? "重排开启" : "重排关闭"}
                  </span>
                  {attachments.length > 0 ? (
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                      {attachments.length} 个附件
                    </span>
                  ) : null}
                </div>

                <Button
                  type="submit"
                  disabled={
                    sending ||
                    uploading ||
                    isListening ||
                    draft.trim().length === 0
                  }
                  className="rounded-full bg-slate-950 text-white hover:bg-slate-800"
                >
                  <Send className="mr-2 h-4 w-4" />
                  {sending ? "发送中..." : "发送"}
                </Button>
              </div>

              <div className="mt-2 text-[11px] leading-5 text-slate-400">
                {voiceStatus ||
                  "语音输入内容会自动写入输入框，回答发送后可自动播报。"}
              </div>
            </div>
          </form>
        </div>
      </main>
    </div>
  )
}

function ChatMessageBubble({
  message,
  userLabel,
  onSpeakMessage,
}: {
  message: ChatMessage
  userLabel: string
  onSpeakMessage?: (message: ChatMessage) => void
}) {
  const isUser = message.role === "user"
  const reasoningContent = getReasoningContent(message.metadata_json)
  const streamState = getStreamState(message.metadata_json)
  const isStreamingMessage =
    !isUser &&
    isRecord(message.metadata_json) &&
    message.metadata_json.streaming === true
  const streamElapsedLabel = getStreamElapsedLabel(message, streamState)
  const canShowStreamDetails = !isUser && Boolean(streamState?.stages.length)
  const canShowHarnessTimeline =
    !isUser && (message.retrieval_trace.length > 0 || isStreamingMessage)
  const shouldOpenHarness =
    isStreamingMessage && message.content.trim().length === 0
  const canShowReasoning = !isUser && reasoningContent.trim().length > 0

  if (isUser) {
    return (
      <div className="flex w-full min-w-0 justify-end">
        <div className="max-w-[78%] min-w-0 text-right">
          <div className="mb-1 flex flex-wrap justify-end gap-2 text-[12px] text-slate-400">
            <span className="font-medium text-slate-600">{userLabel}</span>
            {message.intent ? (
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                {formatIntentLabel(message.intent)}
              </span>
            ) : null}
            {message.historical_reference ? (
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                历史参考
              </span>
            ) : null}
          </div>
          <div className="whitespace-pre-wrap break-words text-[15px] leading-8 text-slate-900">
            {message.content}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-w-0 justify-start">
      <div className="flex min-w-0 max-w-[80%] flex-col items-start text-left">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[12px] text-slate-400">
          <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-1 font-medium text-slate-700">
            {_ASSISTANT_NAME}
          </span>
          {message.intent ? (
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
              {formatIntentLabel(message.intent)}
            </span>
          ) : null}
          {message.historical_reference ? (
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
              历史参考
            </span>
          ) : null}
          {onSpeakMessage ? (
            <button
              type="button"
              onClick={() => onSpeakMessage(message)}
              className="ml-auto inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 transition hover:bg-slate-50"
              aria-label="播放这条回答"
              title="播放这条回答"
            >
              <Volume2 className="h-3 w-3" />
              播放
            </button>
          ) : null}
        </div>

        <div className="whitespace-pre-wrap break-words text-[15px] leading-8 text-slate-900">
          {message.content}
        </div>

        {canShowReasoning ? (
          <details className="group mt-3 w-full max-w-full text-left">
            <summary className="flex list-none items-center gap-2 text-xs text-slate-400 [&::-webkit-details-marker]:hidden">
              <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-1">
                推理过程
              </span>
              <ChevronDown className="h-3.5 w-3.5 transition group-open:rotate-180" />
            </summary>
            <div className="mt-2 max-w-full border-l-2 border-amber-200 pl-3">
              <pre className="whitespace-pre-wrap break-words text-[12px] leading-6 text-slate-700">
                {reasoningContent}
              </pre>
            </div>
          </details>
        ) : null}

        {canShowStreamDetails ? (
          <details className="group mt-3 w-full max-w-full text-left">
            <summary className="flex list-none items-center gap-2 text-xs text-slate-400 [&::-webkit-details-marker]:hidden">
              <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-2 py-1">
                已处理 {streamElapsedLabel}
              </span>
              <ChevronDown className="h-3.5 w-3.5 transition group-open:rotate-180" />
            </summary>
            <div className="mt-2 max-h-56 max-w-full overflow-auto border-l-2 border-slate-200 pl-3">
              <div className="space-y-2">
                {streamState?.stages.map((stage) => (
                  <div
                    key={`${message.id}-${stage.step}`}
                    className="max-w-full text-xs text-slate-600"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-slate-800">
                        {stage.label}
                      </div>
                      <div
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[11px]",
                          stage.status === "done"
                            ? "bg-emerald-50 text-emerald-700"
                            : stage.status === "error"
                              ? "bg-rose-50 text-rose-700"
                              : "bg-amber-50 text-amber-700",
                        )}
                      >
                        {stage.status === "done"
                          ? "已完成"
                          : stage.status === "error"
                            ? "失败"
                            : "进行中"}
                      </div>
                    </div>
                    <div className="mt-1 text-slate-500">{stage.detail}</div>
                    <div className="mt-1 text-[11px] text-slate-400">
                      {stage.elapsed_ms != null
                        ? `耗时 ${formatElapsedMs(stage.elapsed_ms)}`
                        : null}
                      {stage.total_elapsed_ms != null
                        ? ` · 总耗时 ${formatElapsedMs(stage.total_elapsed_ms)}`
                        : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </details>
        ) : null}

        {canShowHarnessTimeline ? (
          <AgentHarnessTimeline
            events={message.retrieval_trace}
            messageId={message.id}
            autoOpen={shouldOpenHarness}
          />
        ) : null}

        {!isUser && message.citations.length > 0 ? (
          <div className="mt-3 w-full max-w-full text-left">
            <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-slate-400">
              来源
            </div>
            <div className="flex flex-wrap gap-2">
              {message.citations.map((citation, index) => (
                <details
                  key={`${message.id}-citation-${index}`}
                  className="group"
                >
                  <summary className="flex list-none items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600 transition hover:bg-white [&::-webkit-details-marker]:hidden">
                    <span className="inline-flex size-5 items-center justify-center rounded-full bg-slate-900 text-[11px] font-medium text-white">
                      {index + 1}
                    </span>
                    <span className="max-w-[220px] truncate">
                      {buildCitationTitle(citation)}
                    </span>
                    <ChevronDown className="h-3.5 w-3.5 text-slate-400 transition group-open:rotate-180" />
                  </summary>
                  <div className="mt-2 max-w-[520px] text-xs leading-6 text-slate-600">
                    <div className="text-slate-700">
                      {citation.source_file ||
                        citation.original_name ||
                        "未命名来源"}
                    </div>
                    <div className="mt-1 text-[11px] text-slate-400">
                      {_buildCitationSubtitle(citation)}
                    </div>
                    {citation.section ? (
                      <div className="mt-1">章节：{citation.section}</div>
                    ) : null}
                    {citation.page_start != null ||
                    citation.page_end != null ? (
                      <div className="mt-1">
                        页码：{citation.page_start ?? "?"}-
                        {citation.page_end ?? "?"}
                      </div>
                    ) : null}
                    <div className="mt-2 border-l-2 border-slate-200 pl-3 text-[11px] leading-5 text-slate-500">
                      {citation.content_excerpt ||
                        citation.summary ||
                        citation.content ||
                        "没有可显示的摘要"}
                    </div>
                  </div>
                </details>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function AgentHarnessTimeline({
  events,
  messageId,
  autoOpen,
}: {
  events: Record<string, unknown>[]
  messageId: string
  autoOpen?: boolean
}) {
  const visibleEvents = events.filter((event) => isRecord(event))
  const todos = getLatestTodos(visibleEvents)
  const toolCount = visibleEvents.filter((event) =>
    ["ToolUse", "PostToolUse", "PreToolUse"].includes(getTraceEventName(event)),
  ).length
  const permissionCount = visibleEvents.filter(
    (event) => getTraceEventName(event) === "Permission",
  ).length
  const skillCount = visibleEvents.filter(
    (event) => getTraceEventName(event) === "SkillLoaded",
  ).length

  return (
    <details
      key={`${messageId}-${autoOpen ? "live" : "folded"}`}
      open={autoOpen || undefined}
      className="group mt-3 w-full max-w-full text-left"
    >
      <summary className="flex list-none items-center gap-2 text-xs text-slate-400 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-2.5 py-1 font-mono text-[11px] text-slate-600">
            <Activity className="h-3.5 w-3.5 text-slate-400" />
            {autoOpen
              ? "Agent running"
              : `${visibleEvents.length} hooks · ${toolCount} tools · ${permissionCount} gates · ${skillCount} skills`}
          </span>
        </div>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400 transition group-open:rotate-180" />
      </summary>
      <div className="mt-2 max-h-[360px] overflow-auto border-l-2 border-slate-200 pl-3 font-mono">
        {todos.length > 0 ? <HarnessTodoList todos={todos} /> : null}
        {visibleEvents.length > 0 ? (
          <div className="space-y-1.5">
            {visibleEvents.map((event, index) => (
              <HarnessLogLine
                key={`${messageId}-harness-${getTraceId(event, index)}`}
                event={event}
                index={index}
              />
            ))}
          </div>
        ) : (
          <div className="px-2 py-2 text-xs text-slate-400">
            正在等待第一条 Agent 运行日志...
          </div>
        )}
      </div>
    </details>
  )
}

function HarnessTodoList({ todos }: { todos: AgentTodo[] }) {
  return (
    <div className="mb-3 px-2 py-2">
      <div className="mb-2 text-[13px] font-bold text-slate-700">
        ## Current Tasks
      </div>
      <div className="space-y-1">
        {todos.map((todo, index) => (
          <div
            key={`${todo.content}-${index}`}
            className="grid grid-cols-[24px_minmax(0,1fr)] gap-2 text-[13px] leading-5"
          >
            <span
              className={cn(
                "text-center font-bold",
                todo.status === "completed"
                  ? "text-emerald-600"
                  : todo.status === "in_progress"
                    ? "text-amber-600"
                    : "text-slate-300",
              )}
            >
              {formatTodoStatusIcon(todo.status)}
            </span>
            <span
              className={cn(
                "break-words",
                todo.status === "completed"
                  ? "text-slate-400 line-through decoration-slate-300"
                  : "text-slate-700",
              )}
            >
              {todo.content}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function HarnessLogLine({
  event,
  index,
}: {
  event: Record<string, unknown>
  index: number
}) {
  const status = getTraceStatus(event)
  const display = getHookDisplay(event)
  const label = display.label
  const rawLabel = display.rawLabel
  const detail = display.detail
  const inputSummary = summarizeTracePayload(event.input)
  const outputSummary = summarizeTracePayload(event.output)
  const elapsed =
    typeof event.elapsed_ms === "number"
      ? formatElapsedMs(event.elapsed_ms)
      : ""
  const compactDetail = detail || outputSummary || inputSummary

  return (
    <div className="min-w-0 rounded-md px-2 py-1.5 text-[13px] leading-5 transition hover:bg-slate-50">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className="shrink-0 font-bold text-slate-500">[HOOK]</span>
        <span className="break-all font-semibold text-slate-800">{label}</span>
        {rawLabel ? (
          <span className="font-mono text-[11px] text-slate-400">
            {rawLabel}
          </span>
        ) : null}
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px]",
            getHookStatusClass(status),
          )}
        >
          {formatTraceStatus(status)}
        </span>
        <span className="text-[11px] text-slate-300">#{index + 1}</span>
        {elapsed ? (
          <span className="text-[11px] text-slate-300">{elapsed}</span>
        ) : null}
      </div>
      {compactDetail ? (
        <div className="mt-1 break-words pl-[54px] text-[12px] text-slate-500">
          {compactDetail}
        </div>
      ) : null}
    </div>
  )
}

function getHookDisplay(event: Record<string, unknown>): {
  label: string
  rawLabel: string
  detail: string
} {
  const eventName = getTraceEventName(event)
  const tool = typeof event.tool === "string" ? event.tool : ""
  const step = typeof event.step === "string" ? event.step : ""
  const status = getTraceStatus(event)
  const rawLabel = tool || step || eventName
  const outputSummary = summarizeTracePayload(event.output)
  const errorDetail = status === "error" && outputSummary ? outputSummary : ""

  if (eventName === "SubAgentStart") {
    return {
      label: "子 Agent 启动",
      rawLabel,
      detail:
        getTraceDetail(event) ||
        summarizeTracePayload(event.input) ||
        "Agent 正在启动一个子任务执行器。",
    }
  }
  if (eventName === "SubAgentEnd") {
    return {
      label: status === "error" ? "子 Agent 失败" : "子 Agent 完成",
      rawLabel,
      detail:
        errorDetail ||
        getTraceDetail(event) ||
        summarizeTracePayload(event.output) ||
        "子 Agent 已结束执行。",
    }
  }
  if (eventName === "SubAgentToolUse") {
    return {
      label: "子 Agent 步骤",
      rawLabel,
      detail:
        errorDetail ||
        getTraceDetail(event) ||
        summarizeTracePayload(event.output) ||
        "子 Agent 正在执行内部步骤。",
    }
  }

  const toolDisplay = getToolDisplay(tool || step)
  if (toolDisplay) {
    const phaseDetail = getStepDetail(step, status)
    return {
      label: toolDisplay.label,
      rawLabel,
      detail:
        errorDetail ||
        phaseDetail ||
        getTraceDetail(event) ||
        toolDisplay.detail,
    }
  }

  const eventDisplay = getEventDisplay(eventName, step, status)
  return {
    label: eventDisplay.label,
    rawLabel: rawLabel === eventDisplay.label ? "" : rawLabel,
    detail: errorDetail || getTraceDetail(event) || eventDisplay.detail,
  }
}

function getToolDisplay(
  name: string,
): { label: string; detail: string } | null {
  const labels: Record<string, { label: string; detail: string }> = {
    todo_write: {
      label: "更新任务清单",
      detail: "Agent 正在规划或更新当前要完成的步骤。",
    },
    load_skill: {
      label: "加载技能说明",
      detail: "Agent 正在读取某个技能的使用规则，用来指导后续工具调用。",
    },
    search_policy_knowledge: {
      label: "检索政策知识库",
      detail: "Agent 正在从向量库和关键词候选中查找可引用的政策依据。",
    },
    compose_policy_answer: {
      label: "生成政策回答",
      detail: "Agent 正在基于检索到的证据组织最终回答。",
    },
    search_positions_pg: {
      label: "筛选岗位表",
      detail: "Agent 正在用 PostgreSQL 的结构化字段筛选公务员岗位。",
    },
    review_position_risks: {
      label: "审查岗位风险",
      detail: "Agent 正在检查岗位条件、专业限制、地区和报考风险。",
    },
    generate_study_plan: {
      label: "生成备考计划",
      detail: "Agent 正在根据用户情况和目标岗位安排复习计划。",
    },
    compose_final_report: {
      label: "整理最终报告",
      detail: "Agent 正在把岗位、风险、依据和备考建议汇总成最终回答。",
    },
  }
  return labels[name] || null
}

function getEventDisplay(
  eventName: string,
  step: string,
  status: string,
): { label: string; detail: string } {
  if (eventName === "UserPromptSubmit") {
    return {
      label: "收到用户问题",
      detail: "系统已接收你的问题，并开始进入 Agent 执行循环。",
    }
  }
  if (eventName === "LLMStart") {
    return {
      label: "模型思考下一步",
      detail: "模型正在判断是否需要列计划、调用工具、继续检索或直接回答。",
    }
  }
  if (eventName === "LLMStop") {
    return {
      label: "模型返回决策",
      detail: "模型已经决定本轮要做什么，可能是调用工具，也可能是输出回答。",
    }
  }
  if (eventName === "PreToolUse") {
    return {
      label: "准备调用工具",
      detail: "系统正在整理工具参数，并准备进入权限检查。",
    }
  }
  if (eventName === "Permission") {
    return {
      label: "权限检查",
      detail:
        status === "allow"
          ? "该工具是允许执行的项目内工具，已放行。"
          : "系统正在判断这个工具调用是否允许执行。",
    }
  }
  if (eventName === "ToolUse") {
    return {
      label: "执行工具",
      detail: "工具已经开始运行，后续会返回执行结果。",
    }
  }
  if (eventName === "PostToolUse") {
    return {
      label: status === "error" ? "工具执行失败" : "工具执行完成",
      detail:
        status === "error"
          ? "工具执行时出现错误，Agent 会根据错误尝试恢复或换路径。"
          : "工具已返回结果，Agent 会把结果交给模型继续判断。",
    }
  }
  if (eventName === "RetrievalStep") {
    return {
      label: formatStepLabel(step),
      detail: getStepDetail(step, status),
    }
  }
  if (eventName === "Stop") {
    return {
      label: "Agent 停止",
      detail: "本轮 Agent 已完成工具调用，准备输出最终回答。",
    }
  }
  return {
    label: formatTraceEventLabel(eventName),
    detail: "Agent 正在处理这一内部步骤。",
  }
}

function getStepDetail(step: string, status: string): string {
  const verb =
    status === "done" ? "已完成" : status === "error" ? "失败" : "正在"
  const details: Record<string, string> = {
    rewrite_queries:
      status === "done"
        ? "已把原问题改写成更适合知识库检索的查询。"
        : `${verb}改写检索问题。`,
    retrieve:
      status === "done"
        ? "已完成向量检索和关键词候选检索。"
        : `${verb}检索向量库和关键词候选。`,
    fuse_and_rerank:
      status === "done"
        ? "已完成候选证据融合和重排序。"
        : `${verb}对检索结果做融合和重排序。`,
    react_evidence_review:
      status === "done"
        ? "已检查证据是否足够支撑回答。"
        : `${verb}检查证据是否足够。`,
    agent_loop:
      status === "done" ? "模型已完成本轮判断。" : "模型正在判断下一步行动。",
  }
  return details[step] || ""
}

function formatStepLabel(step: string): string {
  const labels: Record<string, string> = {
    rewrite_queries: "改写检索问题",
    retrieve: "检索候选证据",
    fuse_and_rerank: "证据融合排序",
    react_evidence_review: "检查证据充分性",
    agent_loop: "Agent 决策循环",
  }
  return labels[step] || step || "内部步骤"
}

function getTraceId(event: Record<string, unknown>, index: number): string {
  return typeof event.id === "string" && event.id ? event.id : String(index)
}

function getLatestTodos(events: Record<string, unknown>[]): AgentTodo[] {
  let latest: AgentTodo[] = []
  for (const event of events) {
    const tool = typeof event.tool === "string" ? event.tool : ""
    const step = typeof event.step === "string" ? event.step : ""
    if (
      tool !== "todo_write" &&
      tool !== "todo_tasks" &&
      step !== "todo_write" &&
      step !== "todo_tasks"
    ) {
      continue
    }
    const outputTodos = extractTodosFromPayload(event.output)
    const inputTodos = extractTodosFromPayload(event.input)
    const todos = outputTodos.length > 0 ? outputTodos : inputTodos
    if (todos.length > 0) {
      latest = todos
    }
  }
  return latest
}

function extractTodosFromPayload(value: unknown): AgentTodo[] {
  if (!isRecord(value)) {
    if (!Array.isArray(value)) {
      return []
    }
    return value
      .map((item) => normalizeTodoItem(item))
      .filter((item): item is AgentTodo => item !== null)
  }

  const directTodos = Array.isArray(value.todos) ? value.todos : null
  const contractTodos =
    isRecord(value.task_contract) && Array.isArray(value.task_contract.todos)
      ? value.task_contract.todos
      : null
  const todos = directTodos ?? contractTodos
  if (!todos) {
    return []
  }
  return todos
    .map((item) => {
      return normalizeTodoItem(item)
    })
    .filter((item): item is AgentTodo => item !== null)
}

function normalizeTodoItem(value: unknown): AgentTodo | null {
  if (!isRecord(value)) {
    return null
  }
  const content =
    typeof value.content === "string" ? value.content.trim() : ""
  const status =
    value.status === "completed" ||
    value.status === "in_progress" ||
    value.status === "pending"
      ? value.status
      : "pending"
  if (!content) {
    return null
  }
  return { content, status }
}

function formatTodoStatusIcon(status: AgentTodo["status"]): string {
  if (status === "completed") {
    return "✓"
  }
  if (status === "in_progress") {
    return "▸"
  }
  return " "
}

function getHookStatusClass(status: string): string {
  if (status === "error" || status === "deny" || status === "denied") {
    return "bg-rose-50 text-rose-700"
  }
  if (status === "running") {
    return "bg-amber-50 text-amber-700"
  }
  if (status === "allow" || status === "done") {
    return "bg-emerald-50 text-emerald-700"
  }
  return "bg-slate-100 text-slate-600"
}

function getTraceEventName(event: Record<string, unknown>): string {
  if (typeof event.event === "string" && event.event) {
    return event.event
  }
  if (typeof event.step === "string" && event.step) {
    return event.step
  }
  return "TraceEvent"
}

function getTraceStatus(event: Record<string, unknown>): string {
  return typeof event.status === "string" && event.status
    ? event.status
    : typeof event.stage === "string" && event.stage
      ? event.stage
      : "done"
}

function getTraceDetail(event: Record<string, unknown>): string {
  if (typeof event.detail === "string") {
    return event.detail
  }
  if (typeof event.action === "string") {
    return event.action
  }
  return ""
}

function formatTraceStatus(status: string): string {
  const labels: Record<string, string> = {
    running: "运行中",
    done: "完成",
    error: "失败",
    allow: "允许",
    deny: "拒绝",
    denied: "已拦截",
  }
  return labels[status] || status
}

function formatTraceEventLabel(eventName: string): string {
  const labels: Record<string, string> = {
    UserPromptSubmit: "用户请求",
    LLMStart: "模型思考",
    LLMStop: "模型返回",
    PreToolUse: "工具准备",
    Permission: "权限门",
    ToolUse: "工具调用",
    PostToolUse: "工具结果",
    SkillLoaded: "技能加载",
    Compact: "上下文压缩",
    Memory: "记忆事件",
    Stop: "停止",
    Fallback: "降级流程",
  }
  return labels[eventName] || eventName
}

function summarizeTracePayload(value: unknown): string {
  if (!isRecord(value)) {
    return ""
  }
  const errorText =
    typeof value.error === "string" && value.error.trim()
      ? value.error.trim()
      : ""
  const errorType =
    typeof value.error_type === "string" && value.error_type.trim()
      ? value.error_type.trim()
      : ""
  if (errorText || errorType) {
    return [errorType, errorText].filter(Boolean).join(": ")
  }
  const entries = Object.entries(value).filter(([, item]) => item != null)
  if (entries.length === 0) {
    return ""
  }
  return entries
    .slice(0, 6)
    .map(([key, item]) => `${key}: ${summarizeTraceValue(item)}`)
    .join(" · ")
}

function summarizeTraceValue(value: unknown): string {
  if (typeof value === "string") {
    return value.length > 140 ? `${value.slice(0, 140)}...` : value
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  if (Array.isArray(value)) {
    return `${value.length} 项`
  }
  if (isRecord(value)) {
    const keys = Object.keys(value)
    return keys.length ? `{${keys.slice(0, 4).join(", ")}}` : "{}"
  }
  return String(value)
}

function parseSseFrame(frame: string): SseEvent | null {
  const lines = frame.split(/\r?\n/)
  let event = "message"
  const dataLines: string[] = []
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim()
      continue
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  if (dataLines.length === 0) {
    return null
  }
  const dataText = dataLines.join("\n")
  try {
    return {
      event,
      data: JSON.parse(dataText),
    }
  } catch {
    return {
      event,
      data: dataText,
    }
  }
}

function extractDelta(data: unknown): string {
  if (!data || typeof data !== "object") {
    return ""
  }
  const payload = data as { delta?: unknown }
  return typeof payload.delta === "string" ? payload.delta : ""
}

function extractTrace(data: unknown): Record<string, unknown> | null {
  if (!data || typeof data !== "object") {
    return null
  }
  const payload = data as { trace?: unknown }
  return payload.trace && typeof payload.trace === "object"
    ? (payload.trace as Record<string, unknown>)
    : null
}

function extractCitations(data: unknown): ChatCitation[] {
  if (!data || typeof data !== "object") {
    return []
  }
  const payload = data as { citations?: unknown }
  if (!Array.isArray(payload.citations)) {
    return []
  }
  return payload.citations.filter((item): item is ChatCitation =>
    Boolean(item && typeof item === "object"),
  )
}

function extractReport(data: unknown): string {
  if (!data || typeof data !== "object") {
    return ""
  }
  const payload = data as { report?: unknown }
  return typeof payload.report === "string" ? payload.report : ""
}

function extractStage(data: unknown): StreamStage | null {
  if (!data || typeof data !== "object") {
    return null
  }
  const payload = data as {
    step?: unknown
    label?: unknown
    status?: unknown
    detail?: unknown
    elapsed_ms?: unknown
    total_elapsed_ms?: unknown
  }
  if (
    typeof payload.step !== "string" ||
    typeof payload.label !== "string" ||
    typeof payload.status !== "string"
  ) {
    return null
  }
  const status = payload.status
  if (status !== "running" && status !== "done" && status !== "error") {
    return null
  }
  return {
    step: payload.step,
    label: payload.label,
    status,
    detail: typeof payload.detail === "string" ? payload.detail : undefined,
    elapsed_ms:
      typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : undefined,
    total_elapsed_ms:
      typeof payload.total_elapsed_ms === "number"
        ? payload.total_elapsed_ms
        : undefined,
  }
}

function extractErrorDetail(data: unknown): string {
  if (!data || typeof data !== "object") {
    return ""
  }
  const payload = data as { detail?: unknown }
  return typeof payload.detail === "string" ? payload.detail : ""
}

function extractErrorStage(data: unknown): string {
  if (!data || typeof data !== "object") {
    return ""
  }
  const payload = data as { stage?: unknown }
  return typeof payload.stage === "string" ? payload.stage : ""
}

function mergeStageIntoMessage(
  message: ChatMessage,
  stage: StreamStage,
): ChatMessage {
  const metadata = isRecord(message.metadata_json) ? message.metadata_json : {}
  const streamState = getStreamState(metadata)
  const stages = [...(streamState?.stages ?? [])]
  const existingIndex = stages.findIndex((item) => item.step === stage.step)
  if (existingIndex >= 0) {
    stages[existingIndex] = {
      ...stages[existingIndex],
      ...stage,
    }
  } else {
    stages.push(stage)
  }

  const startedAt =
    streamState?.started_at || message.created_at || new Date().toISOString()
  return {
    ...message,
    metadata_json: {
      ...metadata,
      streaming: true,
      stream_state: {
        started_at: startedAt,
        stages,
        total_elapsed_ms:
          stage.total_elapsed_ms ?? streamState?.total_elapsed_ms ?? undefined,
      },
    },
  }
}

function getStreamState(
  metadata_json: Record<string, unknown>,
): StreamState | null {
  const streamState = metadata_json.stream_state
  if (!isRecord(streamState)) {
    return null
  }
  const startedAt =
    typeof streamState.started_at === "string" ? streamState.started_at : null
  const stagesRaw = Array.isArray(streamState.stages) ? streamState.stages : []
  const stages = stagesRaw
    .map((item) => {
      if (!isRecord(item)) {
        return null
      }
      const step = typeof item.step === "string" ? item.step : null
      const label = typeof item.label === "string" ? item.label : null
      const status =
        item.status === "running" ||
        item.status === "done" ||
        item.status === "error"
          ? item.status
          : null
      if (!step || !label || !status) {
        return null
      }
      return {
        step,
        label,
        status,
        detail: typeof item.detail === "string" ? item.detail : undefined,
        elapsed_ms:
          typeof item.elapsed_ms === "number" ? item.elapsed_ms : undefined,
        total_elapsed_ms:
          typeof item.total_elapsed_ms === "number"
            ? item.total_elapsed_ms
            : undefined,
      } as StreamStage
    })
    .filter((item): item is StreamStage => item !== null)

  if (!startedAt && stages.length === 0) {
    return null
  }
  return {
    started_at: startedAt || new Date().toISOString(),
    stages,
    total_elapsed_ms:
      typeof streamState.total_elapsed_ms === "number"
        ? streamState.total_elapsed_ms
        : undefined,
  }
}

function getReasoningContent(metadata_json: Record<string, unknown>): string {
  const value = metadata_json.reasoning_content
  return typeof value === "string" ? value : ""
}

function getStreamElapsedLabel(
  message: ChatMessage,
  streamState: StreamState | null,
): string {
  if (streamState?.total_elapsed_ms != null) {
    return formatElapsedMs(streamState.total_elapsed_ms)
  }
  if (!message.created_at) {
    return "0s"
  }
  const started = new Date(message.created_at).getTime()
  if (Number.isNaN(started)) {
    return "0s"
  }
  return formatElapsedMs(Math.max(0, Date.now() - started))
}

function formatElapsedMs(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "0s"
  }
  if (value < 1000) {
    return `${Math.max(1, Math.round(value / 100)) / 10}s`
  }
  const seconds = value / 1000
  return `${seconds >= 10 ? seconds.toFixed(0) : seconds.toFixed(1)}s`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function formatIntentLabel(intent?: string | null): string {
  if (!intent) {
    return "未知"
  }
  const labels: Record<string, string> = {
    position_recommendation: "结构化分析",
    route_intent: "意图识别",
    technical_qa: "技术问答",
    exam_affairs_qa: "考务问答",
    policy_qa: "政策问答",
    policy_rag: "政策检索",
    general_chat: "普通对话",
    unknown: "未知",
  }
  return labels[intent] || intent
}

function formatStreamStageLabel(stage: string): string {
  const labels: Record<string, string> = {
    init: "初始化",
    route_intent: "意图识别",
    rewrite_queries: "问题改写",
    retrieve: "知识检索",
    fuse_and_rerank: "融合重排",
    position_recommendation: "结构化分析",
    react_evidence_review: "证据复核",
    risk_review: "风险审查",
    report_generation: "报告生成",
    autonomous_agent: "自主 Agent",
    direct_answer: "直接回答",
    answer: "答案生成",
    finalize: "会话收尾",
  }
  return labels[stage] || stage
}

function buildPresetQuestions(seed: string): string[] {
  const pool = [...PRESET_QUESTION_POOL]
  const rng = seededRandom(seed)
  for (let index = pool.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(rng() * (index + 1))
    ;[pool[index], pool[swapIndex]] = [pool[swapIndex], pool[index]]
  }
  return pool.slice(0, 4)
}

function seededRandom(seed: string): () => number {
  let hash = 2166136261
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return () => {
    hash += 0x6d2b79f5
    let t = hash
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function prettyFileSize(sizeBytes: number): string {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) {
    return "未知大小"
  }
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`
}

function _buildCitationSubtitle(citation: ChatCitation): string {
  const parts: string[] = []
  if (citation.source_file) {
    parts.push(citation.source_file)
  }
  if (citation.section) {
    parts.push(`章节：${citation.section}`)
  }
  if (citation.page_start != null || citation.page_end != null) {
    parts.push(
      `页码：${citation.page_start ?? "?"}-${citation.page_end ?? "?"}`,
    )
  }
  if (citation.content_excerpt) {
    parts.push(citation.content_excerpt)
  } else if (citation.summary) {
    parts.push(citation.summary)
  }
  return parts.join(" · ")
}

function buildCitationTitle(citation: ChatCitation): string {
  return (
    citation.doc_title ||
    citation.original_name ||
    citation.source_file ||
    "未命名来源"
  )
}

function displaySessionTitle(title?: string | null): string {
  const normalized = (title || "").trim()
  if (!normalized || normalized === DEFAULT_SESSION_TITLE) {
    return DEFAULT_SESSION_TITLE
  }
  return normalized
}

function isMissingSessionError(message: string): boolean {
  return message.includes("Chat session not found")
}
