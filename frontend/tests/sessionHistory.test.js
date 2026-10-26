import test from 'node:test'
import assert from 'node:assert/strict'
globalThis.localStorage = { getItem: () => null, setItem() {} }
const { store, mergeSavedSessions } = await import('../src/store.js')

test('server history restores a fresh browser and preserves in-flight edits', () => {
  store.sessions = []
  store.currentThreadId = ''
  mergeSavedSessions([{ thread_id: 'old', query: '销售周报', status: 'completed', result: '210' }])
  assert.equal(store.currentThreadId, 'old')
  assert.equal(store.sessions[0].result, '210')
  store.sessions[0].status = 'running'
  store.sessions[0].result = ''
  mergeSavedSessions([{ thread_id: 'old', status: 'completed', result: 'stale' }], new Set(['old']))
  assert.equal(store.sessions[0].status, 'running')
  assert.equal(store.sessions[0].result, '')
  store.sessions = []
})
