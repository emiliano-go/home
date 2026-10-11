export function clickable(onClick) {
  return {
    role: 'button',
    tabIndex: 0,
    onClick,
    onKeyDown: (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onClick(e)
      }
    },
  }
}

// Arrow-key navigation within a container of buttons (Tab enters, arrows
// move, matching the grid/list layout). Attach as onKeyDown on the container.
export function handleArrowNav(e) {
  if (!['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
  const container = e.currentTarget
  const items = Array.from(container.querySelectorAll('button:not([disabled])'))
  if (items.length < 2) return
  const idx = items.indexOf(document.activeElement)
  if (idx === -1) return
  e.preventDefault()
  // Detect column count from layout so Up/Down jumps a full row in grids.
  const firstTop = items[0].offsetTop
  const cols = items.filter((el) => el.offsetTop === firstTop).length || 1
  let next = idx
  switch (e.key) {
    case 'ArrowRight':
      next = (idx + 1) % items.length
      break
    case 'ArrowLeft':
      next = (idx - 1 + items.length) % items.length
      break
    case 'ArrowDown':
      next = idx + cols <= items.length - 1 ? idx + cols : idx
      break
    case 'ArrowUp':
      next = idx - cols >= 0 ? idx - cols : idx
      break
    case 'Home':
      next = 0
      break
    case 'End':
      next = items.length - 1
      break
  }
  items[next]?.focus()
}
