<template>
  <div class="app">
    <!-- 左侧边栏 -->
    <aside class="sidebar glass-card">
      <div class="logo">
        <el-icon :size="22" color="#165DFF"><MagicStick /></el-icon>
        <span class="logo-text">数据分析助手</span>
        <span class="logo-sub">多智能体数据分析</span>
        <el-switch
          :model-value="store.theme === 'dark'"
          class="theme-switch"
          inline-prompt
          active-icon="Moon"
          inactive-icon="Sunny"
          @change="toggleTheme"
        />
      </div>

      <!-- 统计卡片 -->
      <div class="stats">
        <div class="stat running">
          <span class="num">{{ stats.running }}</span>
          <span class="label">运行中</span>
        </div>
        <div class="stat completed">
          <span class="num">{{ stats.completed }}</span>
          <span class="label">已完成</span>
        </div>
        <div class="stat failed">
          <span class="num">{{ stats.failed }}</span>
          <span class="label">失败</span>
        </div>
      </div>

      <!-- 会话列表 -->
      <div class="section-title">会话列表</div>
      <el-scrollbar class="session-scroll">
        <el-empty v-if="!store.sessions.length" description="暂无会话" :image-size="60" />
        <div
          v-for="s in store.sessions"
          :key="s.thread_id"
          class="session-item"
          :class="{ active: s.thread_id === store.currentThreadId }"
          @click="onSwitch(s.thread_id)"
        >
          <div class="session-head">
            <el-tag :type="statusTagType(s.status)" size="small">{{ statusText(s.status) }}</el-tag>
            <span class="session-time">{{ s.created_at.slice(5, 16) }}</span>
          </div>
          <div class="session-query">{{ s.query }}</div>
          <div class="session-actions">
            <el-button link size="small" @click.stop="rerun(s.thread_id)">
              <el-icon><RefreshRight /></el-icon>重跑
            </el-button>
            <el-button link size="small" type="danger" @click.stop="onDelete(s.thread_id)">
              <el-icon><Delete /></el-icon>删除会话
            </el-button>
          </div>
        </div>
      </el-scrollbar>

      <!-- 快捷模板 -->
      <div class="section-title">快捷模板</div>
      <div class="templates">
        <el-tag
          v-for="t in QUICK_TEMPLATES"
          :key="t.label"
          class="template-tag"
          effect="plain"
          @click="fillTemplate(t.value)"
        >
          {{ t.label }}
        </el-tag>
      </div>
    </aside>

    <!-- 中央主区域 -->
    <main ref="mainRef" class="main" :class="{ resizing: resizeState }">
      <EventTree :session="session" @rerun="rerun" @terminate="terminate" />
      <div
        class="resize-handle"
        role="separator"
        aria-label="调整文档区域高度"
        aria-orientation="horizontal"
        :aria-valuenow="Math.round(resultPanelSize)"
        aria-valuemin="20"
        aria-valuemax="75"
        tabindex="0"
        @pointerdown="startResize"
        @pointermove="moveResize"
        @pointerup="stopResize"
        @pointercancel="stopResize"
        @keydown="resizeByKeyboard"
      ><span></span></div>
      <ResultPreview :session="session" :style="{ flex: `0 0 ${resultPanelSize}%` }" />
    </main>

    <!-- 右侧文件面板 -->
    <aside class="file glass-card">
      <FilePanel :session="session" />
    </aside>

    <!-- 底部任务输入通栏 -->
    <footer class="taskbar">
      <TaskInput @submit="startTask" />
    </footer>

    <!-- Toast -->
    <div class="toasts">
      <transition-group name="toast">
        <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.type">
          <el-icon><component :is="toastIcon(t.type)" /></el-icon>
          <span>{{ t.message }}</span>
        </div>
      </transition-group>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import TaskInput from './components/TaskInput.vue'
import EventTree from './components/EventTree.vue'
import FilePanel from './components/FilePanel.vue'
import ResultPreview from './components/ResultPreview.vue'
import { submitTask, uploadFiles, cancelTask, getTaskStatus, deleteSessionRemote, getSavedSessions } from './api'
import { createTaskSync } from './taskSync'
import { applyStreamEvent, mergeStreamSnapshot } from './liveStreams'
import {
  store,
  mergeSavedSessions,
  addSession,
  getSession,
  switchSession,
  deleteSession,
  toggleTheme,
  sessionStats,
  currentSession,
  toast,
  QUICK_TEMPLATES,
} from './store'

const stats = computed(() => sessionStats())
const session = computed(() => currentSession())
const mainRef = ref(null)
const savedPanelSize = Number(localStorage.getItem('data-analysis-assistant-result-panel-size'))
const resultPanelSize = ref(Number.isFinite(savedPanelSize) && savedPanelSize > 0 ? savedPanelSize : 40)
const resizeState = ref(null)

watch(resultPanelSize, (value) => {
  localStorage.setItem('data-analysis-assistant-result-panel-size', String(value))
})

function clampPanelSize(value) {
  const height = mainRef.value?.clientHeight || 700
  const min = Math.max(20, (160 / height) * 100)
  const max = Math.min(75, ((height - 180) / height) * 100)
  return Math.min(max, Math.max(min, value))
}

function startResize(event) {
  if (event.button !== 0) return
  resizeState.value = { y: event.clientY, size: resultPanelSize.value }
  event.currentTarget.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function moveResize(event) {
  if (!resizeState.value) return
  const height = mainRef.value?.clientHeight || 700
  resultPanelSize.value = clampPanelSize(
    resizeState.value.size + ((resizeState.value.y - event.clientY) / height) * 100,
  )
}

function stopResize() {
  resizeState.value = null
}

function resizeByKeyboard(event) {
  if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
    event.preventDefault()
    resultPanelSize.value = clampPanelSize(resultPanelSize.value + (event.key === 'ArrowUp' ? 3 : -3))
  }
}

const syncs = new Map()
const isActive = (s) => ['running', 'cancelling'].includes(s.status)

function stopSync(threadId) {
  syncs.get(threadId)?.stop()
  syncs.delete(threadId)
}

function followSession(s) {
  stopSync(s.thread_id)
  const sync = createTaskSync(s.thread_id, {
    onEvent: (ev) => onEvent(s, ev),
    onState: (state) => applyTaskStatus(s, state),
  })
  syncs.set(s.thread_id, sync)
  return sync
}

function applyTaskStatus(session, state) {
  if (!state) return
  mergeStreamSnapshot(session, state.streams)
  if (state.session_dir) session.session_dir = state.session_dir
  if (state.status === 'unknown') {
    if (isActive(session)) {
      session.status = 'failed'
      session.events.push({ event: 'error', message: '服务端已无此任务记录；任务可能因服务重启而中断。可重跑或移除。' })
    }
  } else if (state.status === 'completed') {
    session.status = 'completed'
    session.result = state.result || session.result || ''
    if (!session.events.some((ev) => ev.event === 'task_result')) {
      session.events.push({ event: 'task_result', message: '任务完成（状态同步）' })
    }
  } else if (state.status === 'failed') {
    if (session.status !== 'failed') session.events.push({ event: 'error', message: state.error || '任务执行失败' })
    session.status = 'failed'
  } else if (state.status === 'cancelled') { session.status = 'cancelled' }
  else if (state.status === 'cancelling' && session.status === 'running') { session.status = 'cancelling' }
  if (!isActive(session)) stopSync(session.thread_id)
}

function refreshStatuses() {
  for (const sync of syncs.values()) sync.refresh()
}

function onVisible() {
  if (document.visibilityState === 'visible') refreshStatuses()
}

onMounted(() => {
  restoreSavedSessions()
  for (const s of store.sessions.filter(isActive)) followSession(s).start()
  window.addEventListener('online', refreshStatuses)
  window.addEventListener('focus', refreshStatuses)
  document.addEventListener('visibilitychange', onVisible)
})

async function restoreSavedSessions() {
  const originalIds = new Set(store.sessions.map((s) => s.thread_id))
  try {
    let offset = 0
    do {
      const saved = await getSavedSessions(offset)
      // Do not overwrite a task submitted/rerun, or resurrect one deleted while loading.
      const currentIds = new Set(store.sessions.map((s) => s.thread_id))
      const protectedIds = new Set(store.sessions.filter(isActive).map((s) => s.thread_id))
      for (const id of currentIds) if (!originalIds.has(id)) protectedIds.add(id)
      const records = saved.sessions.filter((s) => !originalIds.has(s.thread_id) || currentIds.has(s.thread_id))
      mergeSavedSessions(records, protectedIds)
      for (const s of store.sessions.filter(isActive)) if (!syncs.has(s.thread_id)) followSession(s).start()
      offset = saved.next_offset
    } while (offset !== null)
  } catch (error) {
    console.warn('服务端会话恢复失败，保留本地记录', error)
  }
}
onUnmounted(() => {
  for (const sync of syncs.values()) sync.stop()
  syncs.clear()
  window.removeEventListener('online', refreshStatuses)
  window.removeEventListener('focus', refreshStatuses)
  document.removeEventListener('visibilitychange', onVisible)
})

function onEvent(session, ev) {
  if (applyStreamEvent(session, ev)) return
  mergeStreamSnapshot(session, ev.data?.streams)
  session.events.push(ev)
  if (ev.event === 'session_created') {
    session.session_dir = ev.data?.path || ''
  } else if (ev.event === 'task_result') {
    session.status = 'completed'
    session.result = ev.data?.result || ''
    toast('success', '任务完成')
  } else if (ev.event === 'error') {
    session.status = 'failed'
    toast('error', ev.message || '任务执行失败')
  } else if (ev.event === 'task_cancelled') {
    session.status = 'cancelled'
    toast('warning', '任务已终止')
  }
  if (!isActive(session)) stopSync(session.thread_id)
}

async function startTask(query, requirePdf, files = []) {
  const threadId = crypto.randomUUID().replace(/-/g, '')
  const session = addSession(threadId, query, requirePdf)
  try {
    if (files.length) await uploadFiles(threadId, files)
    const sync = followSession(session)
    await sync.ready
    await submitTask(query, threadId, requirePdf)
    sync.start()
    toast('info', `会话已创建：${threadId.slice(0, 8)}`)
  } catch (e) {
    stopSync(threadId)
    session.status = 'failed'
    toast('error', e.message || '任务提交失败')
  }
}

async function rerun(threadId) {
  const s = getSession(threadId)
  if (!s || isActive(s)) return
  stopSync(threadId)
  s.events = []
  s.streams = []
  s.status = 'running'
  s.result = ''
  s.session_dir = ''
  s.hard_rounds = []
  try {
    const sync = followSession(s)
    await sync.ready
    await submitTask(s.query, threadId, s.require_pdf)
    sync.start()
    toast('info', '任务已重新执行')
  } catch (e) {
    stopSync(threadId)
    s.status = 'failed'
    toast('error', e.message || '重跑失败')
  }
}

async function terminate(threadId) {
  const s = getSession(threadId)
  if (!s) return
  try {
    const state = await cancelTask(threadId)
    if (state.status === 'cancelling' && isActive(s)) {
      s.status = 'cancelling'
      toast('info', '正在终止任务')
    }
    await syncs.get(threadId)?.refresh()
  } catch (e) {
    try { applyTaskStatus(s, await getTaskStatus(threadId)) } catch {}
    toast('error', e.message || '终止失败')
  }
}

function onSwitch(threadId) {
  switchSession(threadId)
}

async function onDelete(threadId) {
  if (['running', 'cancelling'].includes(getSession(threadId)?.status)) {
    toast('warning', '请先终止正在运行的任务')
    return
  }
  if (!window.confirm('删除此会话及其生成文件和上传文件？此操作无法撤销。')) return
  try {
    await deleteSessionRemote(threadId)
  } catch (e) {
    toast('error', e.message || '删除失败')
    return
  }
  stopSync(threadId)
  deleteSession(threadId)
  toast('info', '会话和文件已删除')
}

function fillTemplate(value) {
  store.pendingQuery = value
}

function statusText(status) {
  return { running: '运行中', cancelling: '正在终止', cancelled: '已终止', completed: '已完成', failed: '失败' }[status] || status
}
function statusTagType(status) {
  return { running: 'primary', cancelling: 'warning', cancelled: 'info', completed: 'success', failed: 'danger' }[status] || 'info'
}
function toastIcon(type) {
  return { success: 'CircleCheck', error: 'CircleClose', warning: 'Warning', info: 'InfoFilled' }[type] || 'InfoFilled'
}
</script>

<style scoped>
.app {
  display: grid;
  grid-template-rows: 1fr auto;
  grid-template-columns: 220px 1fr 320px;
  grid-template-areas:
    'sidebar main file'
    'taskbar taskbar taskbar';
  height: 100vh;
  gap: 12px;
  padding: 12px;
  background: var(--bg);
}
.sidebar {
  grid-area: sidebar;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}
.main {
  grid-area: main;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
  min-width: 0;
}
.resize-handle {
  flex: 0 0 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  touch-action: none;
  user-select: none;
  outline: none;
}
.resize-handle span {
  width: 44px;
  height: 3px;
  border-radius: 3px;
  background: var(--border);
  transition: background 0.15s, width 0.15s;
}
.resize-handle:hover span,
.resize-handle:focus-visible span {
  width: 64px;
  background: var(--primary);
}
.main.resizing {
  cursor: row-resize;
  user-select: none;
}
.file {
  grid-area: file;
  padding: 12px;
  overflow: hidden;
}
.taskbar {
  grid-area: taskbar;
}

.logo {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 40px;
  grid-template-rows: auto auto;
  align-items: center;
  column-gap: 6px;
}
.logo > .el-icon {
  grid-column: 1;
  grid-row: 1 / span 2;
}
.logo-text {
  grid-column: 2;
  grid-row: 1;
  font-size: 16px;
  font-weight: 700;
  color: var(--primary);
  white-space: nowrap;
}
.logo-sub {
  grid-column: 2;
  grid-row: 2;
  font-size: 10px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.theme-switch {
  grid-column: 3;
  grid-row: 1 / span 2;
}

.stats {
  display: flex;
  gap: 8px;
}
.stat {
  flex: 1;
  border-radius: 8px;
  padding: 8px;
  text-align: center;
  background: var(--bg);
}
.stat .num {
  font-size: 20px;
  font-weight: 700;
  display: block;
}
.stat .label {
  font-size: 11px;
  color: var(--text-secondary);
}
.stat.running .num {
  color: var(--primary);
}
.stat.completed .num {
  color: var(--success);
}
.stat.failed .num {
  color: var(--danger);
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
.session-scroll {
  flex: 1;
  min-height: 0;
}
.session-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.session-item:hover {
  border-color: var(--primary);
}
.session-item.active {
  border-color: var(--primary);
  background: rgba(22, 93, 255, 0.06);
}
.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.session-time {
  font-size: 11px;
  color: var(--text-secondary);
}
.session-query {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-actions {
  display: flex;
  gap: 4px;
  margin-top: 4px;
}

.templates {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.template-tag {
  cursor: pointer;
}

.toasts {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border-radius: 8px;
  background: var(--card-bg);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  font-size: 13px;
}
.toast.success {
  border-left: 3px solid var(--success);
}
.toast.error {
  border-left: 3px solid var(--danger);
}
.toast.warning {
  border-left: 3px solid var(--warning);
}
.toast.info {
  border-left: 3px solid var(--primary);
}
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
