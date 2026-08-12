<template>
  <div class="ma-workspace">
    <aside class="ma-rail" aria-label="多智能体编排概览">
      <RouterLink class="ma-back-link" :to="{ name: 'agents' }">
        <ArrowLeft :size="16" aria-hidden="true" />
        Agent 应用
      </RouterLink>

      <div class="ma-agent-intro">
        <span class="ma-agent-mark"><GraphIcon :size="26" weight="duotone" aria-hidden="true" /></span>
        <div>
          <span class="ma-product-name">Multi-Agent</span>
          <h1>Plan-and-Solve</h1>
        </div>
      </div>
      <p class="ma-agent-description">主智能体负责理解与调度，子智能体按计划执行，最后统一综合结果。</p>

      <section class="ma-history" aria-labelledby="ma-history-title">
        <header>
          <h2 id="ma-history-title">历史任务</h2>
          <button type="button" aria-label="刷新历史任务" title="刷新" @click="loadMultiAgentSessions()">
            <ClockCounterClockwise :size="15" aria-hidden="true" />
          </button>
        </header>
        <p v-if="sessionsLoading" class="ma-history-state">正在加载…</p>
        <p v-else-if="sessionsError" class="ma-history-state is-error">{{ sessionsError }}</p>
        <p v-else-if="!multiAgentSessions.length" class="ma-history-state">暂无历史任务</p>
        <div v-else class="ma-history-list">
          <button
            v-for="session in multiAgentSessions"
            :key="session.session_id"
            class="ma-history-item"
            :class="{ 'is-active': activeSessionId === session.session_id }"
            type="button"
            :disabled="running || Boolean(loadingSessionId)"
            @click="loadHistoricalSession(session)"
          >
            <span>
              <strong>{{ session.title || '未命名任务' }}</strong>
              <small>{{ formatSessionTime(session.updated_at) }}</small>
            </span>
          </button>
        </div>
      </section>

      <ol class="ma-pipeline" aria-label="执行阶段">
        <li
          v-for="(stage, index) in stageDefinitions"
          :key="stage.key"
          :class="`is-${stageState(index)}`"
          :aria-current="stageState(index) === 'active' ? 'step' : undefined"
        >
          <span class="ma-stage-icon">
            <Check v-if="stageState(index) === 'complete'" :size="16" weight="bold" aria-hidden="true" />
            <WarningCircle v-else-if="stageState(index) === 'error'" :size="17" weight="fill" aria-hidden="true" />
            <Stop v-else-if="stageState(index) === 'stopped'" :size="16" weight="fill" aria-hidden="true" />
            <component v-else :is="stage.icon" :size="17" aria-hidden="true" />
          </span>
          <span class="ma-stage-copy">
            <strong>{{ stage.label }}</strong>
            <small>{{ stage.note }}</small>
          </span>
        </li>
      </ol>

      <div class="ma-architecture">
        <div>
          <span><Brain :size="17" aria-hidden="true" />主智能体</span>
          <small>分析、规划、调度、综合</small>
        </div>
        <div>
          <span><Robot :size="17" aria-hidden="true" />子智能体</span>
          <small>分解、执行、评估、汇报</small>
        </div>
      </div>
    </aside>

    <main class="ma-main">
      <header class="ma-header">
        <div>
          <h2>协作任务</h2>
          <p>把复杂目标拆解为可追踪的智能体执行过程</p>
        </div>
        <div class="ma-header-actions">
          <button
            v-if="hasRun && !running"
            class="ma-icon-button"
            type="button"
            aria-label="新建任务"
            title="新建任务"
            @click="resetRun"
          >
            <Plus :size="18" aria-hidden="true" />
          </button>
          <span class="ma-runtime-status" :class="`is-${runState}`" role="status" aria-live="polite">
            <CircleNotch v-if="running" class="ma-spinning" :size="15" aria-hidden="true" />
            <WarningCircle v-else-if="runState === 'error'" :size="15" weight="fill" aria-hidden="true" />
            <Stop v-else-if="runState === 'stopped'" :size="14" weight="fill" aria-hidden="true" />
            <CheckCircle v-else :size="15" weight="fill" aria-hidden="true" />
            {{ statusLabel }}
          </span>
        </div>
      </header>

      <div ref="outputPanel" class="ma-output" @scroll="handleOutputScroll">
        <section v-if="!hasRun" class="ma-empty">
          <div class="ma-empty-copy">
            <span class="ma-empty-mark"><Strategy :size="34" weight="duotone" aria-hidden="true" /></span>
            <h2>把复杂问题交给一支智能体队伍</h2>
            <p>描述目标和期望结果，编排器会判断协作范围、生成计划并汇总每个执行结果。</p>
          </div>

          <div class="ma-prompt-starters" aria-label="任务示例">
            <button
              v-for="prompt in promptStarters"
              :key="prompt.label"
              type="button"
              @click="choosePrompt(prompt.value)"
            >
              <span>
                <strong>{{ prompt.label }}</strong>
                <small>{{ prompt.description }}</small>
              </span>
              <CaretRight :size="17" aria-hidden="true" />
            </button>
          </div>
        </section>

        <template v-else>
          <article class="ma-user-brief">
            <span class="ma-brief-icon"><Stack :size="19" aria-hidden="true" /></span>
            <div>
              <span>任务输入</span>
              <p>{{ currentTask }}</p>
            </div>
          </article>

          <div class="ma-results-grid">
            <section class="ma-trace-panel" aria-labelledby="ma-trace-title">
              <header class="ma-panel-header">
                <div>
                  <ListChecks :size="19" aria-hidden="true" />
                  <h3 id="ma-trace-title">执行追踪</h3>
                </div>
                <span>{{ traceEvents.length }} 条更新</span>
              </header>

              <div v-if="!traceEvents.length && running" class="ma-trace-skeleton" aria-label="正在建立执行计划">
                <span></span><span></span><span></span>
              </div>

              <div v-else class="ma-timeline">
                <article
                  v-for="event in traceEvents"
                  :key="event.id"
                  class="ma-trace-event"
                  :class="eventTone(event)"
                >
                  <span class="ma-trace-icon">
                    <component :is="eventIcon(event)" :size="17" aria-hidden="true" />
                  </span>
                  <div class="ma-trace-copy">
                    <header>
                      <strong>{{ eventTitle(event) }}</strong>
                      <time>{{ elapsedLabel(event) }}</time>
                    </header>
                    <p v-if="eventDetail(event)">{{ eventDetail(event) }}</p>

                    <ol v-if="planSteps(event).length" class="ma-plan-list">
                      <li v-for="step in planSteps(event)" :key="step.stepId">
                        <span>{{ step.stepId }}</span>
                        <div>
                          <strong>{{ step.description }}</strong>
                          <small v-if="step.subagentType">{{ formatAgent(step.subagentType) }}</small>
                        </div>
                      </li>
                    </ol>

                    <span v-if="complexityLabel(event)" class="ma-complexity">
                      {{ complexityLabel(event) }}
                    </span>
                  </div>
                </article>
              </div>
            </section>

            <section class="ma-answer-panel" aria-labelledby="ma-answer-title">
              <header class="ma-panel-header">
                <div>
                  <Sparkle :size="19" weight="fill" aria-hidden="true" />
                  <h3 id="ma-answer-title">最终交付</h3>
                </div>
                <button
                  v-if="answerText"
                  class="ma-copy-button"
                  type="button"
                  :aria-label="copied ? '已复制结果' : '复制结果'"
                  @click="copyAnswer"
                >
                  <Check v-if="copied" :size="15" weight="bold" aria-hidden="true" />
                  <Copy v-else :size="15" aria-hidden="true" />
                  {{ copied ? '已复制' : '复制' }}
                </button>
              </header>

              <div v-if="errorMessage" class="ma-answer-state is-error" role="alert">
                <WarningCircle :size="27" weight="duotone" aria-hidden="true" />
                <strong>任务执行未完成</strong>
                <p>{{ errorMessage }}</p>
              </div>

              <div v-else-if="cancelledMessage" class="ma-answer-state is-stopped" role="status">
                <Stop :size="25" weight="duotone" aria-hidden="true" />
                <strong>任务已停止</strong>
                <p>{{ cancelledMessage }}</p>
              </div>

              <div v-else-if="answerText" class="message-markdown ma-answer-content" v-html="renderedAnswer"></div>

              <div v-else-if="running" class="ma-answer-skeleton" aria-label="正在等待综合结果">
                <div><span></span><span></span></div>
                <i></i><i></i><i></i><i></i>
              </div>

              <div v-else class="ma-answer-state">
                <Sparkle :size="27" aria-hidden="true" />
                <strong>暂无可展示结果</strong>
                <p>可以调整任务描述后重新运行。</p>
              </div>

              <footer v-if="isComplete && answerText" class="ma-answer-footer">
                <CheckCircle :size="16" weight="fill" aria-hidden="true" />
                本次协作任务已完成
              </footer>
            </section>
          </div>
        </template>
      </div>

      <footer class="ma-composer-wrap">
        <form class="ma-composer" :class="{ 'is-focused': composerFocused }" @submit.prevent="submitTask">
          <label class="sr-only" for="multi-agent-task">描述需要多智能体协作的任务</label>
          <textarea
            id="multi-agent-task"
            ref="composerInput"
            v-model="taskInput"
            maxlength="4000"
            rows="2"
            placeholder="描述任务目标、可用信息和期望结果"
            :disabled="running"
            @focus="composerFocused = true"
            @blur="composerFocused = false"
            @keydown="handleComposerKeydown"
          ></textarea>
          <div class="ma-composer-tools">
            <span class="ma-composer-hint">Enter 运行，Shift+Enter 换行</span>
            <span class="ma-character-count">{{ taskInput.length }} / 4000</span>
            <button v-if="running" class="ma-stop-button" type="button" @click="stopRun">
              <Stop :size="16" weight="fill" aria-hidden="true" />
              停止
            </button>
            <button v-else class="ma-submit-button" type="submit" :disabled="!taskInput.trim()">
              <PaperPlaneTilt :size="17" weight="bold" aria-hidden="true" />
              运行
            </button>
          </div>
        </form>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, type Component } from 'vue'
import {
  PhArrowLeft as ArrowLeft,
  PhBrain as Brain,
  PhCaretRight as CaretRight,
  PhCheck as Check,
  PhCheckCircle as CheckCircle,
  PhCircleNotch as CircleNotch,
  PhClockCounterClockwise as ClockCounterClockwise,
  PhCopy as Copy,
  PhGitBranch as GitBranch,
  PhGraph as GraphIcon,
  PhListChecks as ListChecks,
  PhPaperPlaneTilt as PaperPlaneTilt,
  PhPlus as Plus,
  PhRobot as Robot,
  PhSparkle as Sparkle,
  PhStack as Stack,
  PhStop as Stop,
  PhStrategy as Strategy,
  PhWarningCircle as WarningCircle,
  PhWrench as Wrench,
} from '@phosphor-icons/vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { api, getSavedApiBase, STORAGE_KEYS } from '../api/client'
import type { Session } from '../types/api'

marked.setOptions({ breaks: true, gfm: true })

interface RunEvent {
  id: number
  type: string
  data: Record<string, unknown>
  receivedAt: number
}

interface PlanStepView {
  stepId: string
  description: string
  subagentType: string
}

type StageState = 'idle' | 'active' | 'complete' | 'error' | 'stopped'

const stageDefinitions: Array<{ key: string; label: string; note: string; icon: Component }> = [
  { key: 'analyze', label: '理解任务', note: '识别范围与复杂度', icon: Brain },
  { key: 'plan', label: '制定计划', note: '拆分步骤与依赖', icon: ListChecks },
  { key: 'execute', label: '协作执行', note: '调度子智能体', icon: GitBranch },
  { key: 'synthesize', label: '综合结果', note: '汇总并形成交付', icon: Sparkle },
]

const promptStarters = [
  {
    label: '梳理方案与风险',
    description: '拆解目标、约束和潜在风险，输出可执行方案',
    value: '请梳理这个任务的目标、关键约束和潜在风险，分工验证后给出一份可执行方案。',
  },
  {
    label: '比较多种选择',
    description: '从多个维度并行分析，汇总差异和建议',
    value: '请对我提供的几种选择做多维度比较，分别分析优缺点、风险和适用条件，最后给出建议。',
  },
  {
    label: '分析问题根因',
    description: '分工核查假设，形成有依据的结论',
    value: '请分析这个问题的可能根因，安排不同子任务核查关键假设，并汇总为结论和后续行动。',
  },
]

const taskInput = ref('')
const currentTask = ref('')
const running = ref(false)
const events = ref<RunEvent[]>([])
const outputPanel = ref<HTMLElement | null>(null)
const composerInput = ref<HTMLTextAreaElement | null>(null)
const composerFocused = ref(false)
const copied = ref(false)
const runStartedAt = ref(0)
const shouldAutoScroll = ref(true)
const activeController = ref<AbortController | null>(null)
const activeSessionId = ref('')
const multiAgentSessions = ref<Session[]>([])
const sessionsLoading = ref(false)
const sessionsError = ref('')
const loadingSessionId = ref('')
let eventSequence = 0
let copyTimer: number | undefined

const hasRun = computed(() => Boolean(currentTask.value) || events.value.length > 0)
const errorEvent = computed(() => [...events.value].reverse().find((event) => event.type === 'error'))
const errorMessage = computed(() => dataString(errorEvent.value, 'message') || '')
const cancelledEvent = computed(() => [...events.value].reverse().find((event) => event.type === 'cancelled'))
const cancelledMessage = computed(() => dataString(cancelledEvent.value, 'message') || '')
const isComplete = computed(() => events.value.some((event) => event.type === 'done') && !running.value)
const runState = computed(() => {
  if (running.value) return 'running'
  if (errorMessage.value) return 'error'
  if (cancelledMessage.value) return 'stopped'
  if (isComplete.value) return 'complete'
  return 'ready'
})
const statusLabel = computed(() => ({
  running: '执行中',
  error: '需要处理',
  stopped: '已停止',
  complete: '已完成',
  ready: '就绪',
})[runState.value])

const traceEvents = computed(() => events.value.filter((event) => !['start', 'token', 'done'].includes(event.type)))

const answerText = computed(() => {
  const synthesis = [...events.value].reverse().find((event) => event.type === 'synthesis_done')
  const synthesizedAnswer = dataString(synthesis, 'answer')
  if (synthesizedAnswer) return synthesizedAnswer

  let markerIndex = -1
  for (let index = events.value.length - 1; index >= 0; index -= 1) {
    const event = events.value[index]
    if (!event) continue
    const node = dataString(event, 'node')
    if (event.type === 'synthesizing' || (event.type === 'status' && ['synthesize', 'respond'].includes(node))) {
      markerIndex = index
      break
    }
  }

  const startIndex = markerIndex > 0 && events.value[markerIndex - 1]?.type === 'token'
    ? markerIndex - 1
    : Math.max(0, markerIndex + 1)
  const tokenEvents = events.value.slice(startIndex).filter((event) => (
    event.type === 'token' && (!dataString(event, 'agent') || dataString(event, 'agent') === 'main')
  ))
  return tokenEvents.map((event) => dataString(event, 'text')).join('')
})

const renderedAnswer = computed(() => DOMPurify.sanitize(marked.parse(answerText.value) as string))

const activeStageIndex = computed(() => {
  if (!hasRun.value) return -1
  let current = 0
  for (const event of events.value) {
    const node = dataString(event, 'node')
    if (event.type === 'done') current = stageDefinitions.length
    else if (event.type === 'synthesizing' || event.type === 'synthesis_done' || ['synthesize', 'respond'].includes(node)) current = 3
    else if (['dispatching', 'subagent_start', 'subagent_plan', 'subagent_step', 'subagent_progress', 'subagent_done', 'tool_call', 'tool_result'].includes(event.type) || node === 'execute') current = 2
    else if (event.type === 'plan_created' || ['plan', 'replan'].includes(node)) current = 1
    else if (event.type === 'analyzing' || event.type === 'analysis_done' || node === 'analyze') current = 0
  }
  return current
})

function stageState(index: number): StageState {
  if (!hasRun.value) return 'idle'
  if (index < activeStageIndex.value || activeStageIndex.value >= stageDefinitions.length) return 'complete'
  if (index === activeStageIndex.value && errorMessage.value) return 'error'
  if (index === activeStageIndex.value && cancelledMessage.value) return 'stopped'
  if (index === activeStageIndex.value) return 'active'
  return 'idle'
}

function dataString(event: RunEvent | undefined, key: string): string {
  const value = event?.data[key]
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function dataNumber(event: RunEvent, key: string): number | null {
  const value = event.data[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function eventTitle(event: RunEvent): string {
  const titles: Record<string, string> = {
    status: dataString(event, 'node') === 'replan' ? '调整执行计划' : '主智能体更新',
    analyzing: '分析任务',
    analysis_done: '任务分析完成',
    plan_created: '执行计划已生成',
    dispatching: '调度子智能体',
    subagent_start: `${formatAgent(dataString(event, 'subagent_type'))} 开始执行`,
    subagent_plan: `${formatAgent(dataString(event, 'subagent_type'))} 制定子计划`,
    subagent_step: `${formatAgent(dataString(event, 'subagent_type'))} 更新步骤`,
    subagent_progress: `${formatAgent(dataString(event, 'subagent_type'))} 更新进度`,
    subagent_done: `${formatAgent(dataString(event, 'subagent_type'))} ${event.data.success === false ? '执行失败' : '执行完成'}`,
    synthesizing: '综合执行结果',
    synthesis_done: '最终结果已生成',
    tool_call: `调用工具 ${dataString(event, 'tool_name')}`,
    tool_result: `工具 ${dataString(event, 'tool_name')} 返回结果`,
    error: '执行发生错误',
    cancelled: '任务已停止',
  }
  return titles[event.type] || '执行状态更新'
}

function eventDetail(event: RunEvent): string {
  if (event.type === 'analysis_done') {
    return dataString(event, 'task_summary') || '已完成任务范围与协作需求分析。'
  }
  if (event.type === 'plan_created') {
    const count = planSteps(event).length
    return count ? `已生成 ${count} 个可执行步骤。` : '执行计划已准备。'
  }
  if (event.type === 'dispatching') {
    const agent = formatAgent(dataString(event, 'subagent_type'))
    const step = dataString(event, 'step_id')
    return step ? `${agent} 正在处理计划步骤 ${step}。` : `${agent} 正在接收任务。`
  }
  if (event.type === 'subagent_done') return dataString(event, 'result_summary')
  if (event.type === 'subagent_step') {
    return dataString(event, 'description') || `当前状态：${dataString(event, 'status') || '执行中'}`
  }
  if (event.type === 'subagent_progress') {
    const progress = dataNumber(event, 'progress')
    return progress === null ? '子智能体正在执行。' : `当前进度 ${Math.round(progress)}%。`
  }
  if (event.type === 'tool_call') return '子智能体正在使用可用工具处理当前步骤。'
  if (event.type === 'tool_result') return dataString(event, 'result_summary') || '工具调用已完成。'
  if (event.type === 'synthesis_done') return '所有可用结果已完成汇总。'
  if (event.type === 'cancelled') return dataString(event, 'message')
  return dataString(event, 'message') || dataString(event, 'reason')
}

function eventIcon(event: RunEvent): Component {
  const icons: Record<string, Component> = {
    analyzing: Brain,
    analysis_done: CheckCircle,
    plan_created: ListChecks,
    dispatching: GitBranch,
    subagent_start: Robot,
    subagent_plan: ListChecks,
    subagent_step: Robot,
    subagent_progress: CircleNotch,
    subagent_done: event.data.success === false ? WarningCircle : CheckCircle,
    synthesizing: Sparkle,
    synthesis_done: CheckCircle,
    tool_call: Wrench,
    tool_result: Wrench,
    error: WarningCircle,
    cancelled: Stop,
  }
  return icons[event.type] || (dataString(event, 'node') === 'replan' ? GitBranch : CircleNotch)
}

function eventTone(event: RunEvent): string {
  if (event.type === 'error' || event.type === 'cancelled' || event.data.success === false) return 'is-error'
  if (['analysis_done', 'subagent_done', 'synthesis_done'].includes(event.type)) return 'is-success'
  if (['plan_created', 'dispatching', 'subagent_start', 'subagent_plan', 'synthesizing'].includes(event.type)) return 'is-accent'
  return ''
}

function complexityLabel(event: RunEvent): string {
  if (event.type !== 'analysis_done') return ''
  const complexity = dataString(event, 'complexity').toLowerCase()
  return ({ simple: '简单任务', medium: '中等复杂度', complex: '复杂任务' } as Record<string, string>)[complexity] || ''
}

function planSteps(event: RunEvent): PlanStepView[] {
  const rawPlan = event.data.plan
  if (!Array.isArray(rawPlan)) return []
  return rawPlan.flatMap((rawStep, index) => {
    if (!rawStep || typeof rawStep !== 'object') return []
    const step = rawStep as Record<string, unknown>
    const description = typeof step.description === 'string' ? step.description : ''
    if (!description) return []
    const rawStepId = step.step_id
    const stepId = typeof rawStepId === 'string' || typeof rawStepId === 'number' ? String(rawStepId) : String(index + 1)
    return [{
      stepId,
      description,
      subagentType: typeof step.subagent_type === 'string' ? step.subagent_type : '',
    }]
  })
}

function formatAgent(value: string): string {
  if (!value || value === 'main') return '主智能体'
  if (value === 'general_assistant') return '通用助手'
  return value.replaceAll('_', ' ')
}

function elapsedLabel(event: RunEvent): string {
  if (!runStartedAt.value) return '刚刚'
  const seconds = Math.max(0, (event.receivedAt - runStartedAt.value) / 1000)
  return `+${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`
}

function pushEvent(type: string, data: Record<string, unknown>) {
  if (type === 'done' && events.value.some((event) => event.type === 'done')) return
  events.value.push({ id: ++eventSequence, type, data, receivedAt: Date.now() })
  scrollToBottom()
}

function parseSseFrame(frame: string): { type: string; data: Record<string, unknown> } | null {
  let type = 'message'
  const dataLines: string[] = []
  for (const rawLine of frame.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue
    const separator = rawLine.indexOf(':')
    const field = separator === -1 ? rawLine : rawLine.slice(0, separator)
    let value = separator === -1 ? '' : rawLine.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') type = value
    if (field === 'data') dataLines.push(value)
  }
  if (!dataLines.length) return null
  const rawData = dataLines.join('\n')
  try {
    const parsed = JSON.parse(rawData) as unknown
    return { type, data: parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : { text: parsed } }
  } catch {
    return { type, data: { text: rawData } }
  }
}

function handleOutputScroll() {
  const panel = outputPanel.value
  if (!panel) return
  shouldAutoScroll.value = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 96
}

function scrollToBottom(force = false) {
  nextTick(() => {
    const panel = outputPanel.value
    if (!panel || (!force && !shouldAutoScroll.value)) return
    panel.scrollTop = panel.scrollHeight
  })
}

function choosePrompt(value: string) {
  taskInput.value = value
  nextTick(() => composerInput.value?.focus())
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void submitTask()
}

function resetRun() {
  if (running.value) stopRun()
  events.value = []
  currentTask.value = ''
  activeSessionId.value = ''
  shouldAutoScroll.value = true
  nextTick(() => composerInput.value?.focus())
}

function stopRun() {
  const sessionId = activeSessionId.value
  if (sessionId) {
    const headers = new Headers()
    const apiKey = localStorage.getItem(STORAGE_KEYS.apiKey)
    if (apiKey) headers.set('Authorization', `Bearer ${apiKey}`)
    void fetch(
      `${getSavedApiBase()}/multi-agent/chat/${encodeURIComponent(sessionId)}/cancel`,
      { method: 'POST', headers },
    ).catch(() => undefined)
  }
  activeController.value?.abort()
}

function formatSessionTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

async function loadMultiAgentSessions(showError = true) {
  sessionsLoading.value = true
  sessionsError.value = ''
  try {
    multiAgentSessions.value = await api.listSessions('multi_agent')
  } catch (error) {
    sessionsError.value = error instanceof Error ? error.message : '历史任务加载失败'
    if (!showError) sessionsError.value = ''
  } finally {
    sessionsLoading.value = false
  }
}

async function loadHistoricalSession(session: Session) {
  if (running.value) return
  loadingSessionId.value = session.session_id
  activeSessionId.value = session.session_id
  events.value = []
  currentTask.value = session.title || '未命名任务'
  runStartedAt.value = new Date(session.created_at).getTime() || Date.now()
  try {
    const messages = await api.getMessages(session.session_id)
    const userMessage = messages.find((message) => message.role === 'user')
    const answer = [...messages].reverse().find((message) => message.role === 'assistant')
    currentTask.value = userMessage?.content || currentTask.value
    if (answer?.content) pushEvent('synthesis_done', { answer: answer.content })
    pushEvent('done', { session_id: session.session_id })
    scrollToBottom(true)
  } catch (error) {
    pushEvent('error', {
      message: error instanceof Error ? error.message : '无法加载历史任务',
    })
  } finally {
    loadingSessionId.value = ''
  }
}

async function copyAnswer() {
  if (!answerText.value) return
  await navigator.clipboard.writeText(answerText.value)
  copied.value = true
  window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => { copied.value = false }, 1600)
}

async function submitTask() {
  const query = taskInput.value.trim()
  if (!query || running.value) return

  const controller = new AbortController()
  activeController.value = controller
  running.value = true
  currentTask.value = query
  taskInput.value = ''
  events.value = []
  activeSessionId.value = ''
  runStartedAt.value = Date.now()
  shouldAutoScroll.value = true
  copied.value = false
  scrollToBottom(true)

  const headers = new Headers({
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
  })
  const apiKey = localStorage.getItem(STORAGE_KEYS.apiKey)
  if (apiKey) headers.set('Authorization', `Bearer ${apiKey}`)

  try {
    const response = await fetch(`${getSavedApiBase()}/multi-agent/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ query }),
      signal: controller.signal,
    })

    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event('mka:unauthorized'))
      let message = `${response.status} ${response.statusText}`.trim()
      try {
        const body = await response.json() as { detail?: string; error?: { message?: string } }
        message = body.error?.message || body.detail || message
      } catch {
        // 非 JSON 错误响应使用 HTTP 状态文本。
      }
      throw new Error(message || '请求失败')
    }
    if (!response.body) throw new Error('浏览器未提供流式响应内容')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let terminalEventReceived = false

    while (!terminalEventReceived) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })

      while (true) {
        const boundary = /\r?\n\r?\n/.exec(buffer)
        if (!boundary || boundary.index === undefined) break
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const parsed = parseSseFrame(frame)
        if (!parsed) continue
        pushEvent(parsed.type, parsed.data)
        if (parsed.type === 'start') {
          activeSessionId.value = typeof parsed.data.session_id === 'string'
            ? parsed.data.session_id
            : ''
        }
        if (parsed.type === 'done' || parsed.type === 'error') {
          terminalEventReceived = true
          break
        }
      }

      if (done) break
    }

    if (!terminalEventReceived && buffer.trim()) {
      const parsed = parseSseFrame(buffer)
      if (parsed) {
        pushEvent(parsed.type, parsed.data)
        if (parsed.type === 'start') {
          activeSessionId.value = typeof parsed.data.session_id === 'string'
            ? parsed.data.session_id
            : ''
        }
        terminalEventReceived = parsed.type === 'done' || parsed.type === 'error'
      }
    }

    if (terminalEventReceived) await reader.cancel()
    else if (!controller.signal.aborted) pushEvent('error', { message: '流式连接提前结束，请重试。' })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      pushEvent('cancelled', { message: '已停止本次任务。' })
    } else {
      pushEvent('error', { message: error instanceof Error ? error.message : '无法连接到多智能体服务' })
    }
  } finally {
    if (activeController.value === controller) activeController.value = null
    running.value = false
    await loadMultiAgentSessions(false)
    scrollToBottom()
  }
}

onMounted(() => {
  void loadMultiAgentSessions(false)
})

onBeforeUnmount(() => {
  activeController.value?.abort()
  window.clearTimeout(copyTimer)
})
</script>

<style scoped>
.ma-workspace {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-columns: 272px minmax(0, 1fr);
  overflow: hidden;
  background: var(--surface);
}

.ma-rail {
  min-height: 0;
  padding: 21px 18px 18px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
  background: var(--surface-raised);
}

.ma-back-link {
  width: fit-content;
  min-height: 32px;
  padding: 0 7px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 0.7rem;
  font-weight: 650;
  transition: color 150ms ease, background-color 150ms ease;
}

.ma-back-link:hover { color: var(--text); background: var(--surface-hover); }

.ma-agent-intro {
  margin-top: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.ma-agent-mark {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: var(--radius-md);
  color: var(--accent);
  background: var(--accent-soft);
}

.ma-product-name { color: var(--text-muted); font-size: 0.64rem; font-weight: 700; }
.ma-agent-intro h1 { margin-top: 2px; font-size: 1.04rem; letter-spacing: -0.025em; }
.ma-agent-description { margin-top: 14px; color: var(--text-soft); font-size: 0.73rem; line-height: 1.65; }

.ma-history { min-height: 0; margin-top: 22px; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 9px; }
.ma-history > header { display: flex; align-items: center; justify-content: space-between; }
.ma-history h2 { color: var(--text-soft); font-size: 0.7rem; }
.ma-history > header button { width: 27px; height: 27px; display: grid; place-items: center; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text-muted); cursor: pointer; }
.ma-history > header button:hover { background: var(--surface-hover); color: var(--text); }
.ma-history-list { max-height: 176px; overflow-y: auto; display: grid; gap: 4px; }
.ma-history-item { min-width: 0; min-height: 48px; padding: 7px 8px 7px 10px; display: flex; align-items: center; gap: 8px; border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--text-muted); text-align: left; cursor: pointer; }
.ma-history-item:hover, .ma-history-item.is-active { border-color: var(--line); background: var(--surface-hover); color: var(--text); }
.ma-history-item:disabled { cursor: default; opacity: 0.66; }
.ma-history-item > span { min-width: 0; flex: 1; display: grid; gap: 3px; }
.ma-history-item strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-soft); font-size: 0.66rem; }
.ma-history-item small { font-size: 0.58rem; }
.ma-history-state { padding: 8px 2px; color: var(--text-muted); font-size: 0.63rem; }
.ma-history-state.is-error { color: var(--danger); }

.ma-pipeline {
  margin: 22px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
}

.ma-pipeline li {
  min-height: 67px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  position: relative;
  color: var(--text-muted);
}

.ma-pipeline li:not(:last-child)::after {
  content: '';
  width: 1px;
  position: absolute;
  top: 33px;
  bottom: 0;
  left: 16px;
  background: var(--line-strong);
}

.ma-pipeline li.is-complete:not(:last-child)::after { background: var(--success); }

.ma-stage-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  position: relative;
  z-index: 1;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text-muted);
}

.ma-stage-copy { min-width: 0; padding-top: 2px; display: grid; gap: 4px; }
.ma-stage-copy strong { color: var(--text-soft); font-size: 0.73rem; }
.ma-stage-copy small { font-size: 0.62rem; }
.ma-pipeline li.is-active .ma-stage-icon { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.ma-pipeline li.is-active .ma-stage-copy strong { color: var(--text); }
.ma-pipeline li.is-complete .ma-stage-icon { border-color: color-mix(in srgb, var(--success) 30%, var(--line)); background: var(--success-soft); color: var(--success); }
.ma-pipeline li.is-error .ma-stage-icon { border-color: color-mix(in srgb, var(--danger) 30%, var(--line)); background: var(--danger-soft); color: var(--danger); }
.ma-pipeline li.is-stopped .ma-stage-icon { border-color: color-mix(in srgb, var(--warning) 30%, var(--line)); background: var(--warning-soft); color: var(--warning); }

.ma-architecture {
  margin-top: auto;
  padding-top: 15px;
  display: grid;
  gap: 11px;
  border-top: 1px solid var(--line);
}

.ma-architecture div { display: grid; gap: 4px; }
.ma-architecture span { display: flex; align-items: center; gap: 7px; color: var(--text-soft); font-size: 0.7rem; font-weight: 680; }
.ma-architecture svg { color: var(--accent); }
.ma-architecture small { padding-left: 24px; color: var(--text-muted); font-size: 0.61rem; }

.ma-main {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: 72px minmax(0, 1fr) auto;
  overflow: hidden;
}

.ma-header {
  min-width: 0;
  padding: 0 clamp(20px, 3vw, 36px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

.ma-header > div:first-child { min-width: 0; display: grid; gap: 4px; }
.ma-header h2 { font-size: 0.94rem; letter-spacing: -0.02em; }
.ma-header p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 0.66rem; }
.ma-header-actions { display: flex; align-items: center; gap: 9px; }

.ma-icon-button,
.ma-copy-button,
.ma-stop-button,
.ma-submit-button {
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background-color 150ms ease, border-color 150ms ease, color 150ms ease, transform 100ms ease;
}

.ma-icon-button:active,
.ma-copy-button:active,
.ma-stop-button:active,
.ma-submit-button:active:not(:disabled) { transform: translateY(1px); }

.ma-icon-button {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-muted);
}

.ma-icon-button:hover { background: var(--surface-hover); color: var(--text); }

.ma-runtime-status {
  min-height: 30px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-soft);
  font-size: 0.66rem;
  font-weight: 700;
  white-space: nowrap;
}

.ma-runtime-status.is-running { background: var(--warning-soft); color: var(--warning); }
.ma-runtime-status.is-complete { background: var(--success-soft); color: var(--success); }
.ma-runtime-status.is-error { background: var(--danger-soft); color: var(--danger); }
.ma-runtime-status.is-stopped { background: var(--warning-soft); color: var(--warning); }
.ma-spinning { animation: ma-spin 0.9s linear infinite; }
@keyframes ma-spin { to { transform: rotate(360deg); } }

.ma-output {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: clamp(20px, 3vw, 36px);
  background: var(--bg);
  scroll-behavior: smooth;
}

.ma-empty {
  width: min(100%, 1080px);
  min-height: 100%;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(360px, 1.1fr);
  align-items: center;
  gap: clamp(38px, 6vw, 84px);
  padding: 32px 0 72px;
}

.ma-empty-copy { max-width: 520px; }
.ma-empty-mark { width: 62px; height: 62px; display: grid; place-items: center; margin-bottom: 24px; border-radius: var(--radius-lg); background: var(--accent-soft); color: var(--accent); }
.ma-empty h2 { max-width: 14ch; font-size: clamp(2rem, 4vw, 3.5rem); line-height: 1.05; letter-spacing: -0.055em; font-weight: 710; }
.ma-empty-copy p { max-width: 47ch; margin-top: 17px; color: var(--text-soft); font-size: 0.84rem; line-height: 1.72; }

.ma-prompt-starters { display: grid; gap: 9px; }
.ma-prompt-starters button {
  min-height: 82px;
  padding: 15px 15px 15px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-soft);
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: background-color 160ms ease, border-color 160ms ease, transform 130ms ease;
}

.ma-prompt-starters button:first-child { min-height: 104px; }
.ma-prompt-starters button:hover { background: var(--surface-raised); border-color: var(--line-strong); transform: translateY(-1px); }
.ma-prompt-starters button:active { transform: translateY(1px); }
.ma-prompt-starters button > span { display: grid; gap: 6px; }
.ma-prompt-starters strong { color: var(--text); font-size: 0.8rem; }
.ma-prompt-starters small { color: var(--text-muted); font-size: 0.67rem; line-height: 1.5; }
.ma-prompt-starters svg { flex: 0 0 auto; color: var(--accent); }

.ma-user-brief {
  width: min(100%, 1180px);
  margin: 0 auto 16px;
  padding: 16px 18px;
  display: grid;
  grid-template-columns: 37px minmax(0, 1fr);
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.ma-brief-icon { width: 37px; height: 37px; display: grid; place-items: center; border-radius: 10px; color: var(--accent); background: var(--accent-soft); }
.ma-user-brief > div { min-width: 0; display: grid; gap: 5px; }
.ma-user-brief span:not(.ma-brief-icon) { color: var(--text-muted); font-size: 0.62rem; font-weight: 700; }
.ma-user-brief p { color: var(--text); font-size: 0.82rem; line-height: 1.62; overflow-wrap: anywhere; }

.ma-results-grid {
  width: min(100%, 1180px);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(330px, 0.82fr) minmax(0, 1.18fr);
  align-items: start;
  gap: 16px;
}

.ma-trace-panel,
.ma-answer-panel {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.ma-answer-panel { position: sticky; top: 0; }
.ma-panel-header { min-height: 57px; padding: 0 17px; display: flex; align-items: center; justify-content: space-between; gap: 14px; border-bottom: 1px solid var(--line); background: var(--surface-raised); }
.ma-panel-header > div { display: flex; align-items: center; gap: 8px; }
.ma-panel-header svg { color: var(--accent); }
.ma-panel-header h3 { font-size: 0.79rem; letter-spacing: -0.01em; }
.ma-panel-header > span { color: var(--text-muted); font-size: 0.62rem; }

.ma-copy-button {
  min-height: 31px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.65rem;
}

.ma-copy-button:hover { background: var(--surface-hover); color: var(--text); }

.ma-timeline { padding: 8px 17px 15px; }
.ma-trace-event {
  min-width: 0;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 10px;
  padding: 11px 0 12px;
  position: relative;
  animation: ma-enter 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes ma-enter { from { opacity: 0; transform: translateY(4px); } }
.ma-trace-event:not(:last-child)::after { content: ''; width: 1px; position: absolute; top: 38px; bottom: -1px; left: 14px; background: var(--line); }
.ma-trace-icon { width: 30px; height: 30px; display: grid; place-items: center; position: relative; z-index: 1; border-radius: 9px; background: var(--surface-subtle); color: var(--text-muted); }
.ma-trace-event.is-accent .ma-trace-icon { background: var(--accent-soft); color: var(--accent); }
.ma-trace-event.is-success .ma-trace-icon { background: var(--success-soft); color: var(--success); }
.ma-trace-event.is-error .ma-trace-icon { background: var(--danger-soft); color: var(--danger); }
.ma-trace-copy { min-width: 0; padding-top: 3px; }
.ma-trace-copy > header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.ma-trace-copy > header strong { color: var(--text); font-size: 0.72rem; }
.ma-trace-copy time { flex: 0 0 auto; color: var(--text-muted); font: 0.58rem 'Cascadia Code', 'SFMono-Regular', monospace; }
.ma-trace-copy > p { margin-top: 5px; color: var(--text-soft); font-size: 0.68rem; line-height: 1.55; overflow-wrap: anywhere; }

.ma-plan-list { margin: 11px 0 1px; padding: 0; list-style: none; display: grid; gap: 8px; }
.ma-plan-list li { min-width: 0; display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 8px; }
.ma-plan-list li > span { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 7px; background: var(--surface-subtle); color: var(--text-muted); font: 0.58rem 'Cascadia Code', 'SFMono-Regular', monospace; }
.ma-plan-list li > div { min-width: 0; display: grid; gap: 3px; }
.ma-plan-list strong { color: var(--text-soft); font-size: 0.66rem; line-height: 1.45; }
.ma-plan-list small { width: fit-content; color: var(--accent); font-size: 0.58rem; font-weight: 650; }
.ma-complexity { display: inline-flex; margin-top: 8px; padding: 4px 7px; border-radius: 6px; background: var(--accent-soft); color: var(--accent); font-size: 0.58rem; font-weight: 700; }

.ma-trace-skeleton { padding: 20px 18px; display: grid; gap: 13px; }
.ma-trace-skeleton span { display: block; height: 48px; border-radius: var(--radius-sm); background: var(--surface-subtle); animation: ma-skeleton 1.3s ease-in-out infinite alternate; }
.ma-trace-skeleton span:nth-child(2) { width: 88%; }.ma-trace-skeleton span:nth-child(3) { width: 72%; }
@keyframes ma-skeleton { to { opacity: 0.45; } }

.ma-answer-content { min-height: 260px; padding: 24px 25px 28px; font-size: 0.82rem; }
.ma-answer-content:deep(h1:first-child),
.ma-answer-content:deep(h2:first-child),
.ma-answer-content:deep(h3:first-child) { margin-top: 0; }
.ma-answer-content:deep(p:last-child) { margin-bottom: 0; }

.ma-answer-skeleton { min-height: 300px; padding: 27px 25px; display: grid; align-content: start; gap: 13px; }
.ma-answer-skeleton div { margin-bottom: 6px; display: flex; align-items: center; gap: 9px; }
.ma-answer-skeleton span,
.ma-answer-skeleton i { display: block; height: 13px; border-radius: 5px; background: var(--surface-subtle); animation: ma-skeleton 1.3s ease-in-out infinite alternate; }
.ma-answer-skeleton span:first-child { width: 41%; height: 19px; }.ma-answer-skeleton span:last-child { width: 16%; height: 19px; }
.ma-answer-skeleton i:nth-of-type(1) { width: 96%; }.ma-answer-skeleton i:nth-of-type(2) { width: 91%; }.ma-answer-skeleton i:nth-of-type(3) { width: 78%; }.ma-answer-skeleton i:nth-of-type(4) { width: 86%; }

.ma-answer-state { min-height: 300px; padding: 34px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: var(--text-muted); }
.ma-answer-state svg { margin-bottom: 12px; }
.ma-answer-state strong { color: var(--text); font-size: 0.8rem; }
.ma-answer-state p { max-width: 38ch; margin-top: 6px; font-size: 0.68rem; line-height: 1.55; }
.ma-answer-state.is-error { color: var(--danger); background: color-mix(in srgb, var(--danger-soft) 38%, var(--surface)); }
.ma-answer-state.is-error strong { color: var(--danger); }
.ma-answer-state.is-stopped { color: var(--warning); background: color-mix(in srgb, var(--warning-soft) 38%, var(--surface)); }
.ma-answer-state.is-stopped strong { color: var(--warning); }
.ma-answer-footer { min-height: 42px; padding: 0 17px; display: flex; align-items: center; gap: 7px; border-top: 1px solid var(--line); background: var(--success-soft); color: var(--success); font-size: 0.64rem; font-weight: 680; }

.ma-composer-wrap { padding: 11px clamp(20px, 3vw, 36px) 13px; border-top: 1px solid var(--line); background: var(--surface); }
.ma-composer { width: min(100%, 900px); margin: 0 auto; padding: 10px 11px 9px 14px; border: 1px solid var(--line-strong); border-radius: var(--radius-lg); background: var(--surface-raised); box-shadow: var(--shadow-sm); transition: border-color 150ms ease, box-shadow 150ms ease; }
.ma-composer.is-focused { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 11%, transparent), var(--shadow-sm); }
.ma-composer textarea { width: 100%; min-height: 38px; max-height: 160px; padding: 3px 2px; resize: vertical; border: 0; outline: 0; background: transparent; color: var(--text); font-size: 0.82rem; line-height: 1.55; }
.ma-composer textarea::placeholder { color: var(--text-muted); }
.ma-composer textarea:disabled { cursor: not-allowed; opacity: 0.68; }
.ma-composer-tools { min-height: 35px; margin-top: 7px; display: flex; align-items: center; gap: 10px; }
.ma-composer-hint { color: var(--text-muted); font-size: 0.61rem; }
.ma-character-count { margin-left: auto; color: var(--text-muted); font: 0.58rem 'Cascadia Code', 'SFMono-Regular', monospace; }
.ma-stop-button,
.ma-submit-button { min-height: 35px; padding: 0 12px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; white-space: nowrap; font-size: 0.72rem; font-weight: 700; }
.ma-stop-button { border: 1px solid var(--line-strong); background: var(--surface); color: var(--danger); }
.ma-stop-button:hover { background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 26%, var(--line)); }
.ma-submit-button { border: 1px solid var(--accent); background: var(--accent); color: var(--accent-contrast); }
.ma-submit-button:hover:not(:disabled) { border-color: var(--accent-hover); background: var(--accent-hover); }
.ma-submit-button:disabled { opacity: 0.46; cursor: not-allowed; }

@media (max-width: 1180px) {
  .ma-results-grid { grid-template-columns: 1fr; }
  .ma-answer-panel { position: static; }
}

@media (max-width: 960px) {
  .ma-workspace { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .ma-rail { padding: 14px 20px; display: grid; grid-template-columns: auto minmax(180px, 0.7fr) minmax(430px, 1.3fr); align-items: center; gap: 17px; border-right: 0; border-bottom: 1px solid var(--line); }
  .ma-back-link { display: none; }
  .ma-agent-intro { margin: 0; }
  .ma-agent-description, .ma-architecture { display: none; }
  .ma-history { display: none; }
  .ma-pipeline { margin: 0; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .ma-pipeline li { min-height: auto; grid-template-columns: 30px minmax(0, 1fr); gap: 7px; }
  .ma-pipeline li:not(:last-child)::after { width: auto; height: 1px; top: 15px; right: -1px; bottom: auto; left: 29px; }
  .ma-stage-icon { width: 30px; height: 30px; border-radius: 9px; }
  .ma-stage-copy { padding-top: 0; }
  .ma-stage-copy strong { font-size: 0.65rem; }
  .ma-stage-copy small { display: none; }
}

@media (max-width: 820px) {
  .ma-workspace { height: calc(100dvh - 124px); }
  .ma-rail { grid-template-columns: minmax(150px, 0.65fr) minmax(360px, 1.35fr); padding: 12px 14px; }
  .ma-agent-mark { width: 40px; height: 40px; }
  .ma-product-name { display: none; }
  .ma-agent-intro h1 { margin-top: 0; font-size: 0.82rem; }
  .ma-header { padding: 0 15px; }
  .ma-output { padding: 18px 14px; }
  .ma-composer-wrap { padding: 9px 11px 10px; }
}

@media (max-width: 640px) {
  .ma-rail { grid-template-columns: 1fr; gap: 10px; }
  .ma-agent-intro { display: none; }
  .ma-stage-copy strong { font-size: 0.59rem; }
  .ma-header p { display: none; }
  .ma-header h2 { font-size: 0.86rem; }
  .ma-empty { grid-template-columns: 1fr; align-content: start; gap: 30px; padding: 28px 2px 48px; }
  .ma-empty-mark { width: 52px; height: 52px; margin-bottom: 19px; }
  .ma-empty h2 { font-size: clamp(1.85rem, 9vw, 2.55rem); }
  .ma-prompt-starters button, .ma-prompt-starters button:first-child { min-height: 76px; }
  .ma-user-brief { padding: 13px; grid-template-columns: 32px minmax(0, 1fr); }
  .ma-brief-icon { width: 32px; height: 32px; }
  .ma-panel-header { padding: 0 14px; }
  .ma-timeline { padding-inline: 14px; }
  .ma-answer-content { min-height: 220px; padding: 20px 17px 24px; }
  .ma-answer-state, .ma-answer-skeleton { min-height: 235px; padding: 24px 18px; }
  .ma-composer { border-radius: var(--radius-md); }
  .ma-composer-hint { display: none; }
  .ma-character-count { margin-left: 0; }
  .ma-stop-button, .ma-submit-button { margin-left: auto; }
}
</style>
