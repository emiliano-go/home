import { createPortal } from 'react-dom'
import { Icon } from '../icons.jsx'

export function Modal({ title, onClose, children }) {
  return createPortal(
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="icon-btn modal-close" onClick={onClose} title="Close">
            <Icon name="x" size={20} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body
  )
}

export function ConfirmModal({ title, confirmLabel = 'Confirm', danger = false, busy = false, onConfirm, onClose, children }) {
  return (
    <Modal title={title} onClose={onClose}>
      {children}
      <div className="row" style={{ marginBottom: 0, marginTop: 14 }}>
        <button
          className={`btn ${danger ? 'danger' : 'primary'}`}
          disabled={busy}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}
