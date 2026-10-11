import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Composer, SectionEmpty } from '../components/primitives.jsx'
import { ThinkingBlock, ToolRun, messageItems, pairToolRuns } from '../chat/tools.jsx'
import { Icon } from '../icons.jsx'
import { useAsync } from '../lib/hooks.js'
import { mdToHtml, mdToPlain } from '../lib/markdown.js'
import { randomPhrase } from '../lib/statusPhrases.js'

const BTW_RE = /^\/btw(?:\s+|$)/i

// Last few messages plus whatever the main agent is streaming right now,
// truncated so the side question gets a compact, cheap context.
function btwContext(messages, liveItems, streamingText) {
  const rows = []
  for (const m of messages.slice(-8)) {
    if ((m.role === 'user' || m.role === 'assistant') && m.content) {
      rows.push({ role: m.role, content: String(m.content).slice(0, 1200) })
    }
  }
  for (const item of liveItems) {
    if (item.kind === 'assistant' && item.text) {
      rows.push({ role: 'assistant', content: item.text.slice(0, 4000) })
    }
  }
  if (streamingText) {
    rows.push({
      role: 'assistant',
      content: `[working on it right now] ${streamingText.slice(0, 4000)}`,
    })
  }
  return rows
}

function liveTimeline(items) {
  const timeline = []
  for (const item of items) {
    if (item.kind === 'tool') {
      const last = timeline[timeline.length - 1]
      if (last && last.kind === 'tools') last.events.push(item.evt)
      else timeline.push({ kind: 'tools', events: [item.evt] })
    } else {
      timeline.push(item)
    }
  }
  return timeline
}

export function ChatView({ projectId, sessionId, agentId, providerId, onSessionCreated, initialMessage, action }) {
  const sessionsReq = useAsync(() => api.listSessions(projectId), [projectId])
  const settingsReq = useAsync(api.getSettings, [])
  const thinkingDefaultOpen = (settingsReq.data?.show_thinking ?? '1') !== '0'
  const [messages, setMessages] = useState([])
  const [liveItems, setLiveItems] = useState([])
  const [childRuns, setChildRuns] = useState({})
  const [pending, setPending] = useState(null) // 'working' | 'streaming' | null
  const [error, setError] = useState(null)
  const [questions, setQuestions] = useState([])
  const [copiedId, setCopiedId] = useState(null)
  const [answers, setAnswers] = useState({})
  const [streamingText, setStreamingText] = useState('')
  const [rememberedId, setRememberedId] = useState(null)
  const [btw, setBtw] = useState(null) // {question, answer, error, pending}
  const [phrase, setPhrase] = useState(() => randomPhrase())
  const [runId, setRunId] = useState(null)
  const [reconnecting, setReconnecting] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [btwMinimized, setBtwMinimized] = useState(false)
  const [memoryNote, setMemoryNote] = useState(null)
  const [decisionNote, setDecisionNote] = useState(null)
  const [sandboxNote, setSandboxNote] = useState(null)
  const sessionRef = useRef(sessionId)
  const busyRef = useRef(false)
  const initialSentRef = useRef(false)
  const scrollBoxRef = useRef(null)
  const scrollRef = useRef(null)
  const stickRef = useRef(true)
  const lastSessionRef = useRef(sessionId)
  const selfCreatedRef = useRef(null)
  const streamGenRef = useRef(0)

  const onScroll = () => {
    const el = scrollBoxRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const remember = (text, id) => {
    const trimmed = (text || '').trim()
    if (!trimmed) return
    api
      .addPreference(trimmed)
      .then(() => setRememberedId(id))
      .catch((e) => setError(e.message || String(e)))
  }

  useEffect(() => {
    sessionRef.current = sessionId
  }, [sessionId])

  useEffect(() => {
    const prev = lastSessionRef.current
    lastSessionRef.current = sessionId
    // A send in this instance created the session: keep the live stream state.
    if (prev == null && sessionId && selfCreatedRef.current === sessionId) return
    streamGenRef.current += 1
    busyRef.current = false
    setMessages([])
    setLiveItems([])
    setChildRuns({})
    setError(null)
    setQuestions([])
    setAnswers({})
    setStreamingText('')
    setBtw(null)
    setRunId(null)
    setReconnecting(false)
    setStopped(false)
    setBtwMinimized(false)
    setMemoryNote(null)
    setDecisionNote(null)
      setSandboxNote(null)
    setPhrase(randomPhrase())
    if (sessionId) {
      api
        .listMessages(sessionId)
        .then(setMessages)
        .catch((e) => setError(e.message || String(e)))
      api.listQuestions(sessionId).then(setQuestions).catch(() => {})
    }
  }, [sessionId])

  useEffect(() => {
    if (!stickRef.current) return
    scrollRef.current?.scrollIntoView({ behavior: pending ? 'auto' : 'smooth', block: 'end' })
  }, [messages, liveItems, pending, streamingText])

  useEffect(() => {
    if (!sessionId) return
    let alive = true
    let timer = null
    const tick = async () => {
      if (!alive) return
      if (!busyRef.current) {
        try {
          const runs = await api.listRuns(true)
          if (!alive) return
          const active = runs.some(
            (r) => r.kind === 'chat' && r.session_id === sessionId
          )
          if (active) {
            const rows = await api.listMessages(sessionId)
            if (!alive) return
            setMessages(rows)
            timer = setTimeout(tick, 3000)
            return
          }
          const rows = await api.listMessages(sessionId)
          if (!alive) return
          setMessages(rows)
          return
        } catch (e) {
          // transient; try again
        }
      }
      timer = setTimeout(tick, 3000)
    }
    timer = setTimeout(tick, 1200)
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [sessionId])

  const toggleThinking = (item) =>
    setLiveItems((prev) => prev.map((it) => (it === item ? { ...it, open: !it.open } : it)))

  const askBtw = useCallback(
    (question) => {
      setBtwMinimized(false)
      setBtw({ question, answer: '', error: null, pending: true, unread: false })
      api
        .btw(
          projectId,
          {
            question,
            session_id: sessionRef.current || undefined,
            context: btwContext(messages, liveItems, streamingText),
            ...(agentId
              ? { agent_id: agentId }
              : { provider_id: providerId || undefined }),
          },
          {
            onEvent: (evt) => {
              if (evt.event === 'token') {
                setBtw((b) => b && { ...b, answer: b.answer + (evt.text || '') })
              } else if (evt.event === 'error') {
                setBtw((b) => b && { ...b, error: evt.message || 'btw error', pending: false })
              } else if (evt.event === 'done') {
                setBtw((b) => b && { ...b, pending: false, unread: true })
              }
            },
          }
        )
        .catch((e) =>
          setBtw((b) => b && { ...b, error: e.message || String(e), pending: false })
        )
    },
    [projectId, agentId, providerId, messages, liveItems, streamingText]
  )

  useEffect(() => {
    if (!btw) return
    const onKey = (e) => {
      if (e.key === 'Escape') setBtwMinimized(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [btw])

  const stopRun = useCallback(() => {
    if (!runId) return
    api.stopRun(runId).catch((e) => setError(e.message || String(e)))
  }, [runId])

  const send = useCallback(
    (text) => {
      const trimmed = text.trim()
      if (BTW_RE.test(trimmed)) {
        const question = trimmed.replace(BTW_RE, '').trim()
        if (question) askBtw(question)
        return
      }
      if (busyRef.current) return
      const gen = ++streamGenRef.current
      busyRef.current = true
      stickRef.current = true
      setError(null)
      setLiveItems([])
      setChildRuns({})
      setPending('working')
      setPhrase(randomPhrase())
      setRunId(null)
      setReconnecting(false)
      setStopped(false)
      setMemoryNote(null)
      setDecisionNote(null)
      setSandboxNote(null)
      setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: 'user', content: text }])
      api
        .chatStream(
          projectId,
          {
            message: text,
            session_id: sessionRef.current || undefined,
            action: action || undefined,
            ...(agentId ? { agent_id: agentId } : { provider_id: providerId || undefined }),
          },
          {
            onStatus: (s) => gen === streamGenRef.current && setReconnecting(s === 'reconnecting'),
            onEvent: (evt) => {
              if (gen !== streamGenRef.current) return
              if (evt.run_id) setRunId(evt.run_id)
              if (evt.event === 'session') {
                sessionRef.current = evt.session_id
                selfCreatedRef.current = evt.session_id
                setStreamingText('')
                onSessionCreated(evt.session_id)
              } else if (evt.event === 'message') {
                setPending(null)
                setStreamingText('')
                setLiveItems((prev) => {
                  const next = prev.map((it) =>
                    it.kind === 'thinking' ? { ...it, open: false } : it
                  )
                  if (evt.content && evt.content.trim()) {
                    next.push({ kind: 'assistant', id: `a-${Date.now()}`, text: evt.content })
                  }
                  return next
                })
              } else if (evt.event === 'error') {
                setPending(null)
                setStreamingText('')
                setReconnecting(false)
                setError(evt.message || 'Chat error')
              } else if (evt.event === 'stopped' || evt.event === 'timed_out') {
                setPending(null)
                setReconnecting(false)
                if (evt.event === 'stopped') setStopped(true)
                else setError(evt.message || 'Run timed out')
              } else if (evt.event === 'question') {
                setPending(null)
                setStreamingText('')
                setQuestions((prev) => [...prev, { ...evt, status: 'open' }])
              } else if (evt.event === 'thinking') {
                setPending('streaming')
                setLiveItems((prev) => {
                  const last = prev[prev.length - 1]
                  if (last && last.kind === 'thinking') {
                    return [...prev.slice(0, -1), { ...last, text: last.text + (evt.text || '') }]
                  }
                  return [...prev, { kind: 'thinking', text: evt.text || '', open: thinkingDefaultOpen }]
                })
              } else if (evt.event === 'token') {
                setPending('streaming')
                setStreamingText((prev) => prev + (evt.text || ''))
              } else if (evt.event === 'memory') {
                if (evt.writer) setMemoryNote('Memory writer dispatched in the background')
                else if (evt.written)
                  setMemoryNote(`Memory: ${evt.written} written`)
                else if (evt.candidates)
                  setMemoryNote(
                    `Memory: ${evt.candidates} candidate${evt.candidates > 1 ? 's' : ''} to review`
                  )
                else setMemoryNote('Memory checkpoint: nothing durable')
              } else if (evt.event === 'decision') {
                setDecisionNote({
                  verdict: evt.verdict,
                  composite: evt.composite,
                  vetoes: evt.vetoes || [],
                })
              } else if (evt.event === 'sandbox') {
                const lines = Object.values(evt.changed || {}).reduce((a, b) => a + b, 0)
                setSandboxNote(lines ? `Yolo sandbox: ${lines} changed lines in /tmp` : 'Yolo sandbox: no changes')
              } else if (
                evt.event === 'tool_call' ||
                evt.event === 'tool_result' ||
                evt.event === 'tool_progress'
              ) {
                setPending('streaming')
                setLiveItems((prev) => [...prev, { kind: 'tool', evt }])
              } else if (evt.event === 'subagent' || evt.event === 'swarm') {
                setPending('streaming')
                setChildRuns((prev) => {
                  const key = evt.tool_call_id || 'unknown'
                  const list = prev[key] ? [...prev[key]] : []
                  const member = {
                    run_id: evt.run_id,
                    name: evt.name,
                    index: evt.index,
                    status: evt.status,
                    summary: evt.summary || '',
                    title: evt.title || '',
                  }
                  const at = list.findIndex((m) => m.run_id === evt.run_id)
                  if (at >= 0) list[at] = { ...list[at], ...member }
                  else list.push(member)
                  return { ...prev, [key]: list }
                })
              }
              // usage / ping / done are ignored here
            },
          }
        )
        .catch((err) => {
          if (gen !== streamGenRef.current) return
          setError(err.message || String(err))
          const sid = sessionRef.current
          if (sid) {
            api.listMessages(sid).then(setMessages).catch(() => {})
          } else {
            setMessages((prev) => prev.filter((m) => !String(m.id).startsWith('u-')))
          }
        })
        .finally(() => {
          if (gen !== streamGenRef.current) return
          busyRef.current = false
          setPending(null)
          sessionsReq.reload()
          const sid = sessionRef.current
          if (sid) {
            api
              .listMessages(sid)
              .then((rows) => {
                setMessages(rows)
                setLiveItems([])
              })
              .catch(() => {})
            api.listQuestions(sid).then(setQuestions).catch(() => {})
          }
        })
    },
    [projectId, agentId, providerId, onSessionCreated, action, askBtw, thinkingDefaultOpen] // eslint-disable-line react-hooks/exhaustive-deps
  )

  useEffect(() => {
    if (initialMessage && !initialSentRef.current) {
      initialSentRef.current = true
      send(initialMessage)
    }
  }, [initialMessage, send])

  const answerQuestion = (question, text) => {
    const value = (text || '').trim()
    if (!value) return
    setQuestions((prev) =>
      prev.map((q) => (q.id === question.id ? { ...q, status: 'answered', answer: value } : q))
    )
    send(value)
  }

  const skipQuestion = (question) => {
    api
      .dismissQuestion(question.id)
      .then(() => setQuestions((prev) => prev.filter((q) => q.id !== question.id)))
      .catch((e) => setError(e.message || String(e)))
  }

  const copyText = (text, id) => {
    if (!text) return
    navigator.clipboard?.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId((cid) => (cid === id ? null : cid)), 1500)
  }

  const copyCommand = (question) => copyText(question.meta?.command, question.id)

  return (
    <div className="chat">
      {action === 'goal' && (
        <div className="chat-banner">
          <Icon name="sparkles" size={14} /> Goal discussion: refine the outcome, then press
          "Generate board" on the Goals tab.
        </div>
      )}
      <div className="chat-scroll" ref={scrollBoxRef} onScroll={onScroll}>
        <div className="chat-inner">
          {messages.length === 0 &&
            liveEvents.length === 0 &&
            !streamingText &&
            !pending && (
              <SectionEmpty
                icon="chat"
                title="New conversation"
                hint="Ask anything about this project, or describe a task to get started."
              />
            )}
          {messageItems(messages).map((item) =>
            item.kind === 'user' ? (
              <div key={`u-${item.id}`} className="msg user">
                <div className="bubble">{item.content}</div>
              </div>
            ) : item.kind === 'notification' ? (
              <div key={`n-${item.id}`} className="msg notification">
                <div className="notification-banner">{item.content}</div>
              </div>
            ) : (
              <div key={`a-${item.id}`}>
                {item.thinking && (
                  <ThinkingBlock text={item.thinking} defaultOpen={thinkingDefaultOpen} />
                )}
                {item.content && (
                  <div className="msg assistant">
                    <div className="avatar">
                      <Icon name="sparkles" size={15} />
                    </div>
                    <div>
                      <div
                        className="msg-md prose"
                        dangerouslySetInnerHTML={{ __html: mdToHtml(item.content) }}
                      />
                      <div className="msg-actions">
                        <button
                          type="button"
                          className="msg-remember"
                          onClick={() => remember(item.content, item.id)}
                        >
                          <Icon name="check" size={12} />
                          {rememberedId === item.id ? 'Saved as preference' : 'Remember this'}
                        </button>
                        <button
                          type="button"
                          className="msg-remember"
                          onClick={() => copyText(mdToPlain(item.content), `plain-${item.id}`)}
                        >
                          {copiedId === `plain-${item.id}` ? 'Copied' : 'Copy'}
                        </button>
                        <button
                          type="button"
                          className="msg-remember"
                          onClick={() => copyText(item.content, `md-${item.id}`)}
                        >
                          {copiedId === `md-${item.id}` ? 'Copied' : 'Copy as markdown'}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
                {item.runs.map((r, i) => (
                  <div key={i} className="tool-run-wrap">
                    <ToolRun name={r.name} args={r.args} result={r.result} />
                  </div>
                ))}
              </div>
            )
          )}
          {liveTimeline(liveItems).map((g, i) =>
            g.kind === 'thinking' ? (
              <div key={`thinking-${i}`} className="thinking-block">
                <button
                  type="button"
                  className="thinking-head"
                  onClick={() => toggleThinking(g)}
                >
                  <Icon name="sparkles" size={13} />
                  <span>Thinking</span>
                  <span className={`thinking-chevron ${g.open ? 'open' : ''}`}>
                    <Icon name="chevronDown" size={13} />
                  </span>
                </button>
                {g.open && <div className="thinking-body">{g.text}</div>}
              </div>
            ) : g.kind === 'assistant' ? (
              <div key={g.id || `assistant-${i}`} className="msg assistant">
                <div className="avatar">
                  <Icon name="sparkles" size={15} />
                </div>
                <div
                  className="msg-md prose"
                  dangerouslySetInnerHTML={{ __html: mdToHtml(g.text) }}
                />
              </div>
            ) : (
              pairToolRuns(g.events).map((r, j) => (
                <div key={`tools-${i}-${j}`} className="tool-run-wrap">
                  <ToolRun
                    name={r.name}
                    args={r.args}
                    result={r.result}
                    progress={r.progress}
                    members={childRuns[r.id]}
                  />
                </div>
              ))
            )
          )}
          {streamingText && (
            <div className="msg assistant">
              <div className="avatar">
                <Icon name="sparkles" size={15} />
              </div>
              <div
                className="msg-md prose"
                dangerouslySetInnerHTML={{ __html: mdToHtml(streamingText) }}
              />
            </div>
          )}
          {pending && (
            <div className="working">
              <span className="pulse" />
              <span>{phrase}</span>
              <span className="working-dots">
                <i />
                <i />
                <i />
              </span>
            </div>
          )}
          {questions
            .filter((q) => q.status === 'open')
            .map((q) => (
              <div key={q.id} className="question-card">
                <div className="question-head">
                  <Icon
                    name={q.kind === 'approval' ? 'alert' : q.kind === 'user_required' ? 'flag' : 'help'}
                    size={14}
                  />
                  {q.kind === 'approval'
                    ? 'Approval needed'
                    : q.kind === 'user_required'
                      ? 'Action needed'
                      : 'The agent needs input'}
                </div>
                <div className="question-text">{q.question}</div>
                {q.kind === 'user_required' && q.meta?.details && (
                  <div className="question-text">{q.meta.details}</div>
                )}
                {q.kind === 'user_required' && q.meta?.command && (
                  <div className="cmd-block">
                    <code>{q.meta.command}</code>
                    <button className="btn" onClick={() => copyCommand(q)}>
                      {copiedId === q.id ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                )}
                {q.options?.length > 0 && (
                  <div className="question-options">
                    {q.options.map((o) => (
                      <button key={o} className="btn" onClick={() => answerQuestion(q, o)}>
                        {o}
                      </button>
                    ))}
                  </div>
                )}
                <div className="row" style={{ marginBottom: 0 }}>
                  <input
                    value={answers[q.id] || ''}
                    onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        answerQuestion(q, answers[q.id])
                      }
                    }}
                    placeholder="Type your answer..."
                  />
                  <button
                    className="btn primary"
                    disabled={!(answers[q.id] || '').trim()}
                    onClick={() => answerQuestion(q, answers[q.id])}
                  >
                    Answer
                  </button>
                  <button className="btn" onClick={() => skipQuestion(q)}>
                    Skip
                  </button>
                </div>
              </div>
            ))}
          <div ref={scrollRef} />
        </div>
      </div>
      <div className="composer-wrap">
        {reconnecting && <div className="chat-note">Reconnecting…</div>}
        {memoryNote && <div className="chat-note">{memoryNote}</div>}
        {sandboxNote && <div className="chat-note">{sandboxNote}</div>}
        {decisionNote && (
          <div className={`chat-note decision-note decision-${decisionNote.verdict}`}>
            Decision: {decisionNote.verdict}
            {decisionNote.composite != null ? ` · ${decisionNote.composite.toFixed(2)}` : ''}
            {decisionNote.vetoes.length ? ` · vetoed: ${decisionNote.vetoes.join(', ')}` : ''}
          </div>
        )}
        {stopped && !pending && <div className="chat-note">Stopped by you.</div>}
        {btw && !btwMinimized && (
          <div className="btw-box">
            <div className="btw-head">
              <span className="btw-prompt">$</span>
              <span className="btw-question" title={btw.question}>
                {btw.question}
              </span>
              <button
                className="btw-close"
                onClick={() => setBtwMinimized(true)}
                title="Minimize (Esc)"
              >
                <Icon name="chevronDown" size={13} />
              </button>
              <button
                className="btw-close"
                onClick={() => {
                  setBtw(null)
                  setBtwMinimized(false)
                }}
                title="Discard"
              >
                <Icon name="x" size={13} />
              </button>
            </div>
            <div className="btw-body">
              {btw.error ? (
                <div className="btw-error">{btw.error}</div>
              ) : btw.answer ? (
                <div className="btw-answer">
                  {btw.answer}
                  {btw.pending && <span className="btw-cursor" />}
                </div>
              ) : (
                <span className="btw-dim">
                  {btw.pending ? (
                    <>
                      reading context
                      <span className="working-dots">
                        <i />
                        <i />
                        <i />
                      </span>
                    </>
                  ) : (
                    'no answer'
                  )}
                </span>
              )}
            </div>
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
        <Composer
          busy={!!pending}
          placeholder="Message... (use /btw for a side question)"
          hint="Enter to send · /btw asks a side question without stopping the task"
          onSend={send}
          onStop={stopRun}
          trailing={
            btw && btwMinimized ? (
              <button
                type="button"
                className="btw-icon"
                title="Reopen the side question"
                onClick={() => {
                  setBtwMinimized(false)
                  setBtw((b) => b && { ...b, unread: false })
                }}
              >
                <Icon name="chat" size={15} />
                {btw.unread && <span className="btw-dot" />}
              </button>
            ) : null
          }
        />
      </div>
    </div>
  )
}
