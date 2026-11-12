<template>
  <div class="compare">
    <PageHeader
      eyebrow="04 · 周度批次对比"
      title="批次对比"
      description="新补入小票与上周发布批次按规则组合逐一比对：新增 / 消失 / 增强 / 减弱一眼分清；两批样本小票数与时间范围同时标出，消失规则不会进入新陈列建议。"
    >
      <template #actions>
        <button
          v-if="canRun"
          class="btn btn--mint"
          type="button"
          data-test="toggle-import"
          @click="showImport = !showImport"
        >
          {{ showImport ? '收起导入' : '补入小票批次' }}
        </button>
      </template>
    </PageHeader>

    <div v-if="!canRead" class="notice notice--tag">
      店长账号可查看批次对比结论，但小票补入、挖掘与重新对比仅对品类运营 / 总监开放。
    </div>

    <ErrorNotice v-if="store.error" :message="store.error" />
    <div v-if="store.notice" class="notice notice--mint" data-test="compare-notice">{{ store.notice }}</div>

    <!-- 小票批次补入 -->
    <ShelfBand v-if="showImport && canRun" index="01" title="小票补入" caption="内容指纹去重：同一批小票重复导入只生效一次">
      <div class="import">
        <label class="import__field">
          <span class="label">批次编号</span>
          <input v-model="importForm.batch_code" class="field" placeholder="BATCH-2026-W47" />
        </label>
        <label class="import__field import__field--grow">
          <span class="label">备注</span>
          <input v-model="importForm.note" class="field" placeholder="本周补入说明（可选）" />
        </label>
        <label class="import__file">
          <span class="label">小票 JSON 文件</span>
          <input class="field" type="file" accept="application/json,.json" @change="onFile" />
        </label>
        <div class="import__actions">
          <button class="btn btn--mint btn--sm" type="button" :disabled="importing || !fileContent" @click="submitImport">
            {{ importing ? '导入中…' : `导入${parsedCount ? `（${parsedCount} 张小票）` : ''}` }}
          </button>
          <span v-if="importError" class="import__error">{{ importError }}</span>
        </div>
      </div>
      <p class="import__hint">
        文件格式：{ "batch_code"?: string, "baskets": [ { basket_no, store_code, store_name, store_tier, channel, basket_ts(带时区), net_amount, item_count, lines[] } ] }
      </p>
    </ShelfBand>

    <!-- 小票批次清单 -->
    <ShelfBand index="02" title="小票批次" caption="每批独立建档，标注样本小票数与时间范围；挖掘时可限定批次">
      <div v-if="batchStore.loading" class="muted">加载中…</div>
      <div v-else-if="!batchStore.batches.length" class="muted">还没有小票批次。</div>
      <table v-else class="grid-table" data-test="batch-table">
        <thead>
          <tr>
            <th>批次</th>
            <th>来源</th>
            <th class="ta-r">小票数</th>
            <th>时间范围</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batchStore.batches" :key="batch.id">
            <td class="mono">{{ batch.batch_code }}</td>
            <td><span class="chip">{{ BATCH_SOURCE_LABELS[batch.source] ?? batch.source }}</span></td>
            <td class="ta-r is-num">{{ formatInteger(batch.basket_count) }}</td>
            <td class="mono">{{ formatDate(batch.period_start) }} ~ {{ formatDate(batch.period_end) }}</td>
            <td class="muted-cell">{{ batch.note || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </ShelfBand>

    <!-- 对比设置 -->
    <ShelfBand index="03" title="选择对比批次" caption="基线建议选已发布工单的批次；同一对批次的结果落快照，重复请求完全一致">
      <div class="picker">
        <label class="picker__field">
          <span class="label">基线批次（上周发布）</span>
          <select v-model="baselineId" class="field" data-test="baseline-select">
            <option value="" disabled>选择已发布基线批次</option>
            <option v-for="run in store.baselines" :key="run.run_id" :value="run.run_id">
              {{ run.run_label }} · {{ run.basket_count }} 张 · {{ formatDate(run.sample_start) }}~{{ formatDate(run.sample_end) }}
            </option>
          </select>
        </label>
        <label class="picker__field">
          <span class="label">当前批次（新补入）</span>
          <select v-model="currentId" class="field" data-test="current-select">
            <option value="" disabled>选择新挖掘批次</option>
            <option v-for="run in succeededRuns" :key="run.id" :value="run.id">
              {{ run.run_label }} · {{ run.basket_count }} 张 · {{ formatDate(run.sample_start) }}~{{ formatDate(run.sample_end) }}
            </option>
          </select>
        </label>
        <div class="picker__actions">
          <button
            class="btn btn--mint"
            type="button"
            data-test="run-compare"
            :disabled="store.loading || !baselineId || !currentId || baselineId === currentId"
            @click="runCompare(false)"
          >
            {{ store.loading ? '对比中…' : '生成对比' }}
          </button>
          <button
            v-if="canRun"
            class="btn btn--quiet btn--sm"
            type="button"
            :disabled="store.loading || !baselineId || !currentId"
            title="重算并覆盖同键快照（对比口径不变，结果仍按这对批次复现）"
            @click="runCompare(true)"
          >
            强制重算
          </button>
        </div>
      </div>
    </ShelfBand>

    <template v-if="result">
      <!-- 两批样本头部 -->
      <ShelfBand index="04" title="样本口径" :caption="`快照时间 ${formatDateTime(result.snapshot_at)}${result.reused_snapshot ? ' · 复用快照' : ' · 首次计算'}`">
        <div class="samples">
          <div class="sample-card">
            <div class="sample-card__eyebrow">基线批次</div>
            <div class="sample-card__label mono">{{ result.baseline.run_label }}</div>
            <div class="sample-card__rows">
              <span>样本小票 <b class="tag-num">{{ formatInteger(result.baseline.basket_count) }}</b> 张</span>
              <span>时间范围 <b class="mono">{{ formatDate(result.baseline.sample_start) }} ~ {{ formatDate(result.baseline.sample_end) }}</b></span>
              <span>通过规则 <b class="tag-num">{{ result.baseline.passed_rules }}</b> 条</span>
            </div>
          </div>
          <div class="sample-card sample-card--new">
            <div class="sample-card__eyebrow">当前批次</div>
            <div class="sample-card__label mono">{{ result.current.run_label }}</div>
            <div class="sample-card__rows">
              <span>样本小票 <b class="tag-num">{{ formatInteger(result.current.basket_count) }}</b> 张</span>
              <span>时间范围 <b class="mono">{{ formatDate(result.current.sample_start) }} ~ {{ formatDate(result.current.sample_end) }}</b></span>
              <span>通过规则 <b class="tag-num">{{ result.current.passed_rules }}</b> 条</span>
            </div>
          </div>
        </div>
      </ShelfBand>

      <!-- 五类变化 KPI -->
      <div class="strip">
        <StatSlip :items="changeStats" />
      </div>

      <!-- 受影响货架位 -->
      <ShelfBand
        v-if="result.affected_slots.length"
        index="05"
        title="受影响的已发布货架位"
        :caption="`${result.affected_slots.length} 个现行工单位的规则已消失或减弱，需要店长复核；消失组合不会进入新建议单`"
      >
        <table class="grid-table" data-test="affected-table">
          <thead>
            <tr>
            <th>工单 / 货架位</th>
            <th>规则组合</th>
            <th>变化</th>
            <th class="ta-r">基线 lift</th>
            <th class="ta-r">新批 lift</th>
            <th class="ta-r">现行月增量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="slot in result.affected_slots" :key="slot.slot_key">
              <td>
                <div class="mono">{{ slot.plan_code }}</div>
                <div class="muted-cell">{{ slot.zone }} · {{ slot.shelf_label }}</div>
              </td>
              <td>{{ slot.rule_label }}</td>
              <td><span :class="['chip', changeTone(slot.change_type)]">{{ RULE_CHANGE_LABELS[slot.change_type] }}</span></td>
              <td class="ta-r is-num">{{ formatDecimal(slot.baseline_lift) }}</td>
              <td class="ta-r is-num">{{ formatDecimal(slot.current_lift) }}</td>
              <td class="ta-r is-num">{{ formatCurrency(slot.est_uplift) }}</td>
            </tr>
          </tbody>
        </table>
      </ShelfBand>

      <!-- 差异明细表 -->
      <ShelfBand index="06" title="规则差异明细" caption="按 消失 → 减弱 → 新增 → 增强 → 持平 排序；保留组合可追溯上批复核结论">
        <template #actions>
          <div class="tabs" data-test="change-tabs">
            <button
              v-for="tab in changeTabs"
              :key="tab.value ?? 'all'"
              type="button"
              class="tab"
              :class="{ 'is-on': changeFilter === tab.value }"
              @click="changeFilter = tab.value"
            >
              {{ tab.label }}{{ tab.value ? ` ${result.counts[tab.value] ?? 0}` : ` ${result.changes.length}` }}
            </button>
          </div>
        </template>
        <table class="grid-table" data-test="change-table">
          <thead>
            <tr>
              <th style="width: 96px">变化</th>
              <th>规则组合</th>
              <th class="ta-r">基线 lift</th>
              <th class="ta-r">新批 lift</th>
              <th class="ta-r">lift 变化</th>
              <th class="ta-r">共现（基→新）</th>
              <th>上批复核追溯</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredChanges" :key="row.rule_identity" :class="`row--${row.change_type}`">
              <td><span :class="['chip', changeTone(row.change_type)]">{{ RULE_CHANGE_LABELS[row.change_type] }}</span></td>
              <td>
                <div class="rule-name">{{ row.label }}</div>
                <div class="muted-cell">{{ row.zone }} · {{ row.shelf_label }}</div>
              </td>
              <td class="ta-r is-num">{{ formatDecimal(row.baseline.lift) }}</td>
              <td class="ta-r is-num">{{ formatDecimal(row.current.lift) }}</td>
              <td class="ta-r is-num" :class="deltaClass(row.lift_change_ratio)">
                {{ formatSignedPercent(row.lift_change_ratio) }}
              </td>
              <td class="ta-r is-num">
                {{ row.baseline.cooccur_count ?? '—' }} → {{ row.current.cooccur_count ?? '—' }}
              </td>
              <td class="lineage-cell">
                <template v-if="row.lineage && row.lineage.baseline_status">
                  <span :class="['chip', statusTone(row.lineage.baseline_status)]">
                    {{ RULE_STATUS_LABELS[row.lineage.baseline_status] }}
                  </span>
                  <span v-if="row.lineage.in_published_plan" class="lineage-published">已进工单</span>
                  <p v-if="row.lineage.baseline_reason" class="lineage-reason">
                    {{ row.lineage.baseline_reviewer }}：{{ row.lineage.baseline_reason }}
                  </p>
                </template>
                <span v-else class="muted-cell">无历史复核</span>
              </td>
              <td class="ta-r">
                <RouterLink v-if="row.current_rule_id" class="btn btn--sm btn--quiet" :to="`/rules/${row.current_rule_id}`">
                  新批规则
                </RouterLink>
                <RouterLink v-else-if="row.baseline_rule_id" class="btn btn--sm btn--quiet" :to="`/rules/${row.baseline_rule_id}`">
                  基线规则
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!filteredChanges.length" class="muted">该分类下没有规则。</div>
      </ShelfBand>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '../components/common/PageHeader.vue'
import ShelfBand from '../components/common/ShelfBand.vue'
import StatSlip, { type SlipItem } from '../components/common/StatSlip.vue'
import ErrorNotice from '../components/common/ErrorNotice.vue'
import { useComparisonStore } from '../stores/comparisonStore'
import { useBasketBatchStore } from '../stores/basketBatchStore'
import { useMiningStore } from '../stores/miningStore'
import { useAuthStore } from '../stores/authStore'
import {
  BATCH_SOURCE_LABELS,
  RULE_CHANGE_LABELS,
  RULE_STATUS_LABELS,
  type RuleChangeType,
} from '../constants/enums'
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatDecimal,
  formatInteger,
  formatSignedPercent,
} from '../utils/format'

const store = useComparisonStore()
const batchStore = useBasketBatchStore()
const mining = useMiningStore()
const auth = useAuthStore()

const canRun = computed(() => auth.can('mining:run'))
const canRead = computed(() => auth.can('mining:read'))

const baselineId = ref('')
const currentId = ref('')
const changeFilter = ref<RuleChangeType | ''>('')
const showImport = ref(false)

const importing = ref(false)
const importError = ref('')
const importForm = ref({ batch_code: '', note: '' })
const fileContent = ref<null | { baskets?: unknown[]; batch_code?: string }>(null)
const parsedCount = computed(() =>
  Array.isArray(fileContent.value?.baskets) ? (fileContent.value?.baskets as unknown[]).length : 0,
)

const result = computed(() => store.current)
const succeededRuns = computed(() => mining.runs.filter((run) => run.status === 'succeeded'))

const changeTabs = [
  { label: '全部', value: '' as const },
  { label: '消失', value: 'gone' as RuleChangeType },
  { label: '减弱', value: 'weaker' as RuleChangeType },
  { label: '新增', value: 'new' as RuleChangeType },
  { label: '增强', value: 'stronger' as RuleChangeType },
  { label: '持平', value: 'stable' as RuleChangeType },
]

const changeStats = computed<SlipItem[]>(() => {
  if (!result.value) return []
  const counts = result.value.counts
  return [
    { label: '新增规则', value: counts.new, unit: '条', tone: 'mint' },
    { label: '消失规则', value: counts.gone, unit: '条', hint: '不进新建议单' },
    { label: '增强', value: counts.stronger, unit: '条', tone: 'mint' },
    { label: '减弱', value: counts.weaker, unit: '条' },
    { label: '持平', value: counts.stable, unit: '条' },
  ]
})

const filteredChanges = computed(() => {
  if (!result.value) return []
  if (!changeFilter.value) return result.value.changes
  return result.value.changes.filter((row) => row.change_type === changeFilter.value)
})

function changeTone(type: RuleChangeType): string {
  if (type === 'new' || type === 'stronger') return 'chip--mint'
  if (type === 'gone' || type === 'weaker') return 'chip--alert'
  return 'chip--tag'
}

function statusTone(status: string): string {
  if (status === 'adopted') return 'chip--mint'
  if (status === 'rejected') return 'chip--alert'
  return 'chip--tag'
}

function deltaClass(value: number | null): string {
  if (value === null) return ''
  if (value > 0) return 'delta--up'
  if (value < 0) return 'delta--down'
  return ''
}

function onFile(event: Event) {
  importError.value = ''
  fileContent.value = null
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result))
      if (!parsed || !Array.isArray(parsed.baskets) || !parsed.baskets.length) {
        importError.value = '文件缺少非空 baskets 数组'
        return
      }
      fileContent.value = parsed
      if (parsed.batch_code && !importForm.value.batch_code) {
        importForm.value.batch_code = String(parsed.batch_code)
      }
    } catch {
      importError.value = 'JSON 解析失败，请检查文件格式'
    }
  }
  reader.readAsText(file)
}

async function submitImport() {
  if (!fileContent.value) return
  if (!importForm.value.batch_code.trim()) {
    importError.value = '请填写批次编号'
    return
  }
  importing.value = true
  importError.value = ''
  try {
    await batchStore.importBatch({
      batch_code: importForm.value.batch_code.trim(),
      note: importForm.value.note,
      imported_filename: 'manual-upload.json',
      baskets: fileContent.value.baskets as Array<Record<string, unknown>>,
    })
    showImport.value = false
    importForm.value = { batch_code: '', note: '' }
    fileContent.value = null
  } catch (error) {
    importError.value = (error as Error).message
  } finally {
    importing.value = false
  }
}

async function runCompare(forceRefresh: boolean) {
  if (!baselineId.value || !currentId.value) return
  try {
    await store.compare({
      baseline_run_id: baselineId.value,
      current_run_id: currentId.value,
      force_refresh: forceRefresh,
    })
  } catch {
    /* 错误写入 store */
  }
}

onMounted(async () => {
  await Promise.all([store.loadBaselines(), store.loadHistory(), mining.loadRuns(), batchStore.load()])
  if (store.baselines.length) baselineId.value = store.baselines[0].run_id
  const w46 = succeededRuns.value.find((run) => run.run_label.includes('W46'))
  if (w46) currentId.value = w46.id
  else if (succeededRuns.value.length) currentId.value = succeededRuns.value[0].id
})
</script>

<style scoped>
.compare {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.notice {
  margin-top: 12px;
  padding: 8px 12px;
  font-size: 12px;
  border: 1px dashed var(--shelf);
  background: var(--paper-2);
}
.notice--tag {
  border-color: var(--tag-deep);
  background: var(--tag-pale);
}
.notice--mint {
  border-color: var(--mint-deep);
  background: var(--mint-pale);
  color: var(--mint-ink);
}
.strip {
  margin-top: 16px;
}
.muted {
  font-size: 12px;
  color: var(--ink-faint);
  padding: 8px 0;
}
.muted-cell {
  font-size: 10.5px;
  color: var(--ink-faint);
}
.mono {
  font-family: var(--tag-font);
  font-size: 11.5px;
}
.ta-r {
  text-align: right;
}
.import {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 16px;
  align-items: end;
}
.import__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.import__field--grow {
  grid-column: span 1;
}
.import__file {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.import__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.import__error {
  font-size: 11px;
  color: var(--alert);
}
.import__hint {
  margin: 10px 0 0;
  font-size: 10.5px;
  color: var(--ink-faint);
  word-break: break-all;
}
.picker {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
}
.picker__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.picker__actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.samples {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.sample-card {
  border: 1px solid var(--shelf-soft);
  border-top: 3px solid var(--shelf);
  background: var(--paper-2);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sample-card--new {
  border-top-color: var(--mint-deep);
  background: var(--mint-pale);
}
.sample-card__eyebrow {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
}
.sample-card__label {
  font-size: 14px;
  font-weight: 600;
}
.sample-card__rows {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--ink-soft);
}
.tabs {
  display: inline-flex;
  border: 1px solid var(--shelf-soft);
  flex-wrap: wrap;
}
.tab {
  background: transparent;
  border: 0;
  border-right: 1px solid var(--shelf-soft);
  padding: 3px 9px;
  font-size: 11px;
  color: var(--ink-soft);
  cursor: pointer;
}
.tab:last-child {
  border-right: 0;
}
.tab.is-on {
  background: var(--tag-pale);
  color: var(--ink);
}
.rule-name {
  font-weight: 500;
}
.row--gone {
  background: color-mix(in oklch, var(--alert-pale) 60%, transparent);
}
.row--weaker td:first-child {
  box-shadow: inset 3px 0 0 var(--alert);
}
.row--new {
  background: color-mix(in oklch, var(--mint-pale) 65%, transparent);
}
.row--stronger td:first-child {
  box-shadow: inset 3px 0 0 var(--mint-deep);
}
.delta--up {
  color: var(--mint-ink);
  font-weight: 600;
}
.delta--down {
  color: var(--alert);
  font-weight: 600;
}
.lineage-cell {
  max-width: 260px;
}
.lineage-published {
  font-size: 10px;
  color: var(--mint-ink);
  margin-left: 6px;
}
.lineage-reason {
  margin: 4px 0 0;
  font-size: 10.5px;
  color: var(--ink-soft);
}
@media (max-width: 1023px) {
  .import,
  .picker,
  .samples {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
