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
  ShieldAlert,
  Sparkles,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
  Workflow,
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

type AgentMilestone = {
  key: string
  label: string
  detail: string
  tone: "neutral" | "success" | "warning"
}

type ChatRequestMode = "policy_rag" | "position_recommendation"

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
      await submitQuery(query)
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
  const riskReview = getRiskReview(message.metadata_json)
  const reportText = getReportText(message.metadata_json)
  const agentMilestones = buildAgentMilestones(message.retrieval_trace).filter(
    (milestone) => milestone.key !== "position_recommendation",
  )
  const streamElapsedLabel = getStreamElapsedLabel(message, streamState)
  const canShowStreamDetails = !isUser && Boolean(streamState?.stages.length)
  const canShowReasoning = !isUser && reasoningContent.trim().length > 0
  const hasRiskReviewContent =
    Boolean(riskReview?.need_manual_confirm) ||
    Boolean(riskReview?.risk_level) ||
    (riskReview?.risk_items?.length ?? 0) > 0
  const canShowAgentPanel =
    !isUser &&
    (hasRiskReviewContent ||
      reportText.trim().length > 0 ||
      agentMilestones.length > 0)

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

        {canShowAgentPanel ? (
          <AgentExecutionPanel
            messageId={message.id}
            riskReview={riskReview}
            reportText={reportText}
            milestones={agentMilestones}
          />
        ) : null}

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
              {message.retrieval_trace.length > 0 ? (
                <details className="mt-3 max-w-full">
                  <summary className="cursor-pointer text-[11px] text-slate-500">
                    检索轨迹
                  </summary>
                  <pre className="mt-2 max-h-56 max-w-full overflow-auto whitespace-pre-wrap border-l-2 border-slate-200 pl-3 text-[11px] leading-5 text-slate-500">
                    {JSON.stringify(message.retrieval_trace, null, 2)}
                  </pre>
                </details>
              ) : null}
            </div>
          </details>
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

        {!isUser && message.retrieval_trace.length > 0 ? (
          <details className="mt-3 w-full max-w-full text-left text-xs text-slate-500">
            <summary className="cursor-pointer select-none text-slate-500">
              检索过程
            </summary>
            <pre className="mt-2 max-w-full overflow-auto whitespace-pre-wrap rounded-2xl border border-slate-200 bg-slate-50 p-3 text-[11px] leading-5 text-slate-500">
              {JSON.stringify(message.retrieval_trace, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  )
}

function AgentExecutionPanel({
  messageId,
  riskReview,
  reportText,
  milestones,
}: {
  messageId: string
  riskReview: AgentRiskReview | null
  reportText: string
  milestones: AgentMilestone[]
}) {
  const riskItems = riskReview?.risk_items ?? []
  const riskLevel = riskReview?.risk_level || "unknown"
  const riskItemCount = riskItems.length
  const needManualConfirm = Boolean(riskReview?.need_manual_confirm)
  const reportPreview = buildReportPreview(reportText, 10)
  const hasReport = reportText.trim().length > 0

  return (
    <details className="relative mt-4 w-full overflow-hidden rounded-[28px] border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-white shadow-[0_20px_60px_rgba(15,23,42,0.18)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-4 sm:px-5 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.22em] text-cyan-100">
              <Workflow className="h-3.5 w-3.5" />
              实际链路
            </span>
            <span className="rounded-full bg-cyan-400/15 px-3 py-1 text-[11px] font-medium text-cyan-100">
              检索
            </span>
            <span className="rounded-full bg-amber-400/15 px-3 py-1 text-[11px] font-medium text-amber-100">
              风险审查
            </span>
            <span className="rounded-full bg-sky-400/15 px-3 py-1 text-[11px] font-medium text-sky-100">
              报告生成
            </span>
          </div>
          <h3 className="mt-3 text-base font-semibold tracking-tight text-white">
            政策问答 Agent 链路
          </h3>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-300">
            这里显示的是后端真实返回的检索轨迹、风险审查和报告内容。默认折叠，想看时再展开。
          </p>
        </div>
        <div className="shrink-0 text-xs text-slate-300">点击展开 / 收起</div>
      </summary>

      <div className="relative px-4 pb-4 sm:px-5">
        <div className="pointer-events-none absolute -right-12 -top-12 size-40 rounded-full bg-cyan-400/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-16 left-1/3 size-48 rounded-full bg-sky-400/10 blur-3xl" />

        <div className="mt-1 grid gap-3 sm:grid-cols-4">
          <MetricChip
            label="风险等级"
            value={formatRiskLevelLabel(riskLevel)}
          />
          <MetricChip
            label="风险项"
            value={riskItemCount > 0 ? String(riskItemCount) : "0"}
          />
          <MetricChip
            label="人工复核"
            value={needManualConfirm ? "需要" : "可跳过"}
          />
          <MetricChip label="报告" value={hasReport ? "已生成" : "未生成"} />
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
            <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-slate-300">
              <Activity className="h-3.5 w-3.5" />
              执行轨迹
            </div>
            <div className="grid gap-2">
              {milestones.length > 0 ? (
                milestones.map((milestone) => (
                  <div
                    key={`${messageId}-${milestone.key}`}
                    className="flex items-start gap-3 rounded-2xl border border-white/8 bg-slate-950/30 px-3 py-3"
                  >
                    <span
                      className={cn(
                        "mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                        milestone.tone === "success"
                          ? "bg-emerald-400/15 text-emerald-200"
                          : milestone.tone === "warning"
                            ? "bg-amber-400/15 text-amber-100"
                            : "bg-sky-400/15 text-sky-100",
                      )}
                    >
                      {milestone.key.slice(0, 1).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-white">
                          {milestone.label}
                        </span>
                        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-slate-300">
                          {milestone.key}
                        </span>
                      </div>
                      <div className="mt-1 text-sm leading-6 text-slate-300">
                        {milestone.detail}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-3 py-4 text-sm text-slate-400">
                  当前消息没有可展示的 Agent 轨迹。
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-3">
            <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
              <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-slate-300">
                <ShieldAlert className="h-3.5 w-3.5" />
                风险审查
              </div>
              {riskItems.length > 0 ? (
                <div className="space-y-2">
                  {riskItems.slice(0, 3).map((item, index) => (
                    <div
                      key={`${messageId}-risk-${index}`}
                      className="rounded-2xl border border-white/8 bg-slate-950/30 px-3 py-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-white">
                          {item.risk_type || `风险项 ${index + 1}`}
                        </span>
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-[10px] font-medium",
                            item.risk_level === "high"
                              ? "bg-rose-400/15 text-rose-100"
                              : item.risk_level === "medium"
                                ? "bg-amber-400/15 text-amber-100"
                                : "bg-emerald-400/15 text-emerald-100",
                          )}
                        >
                          {formatRiskLevelLabel(item.risk_level)}
                        </span>
                      </div>
                      <div className="mt-1 text-sm leading-6 text-slate-300">
                        {item.explanation || item.evidence || "需要进一步核验"}
                      </div>
                      {item.suggestion ? (
                        <div className="mt-2 rounded-2xl border border-white/8 bg-white/5 px-3 py-2 text-xs leading-5 text-slate-200">
                          建议：{item.suggestion}
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {riskItems.length > 3 ? (
                    <div className="text-xs text-slate-400">
                      还有 {riskItems.length - 3} 项风险未展开。
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-3 py-4 text-sm text-slate-400">
                  暂未识别到需要特别提示的风险。
                </div>
              )}
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/5 p-4">
              <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-slate-300">
                <FileText className="h-3.5 w-3.5" />
                报告预览
              </div>
              {hasReport ? (
                <details className="group">
                  <summary className="flex list-none cursor-pointer items-center justify-between gap-3 rounded-2xl border border-white/10 bg-slate-950/30 px-3 py-2 text-sm text-slate-200 [&::-webkit-details-marker]:hidden">
                    <span className="truncate">查看生成报告</span>
                    <ChevronDown className="h-4 w-4 shrink-0 transition group-open:rotate-180" />
                  </summary>
                  <div className="mt-3 rounded-2xl border border-white/10 bg-slate-950/30 p-3">
                    <pre className="whitespace-pre-wrap break-words text-[12px] leading-6 text-slate-200">
                      {reportPreview}
                    </pre>
                    {reportText.length > reportPreview.length ? (
                      <div className="mt-2 text-[11px] text-slate-400">
                        报告已截断显示，展开可在完整内容里查看。
                      </div>
                    ) : null}
                  </div>
                </details>
              ) : (
                <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-3 py-4 text-sm text-slate-400">
                  当前没有报告内容。
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </details>
  )
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

function getRiskReview(
  metadata_json: Record<string, unknown>,
): AgentRiskReview | null {
  const raw = metadata_json.risk_review
  if (!isRecord(raw)) {
    return null
  }
  return raw as AgentRiskReview
}

function getReportText(metadata_json: Record<string, unknown>): string {
  const value = metadata_json.report
  return typeof value === "string" ? value : ""
}

function buildAgentMilestones(
  retrievalTrace: Record<string, unknown>[],
): AgentMilestone[] {
  const milestones: AgentMilestone[] = []
  const seen = new Set<string>()
  for (const entry of retrievalTrace) {
    if (!isRecord(entry)) {
      continue
    }
    const step = typeof entry.step === "string" ? entry.step : ""
    if (!step || seen.has(step)) {
      continue
    }
    const milestone = formatAgentMilestone(step, entry)
    if (!milestone) {
      continue
    }
    seen.add(step)
    milestones.push(milestone)
  }
  return milestones
}

function formatAgentMilestone(
  step: string,
  entry: Record<string, unknown>,
): AgentMilestone | null {
  switch (step) {
    case "position_recommendation":
      return {
        key: step,
        label: "结构化分析",
        detail:
          typeof entry.stage === "string" && entry.stage === "done"
            ? "已完成结构化条件分析。"
            : "正在基于结构化条件做分析。",
        tone: "success",
      }
    case "react_evidence_review":
      return {
        key: step,
        label: "证据复核",
        detail:
          typeof entry.action === "string" && entry.action === "refine"
            ? `补充了 ${formatCount(entry.extra_hit_count)} 条证据后重新校验。`
            : "证据充足，跳过额外补证。",
        tone: "neutral",
      }
    case "risk_intent_analysis":
      return {
        key: step,
        label: "风险识别",
        detail: `识别出 ${formatCount(entry.hypothesis_count)} 个风险假设。`,
        tone: "warning",
      }
    case "risk_act":
      return {
        key: step,
        label: "风险检索",
        detail: `检索到 ${formatCount(entry.evidence_hit_count)} 条相关证据。`,
        tone: "neutral",
      }
    case "risk_observe":
      return {
        key: step,
        label: "风险归纳",
        detail: `汇总形成 ${formatCount(entry.risk_item_count)} 项风险结论。`,
        tone: "warning",
      }
    case "risk_reflect":
      return {
        key: step,
        label: "风险定级",
        detail: `当前综合风险等级为 ${formatRiskLevelLabel(
          typeof entry.risk_level === "string" ? entry.risk_level : undefined,
        )}。`,
        tone: "warning",
      }
    case "plan":
      return {
        key: step,
        label: "报告规划",
        detail: `生成了 ${formatCount(entry.outline_count)} 个报告提纲项。`,
        tone: "neutral",
      }
    case "solve":
      return {
        key: step,
        label: "报告生成",
        detail:
          typeof entry.used_llm === "boolean" && entry.used_llm
            ? "已生成并润色报告初稿。"
            : "已完成报告初稿整理。",
        tone: "success",
      }
    case "review":
      return {
        key: step,
        label: "报告复核",
        detail:
          typeof entry.passed === "boolean" && entry.passed
            ? "报告内容复核通过。"
            : `发现 ${formatCount(entry.missing_section_count)} 处提纲缺失。`,
        tone: "neutral",
      }
    default:
      return null
  }
}

function formatCount(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? String(value)
    : "0"
}

function buildReportPreview(reportText: string, maxLines = 10): string {
  const lines = reportText
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0 || line === "")
  if (lines.length <= maxLines) {
    return reportText.trim()
  }
  return `${lines.slice(0, maxLines).join("\n")}\n\n...`
}

function formatRiskLevelLabel(risk?: string | null): string {
  if (!risk) {
    return "未知"
  }
  const labels: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    unknown: "未知",
  }
  return labels[risk] || risk
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

function MetricChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/10 px-3 py-3 shadow-[0_8px_20px_rgba(15,23,42,0.12)]">
      <div className="text-[10px] uppercase tracking-[0.2em] text-slate-300">
        {label}
      </div>
      <div className="mt-2 text-sm font-semibold text-white">{value}</div>
    </div>
  )
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
