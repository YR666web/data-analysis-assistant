// Per-model sequence numbers prevent delayed REST snapshots from replacing
// newer text, and let a later snapshot repair missing WebSocket chunks.
export function mergeStreamSnapshot(session, blocks = []) {
  if (!blocks.length) return
  session.streams ||= []
  for (const incoming of blocks) {
    const block = session.streams.find((item) => item.id === incoming.id)
    if (!block) session.streams.push({ ...incoming })
    else if (incoming.seq >= block.seq) Object.assign(block, incoming)
  }
  if (session.streams.length > 20) session.streams.splice(0, session.streams.length - 20)
}

export function applyStreamEvent(session, event) {
  if (!['model_start', 'model_delta', 'model_end'].includes(event.event)) return false
  const data = event.data || {}
  if (data.block) mergeStreamSnapshot(session, [data.block])
  else if (event.event === 'model_delta') {
    session.streams ||= []
    let block = session.streams.find((item) => item.id === data.id)
    if (!block && data.seq === 1) {
      mergeStreamSnapshot(session, [{ id: data.id, text: '', seq: 0, status: 'streaming', truncated: false }])
      block = session.streams.find((item) => item.id === data.id)
    }
    if (block && data.seq === block.seq + 1) {
      const text = block.text + data.delta
      block.text = text.slice(-32000)
      block.truncated ||= text.length > 32000
      block.seq = data.seq
    }
  }
  return true
}
