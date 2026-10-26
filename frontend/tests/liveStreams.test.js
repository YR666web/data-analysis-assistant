import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive, computed } from 'vue'
import { applyStreamEvent, mergeStreamSnapshot } from '../src/liveStreams.js'

const delta = (seq, text) => ({ event: 'model_delta', data: { id: 'a', seq, delta: text } })

test('stream text updates reactively without changing the final result', () => {
  const session = reactive({ result: '', streams: [] })
  const rendered = computed(() => session.streams.map((b) => b.text).join(''))
  assert.equal(rendered.value, '')
  applyStreamEvent(session, delta(1, '第一段'))
  applyStreamEvent(session, delta(2, '第二段'))
  assert.equal(rendered.value, '第一段第二段')
  assert.equal(session.result, '')
})

test('duplicates and older REST snapshots cannot overwrite new text', () => {
  const session = {}
  applyStreamEvent(session, delta(1, 'a'))
  applyStreamEvent(session, delta(2, 'b'))
  applyStreamEvent(session, delta(2, 'b'))
  mergeStreamSnapshot(session, [{ id: 'a', text: 'stale', seq: 1 }])
  assert.equal(session.streams[0].text, 'ab')
})

test('a missing chunk is repaired from snapshot before accepting later deltas', () => {
  const session = {}
  applyStreamEvent(session, delta(1, 'a'))
  applyStreamEvent(session, delta(3, 'c'))
  assert.equal(session.streams[0].text, 'a')
  mergeStreamSnapshot(session, [{ id: 'a', text: 'abc', seq: 3, status: 'streaming' }])
  applyStreamEvent(session, delta(4, 'd'))
  assert.equal(session.streams[0].text, 'abcd')
})

test('end event repairs the full text and ends the spinner', () => {
  const session = {}
  applyStreamEvent(session, { event: 'model_end', data: { block: { id: 'a', text: 'complete', seq: 9, status: 'completed' } } })
  assert.equal(session.streams[0].text, 'complete')
  assert.equal(session.streams[0].status, 'completed')
})
