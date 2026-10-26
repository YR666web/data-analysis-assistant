<template>
  <section v-if="blocks.length || active" class="live-output" aria-label="实时输出" :aria-busy="active">
    <header>实时输出 <span>{{ active ? '生成中 · 内容持续更新' : '输出已结束' }}</span></header>
    <p v-if="!blocks.length" class="waiting">任务正在处理，模型输出将在这里实时显示。</p>
    <article v-for="(block, index) in blocks" :key="block.id" class="output-block">
      <div class="block-title">
        输出片段 {{ index + 1 }}
        <span v-if="block.status === 'streaming' && active" class="generating">生成中</span>
        <span v-else>{{ block.status === 'completed' ? '已结束' : '已停止' }}</span>
      </div>
      <p v-if="block.truncated" class="waiting">较早的内容已省略，完整结果请查看文档区域。</p>
      <div v-if="block.text" class="output-text">{{ block.text }}<i v-if="block.status === 'streaming' && active" class="cursor" aria-hidden="true"></i></div>
      <p v-else class="waiting">{{ block.status === 'streaming' && active ? '等待模型返回内容…' : '本轮未返回正文，可能调用了工具。' }}</p>
    </article>
  </section>
</template>

<script setup>
defineProps({ blocks: { type: Array, default: () => [] }, active: Boolean })
</script>

<style scoped>
.live-output { margin: 8px 0 12px; padding: 12px; border-top: 1px solid var(--border); }
header { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; }
header span, .block-title span, .waiting { font-size: 12px; font-weight: 400; color: var(--text-secondary); }
.output-block { padding-top: 12px; }
.block-title { display: flex; gap: 12px; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.block-title .generating { color: var(--primary); }
.output-text { font-size: 13px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.waiting { margin-top: 8px; line-height: 1.6; }
.cursor { display: inline-block; width: 2px; height: 1em; margin-left: 3px; vertical-align: -2px; background: var(--primary); animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .cursor { animation: none; } }
</style>
