import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons.jsx'

export function Spinner({ size = 14 }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
}

export function Skeleton({ className = '', style }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />
}

const isBtw = (msg) => /^\/btw(\s|$)/i.test(msg)

export function Composer({ onSend, busy, placeholder, hint, onStop, trailing }) {
  const [value, setValue] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 200) + 'px'
    }
  }, [value])

  const submit = () => {
    const msg = value.trim()
    if (!msg) return
    if (busy && !isBtw(msg)) return
    setValue('')
    onSend(msg)
  }

  const command = value.match(/^\/[a-z-]+/i)
  const highlighting = !!command

  return (
    <div className="composer">
      <div className={`composer-input ${highlighting ? 'highlighting' : ''}`}>
        {highlighting && (
          <div className="composer-mirror" aria-hidden="true">
            <span className="composer-cmd">{command[0]}</span>
            {value.slice(command[0].length)}
          </div>
        )}
        <textarea
          ref={ref}
          className={highlighting ? 'ghost' : ''}
          rows={1}
          value={value}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
      </div>
      <div className="composer-foot">
        <span className="composer-hint">
          {hint || 'Enter to send, Shift+Enter for a new line'}
        </span>
        <span className="composer-actions">
          {trailing}
          {busy ? (
            <button type="button" className="send-btn stop" onClick={onStop} title="Stop">
              <Icon name="stop" size={16} />
            </button>
          ) : (
            <button
              className="send-btn"
              onClick={submit}
              disabled={!value.trim()}
              title="Send"
            >
              <Icon name="arrowUp" size={18} />
            </button>
          )}
        </span>
      </div>
    </div>
  )
}

export function SectionEmpty({ icon, title, hint, action }) {
  return (
    <div className="placeholder">
      <div className="placeholder-icon">
        <Icon name={icon} size={18} />
      </div>
      <div className="placeholder-title">{title}</div>
      {hint && <div className="placeholder-hint">{hint}</div>}
      {action}
    </div>
  )
}

export function ProgressBar({ percent }) {
  return (
    <div className="progress" title={`${percent}% complete`}>
      <div className="progress-fill" style={{ width: `${percent}%` }} />
    </div>
  )
}
