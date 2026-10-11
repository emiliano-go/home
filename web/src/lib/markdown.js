import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.use({ gfm: true, breaks: true })

export function mdToHtml(md) {
  const html = marked.parse(String(md ?? ''))
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target', 'loading'] })
}

export function mdToPlain(md) {
  const html = mdToHtml(md)
    .replace(/<\/(p|h[1-6]|li|tr|pre|blockquote)>/gi, '</$1>\n')
    .replace(/<br\s*\/?>/gi, '\n')
  const el = document.createElement('div')
  el.innerHTML = html
  return (el.textContent || '').replace(/\n{3,}/g, '\n\n').trim()
}
