import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, nextTick, watch } from 'vue'
import { createTaskSync } from '../src/taskSync.js'
import { connectWS } from '../src/api.js'

const saved = new Map()
globalThis.localStorage = {
  getItem: (key) => saved.get(key) ?? null,
  setItem: (key, value) => saved.set(key, value),
}
const { addSession, store, deleteSession } = await import('../src/store.js')
const flush = async () => { await Promise.resolve(); await Promise.resolve() }

test('received events update rendered state and saved sessions without a refresh', async () => {
  const session = addSession('reactivity_test', 'list drugs', false)
  const result = computed(() => store.sessions[0].result)
  const updates = []
  const unwatch = watch(() => [store.sessions[0].status, result.value, store.sessions[0].events.length],
    (value) => updates.push(value), { flush: 'sync' })
  assert.equal(result.value, '') // prime the same cache used by a rendered component
  session.events.push({ event: 'tool_start' })
  session.result = '8 records'
  session.status = 'completed'
  assert.equal(result.value, '8 records')
  assert.deepEqual(updates.at(-1), ['completed', '8 records', 1])
  await nextTick()
  assert.equal(JSON.parse(saved.get('data-analysis-assistant-sessions'))[0].result, '8 records')
  unwatch()
  deleteSession(session.thread_id)
})

test('does not poll an unsubmitted task while upload or connection is pending', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let reads = 0
  const sync = createTaskSync('pending', {
    connect: async () => ({ close() {} }),
    getStatus: async () => { reads++; return { status: 'running' } },
    onEvent() {}, onState() {},
  })
  t.after(() => sync.stop())
  await sync.ready
  t.mock.timers.tick(10000)
  await flush()
  assert.equal(reads, 0)
  await sync.start()
  assert.equal(reads, 1)
})

test('WebSocket failure still recovers completed result through REST', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let snapshot
  const sync = createTaskSync('fallback', {
    connect: async () => { throw new Error('offline socket') },
    getStatus: async () => ({ status: 'completed', result: 'done', session_dir: 'session_fallback' }),
    onEvent() {}, onState: (state) => { snapshot = state; sync.stop() },
  })
  t.after(() => sync.stop())
  await sync.ready
  await sync.start()
  assert.equal(snapshot.result, 'done')
  assert.equal(snapshot.session_dir, 'session_fallback')
})

test('reconnects after a disconnect and ignores callbacks after disposal', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const connections = []
  const received = []
  const sync = createTaskSync('reconnect', {
    connect: async (id, onEvent, options) => {
      connections.push({ onEvent, ...options })
      return { close() {} }
    },
    getStatus: async () => ({ status: 'running' }),
    onEvent: (ev) => received.push(ev), onState() {}, retryMs: 100,
  })
  t.after(() => sync.stop())
  await sync.ready
  connections[0].onClose()
  t.mock.timers.tick(100)
  await flush()
  assert.equal(connections.length, 2)
  connections[1].onEvent('live')
  sync.stop()
  connections[1].onClose()
  connections[1].onEvent('late')
  t.mock.timers.tick(10000)
  await flush()
  assert.deepEqual(received, ['live'])
  assert.equal(connections.length, 2)
})

test('slow REST requests never overlap and cannot overwrite a disposed run', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let resolveStatus
  let reads = 0
  const states = []
  const sync = createTaskSync('slow', {
    connect: async () => ({ close() {} }),
    getStatus: () => { reads++; return new Promise((resolve) => { resolveStatus = resolve }) },
    onEvent() {}, onState: (state) => states.push(state),
  })
  t.after(() => sync.stop())
  await sync.ready
  const pending = sync.start()
  await sync.refresh()
  t.mock.timers.tick(10000)
  assert.equal(reads, 1)
  sync.stop()
  resolveStatus({ status: 'running' })
  await pending
  assert.deepEqual(states, [])
})

test('temporary REST failure is retried without marking task failed', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let reads = 0
  const states = []
  const sync = createTaskSync('retry', {
    connect: async () => ({ close() {} }),
    getStatus: async () => {
      if (++reads === 1) throw new Error('temporary outage')
      return { status: 'cancelled' }
    },
    onEvent() {}, onState: (state) => { states.push(state.status); sync.stop() }, pollMs: 100,
  })
  t.after(() => sync.stop())
  await sync.ready
  await sync.start()
  assert.deepEqual(states, [])
  t.mock.timers.tick(100)
  await flush()
  assert.deepEqual(states, ['cancelled'])
})

test('closing a WebSocket before it opens rejects promptly', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] })
  let socket
  let closed = 0
  class FakeSocket {
    constructor() { socket = this }
    close() { this.onclose?.() }
  }
  t.mock.property(globalThis, 'WebSocket', FakeSocket)
  // Node has no location; restore the test-only browser value afterwards.
  globalThis.location = { protocol: 'http:', host: 'localhost' }
  t.after(() => { delete globalThis.location })
  const ready = connectWS('early_close', () => {}, { onClose: () => closed++ })
  socket.close()
  await assert.rejects(ready, /断开/)
  assert.equal(closed, 1)
})
