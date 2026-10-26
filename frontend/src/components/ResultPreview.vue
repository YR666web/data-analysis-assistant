<template>
  <div class="result-preview glass-card">
    <el-tabs v-model="activeTab" class="tabs">
      <!-- 问答文本 -->
      <el-tab-pane label="问答文本" name="text">
        <el-empty v-if="!session || !session.result" description="暂无结果" :image-size="80" />
        <div v-else class="text-body">{{ session.result }}</div>
      </el-tab-pane>

      <!-- Markdown 预览 + 复制 -->
      <el-tab-pane label="Markdown 报告" name="md">
        <el-empty v-if="!session || !session.result" description="暂无报告" :image-size="80" />
        <div v-else class="md-wrap">
          <div class="md-toolbar">
            <span class="word-count">正文 {{ session.result.length }} 字</span>
            <el-button link size="small" type="primary" @click="copyMarkdown">
              <el-icon><CopyDocument /></el-icon>复制
            </el-button>
          </div>
          <div class="md-body" v-html="renderedMarkdown"></div>
        </div>
      </el-tab-pane>

      <!-- PDF 预览（仅 PDF 任务） -->
      <el-tab-pane v-if="session && session.require_pdf" label="PDF 预览" name="pdf">
        <div class="pdf-toolbar">
          <el-button link size="small" @click="zoom(0.8)"><el-icon><ZoomOut /></el-icon></el-button>
          <el-button link size="small" @click="zoom(1.2)"><el-icon><ZoomIn /></el-icon></el-button>
          <el-button link size="small" @click="zoom(1)">重置</el-button>
        </div>
        <el-empty v-if="!pdfUrl" description="PDF 生成中或不存在" :image-size="80" />
        <iframe v-else :src="pdfUrl" class="pdf-frame" :style="{ transform: `scale(${scale})` }"></iframe>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { Marked } from 'marked'
import { listFiles, downloadFile } from '../api'
import { toast } from '../store'

const props = defineProps({ session: Object })
const activeTab = ref('text')
const pdfUrl = ref('')
const scale = ref(1)

const escapeAttribute = (value) => String(value).replace(/[&"<>]/g, (char) => ({
  '&': '&amp;', '"': '&quot;', '<': '&lt;', '>': '&gt;',
}[char]))

function safeUrl(value, image = false) {
  const url = String(value).trim()
  if (!url || /[\u0000-\u001f\u007f]/.test(url)) return null
  try {
    const parsed = new URL(url, location.origin)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return url
    if (!image && parsed.protocol === 'mailto:') return url
  } catch {}
  return null
}

const markdown = new Marked({
  renderer: {
    html() { return '' },
    link({ href, title, tokens }) {
      const label = this.parser.parseInline(tokens)
      const url = safeUrl(href)
      if (!url) return label
      const tooltip = title ? ` title="${escapeAttribute(title)}"` : ''
      return `<a href="${escapeAttribute(url)}" rel="noopener noreferrer"${tooltip}>${label}</a>`
    },
    image({ href, title, text }) {
      const url = safeUrl(href, true)
      if (!url) return escapeAttribute(text)
      const tooltip = title ? ` title="${escapeAttribute(title)}"` : ''
      return `<img src="${escapeAttribute(url)}" alt="${escapeAttribute(text)}"${tooltip}>`
    },
  },
})

const renderedMarkdown = computed(() => {
  const md = props.session?.result || ''
  return markdown.parse(md)
})

let previewVersion = 0
watch(
  () => [props.session?.thread_id, props.session?.session_dir, props.session?.status],
  async ([threadId, dir, status]) => {
    const version = ++previewVersion
    if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value)
    pdfUrl.value = ''
    if (threadId && dir && status === 'completed' && props.session?.require_pdf) {
      await loadPdf(threadId, dir, version)
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  previewVersion++
  if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value)
})

async function loadPdf(threadId, dir, version) {
  try {
    const res = await listFiles(threadId, dir)
    const pdf = (res.files || []).find((f) => f.type === 'file' && f.name.endsWith('.pdf'))
    if (pdf) {
      const r = await downloadFile(threadId, pdf.path)
      const blob = await r.blob()
      if (version === previewVersion) pdfUrl.value = URL.createObjectURL(blob)
    }
  } catch {}
}

function copyMarkdown() {
  navigator.clipboard.writeText(props.session?.result || '')
  toast('success', '报告已复制到剪贴板')
}

function zoom(v) {
  scale.value = v
}
</script>

<style scoped>
.result-preview {
  flex: 0 0 40%;
  min-height: 180px;
  min-width: 0;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
}
.tabs :deep(.el-tabs__content) {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.tabs :deep(.el-tab-pane) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.text-body {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
}
.md-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.md-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.word-count {
  font-size: 12px;
  color: var(--text-secondary);
}
.md-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: auto;
  overscroll-behavior: contain;
  font-size: 13px;
  line-height: 1.7;
  padding: 8px 0;
  overflow-wrap: anywhere;
}
.md-body :deep(table) {
  border-collapse: collapse;
}
.md-body :deep(td),
.md-body :deep(th) {
  border: 1px solid var(--border);
  padding: 4px 8px;
}
.pdf-toolbar {
  display: flex;
  gap: 4px;
  padding-bottom: 4px;
}
.pdf-frame {
  width: 100%;
  height: calc(100% - 30px);
  border: none;
  transform-origin: top left;
}
</style>
