<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error && !data" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-row">
          <label for="restock-budget" class="budget-label">{{ t('restocking.budget') }}</label>
          <input
            id="restock-budget"
            v-model.number="budget"
            type="range"
            class="budget-slider"
            :min="0"
            :max="maxBudget"
            :step="BUDGET_STEP"
          />
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <p class="budget-hint">
          {{ t('restocking.budgetHint', { amount: formatMoney(fullRestockCost, 2) }) }}
        </p>
      </div>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatMoney(data.budget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.orderTotal') }}</div>
          <div class="stat-value">{{ formatMoney(data.total_cost, 2) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(data.remaining_budget, 2) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.estimatedLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { days: estimatedLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="confirmation" class="confirmation">
        <div>
          <div class="confirmation-title">
            {{ t('restocking.orderPlaced', { orderNumber: confirmation.order_number }) }}
          </div>
          <div class="confirmation-details">
            {{ t('restocking.orderPlacedDetails', {
              date: formatDate(confirmation.expected_delivery),
              days: confirmation.lead_time_days
            }) }}
          </div>
        </div>
        <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            {{ t('restocking.recommendations') }} ({{ recommendations.length }})
            <span v-if="refreshing" class="refreshing">{{ t('common.loading') }}</span>
          </h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="!canPlaceOrder"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else class="table-container">
          <table class="restock-table">
            <thead>
              <tr>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.demandGap') }}</th>
                <th class="num">{{ t('restocking.table.recommendedQty') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="rec in recommendations"
                :key="rec.item_sku"
                :class="{ 'partial-row': rec.partial }"
              >
                <td>
                  <div class="item-name">{{ translateProductName(rec.item_name) }}</div>
                  <div class="item-sku">{{ rec.item_sku }}</div>
                </td>
                <td>
                  <span :class="['badge', rec.trend]">{{ t(`trends.${rec.trend}`) }}</span>
                </td>
                <td class="num">{{ rec.demand_gap.toLocaleString() }}</td>
                <td class="num">
                  <strong>{{ rec.recommended_quantity.toLocaleString() }}</strong>
                  <span
                    v-if="rec.partial"
                    class="badge warning partial-badge"
                    :title="t('restocking.partialHint')"
                  >{{ t('restocking.partial') }}</span>
                </td>
                <td class="num">{{ formatMoney(rec.unit_cost, 2) }}</td>
                <td class="num"><strong>{{ formatMoney(rec.line_total, 2) }}</strong></td>
                <td class="num">{{ t('restocking.days', { days: rec.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const BUDGET_STEP = 50
// Slider max is the full restock cost rounded UP to the next multiple of this,
// so the top of the slider always covers every demand gap.
const BUDGET_ROUNDING = 500
const DEBOUNCE_MS = 250

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const refreshing = ref(false)
    const error = ref(null)
    const data = ref(null)
    const budget = ref(0)
    const maxBudget = ref(0)
    const fullRestockCost = ref(0)

    const submitting = ref(false)
    const submitError = ref(null)
    const confirmation = ref(null)

    const recommendations = computed(() => data.value?.recommendations || [])

    // Lead time of the whole order is driven by its slowest item
    const estimatedLeadTime = computed(() => {
      return recommendations.value.reduce((max, rec) => Math.max(max, rec.lead_time_days), 0)
    })

    // Disallow ordering while a refetch is pending/in flight so the submitted
    // items always match the budget shown on the slider.
    const canPlaceOrder = computed(() => {
      return recommendations.value.length > 0 && !submitting.value && !refreshing.value
    })

    const formatMoney = (amount, decimals = 0) => {
      return formatCurrencyWithDecimals(Number(amount) || 0, currentCurrency.value, decimals)
    }

    const formatDate = (dateString) => {
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return dateString || ''
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
    }

    const extractErrorDetail = (err, fallback) => {
      const detail = err?.response?.data?.detail
      if (typeof detail === 'string') return detail
      // FastAPI 422 responses return a list of validation errors
      if (Array.isArray(detail)) return detail.map(d => d.msg).filter(Boolean).join('; ') || fallback
      return fallback
    }

    // Stale-response guard: each fetch gets an increasing id, and only the
    // response for the latest id is applied. If an older (slower) request
    // resolves after a newer one, its result is discarded.
    let latestRequestId = 0

    const fetchRecommendations = async (value) => {
      const requestId = ++latestRequestId
      refreshing.value = true
      try {
        const result = await api.getRestockRecommendations(value)
        if (requestId !== latestRequestId) return
        data.value = result
        error.value = null
      } catch (err) {
        if (requestId !== latestRequestId) return
        error.value = extractErrorDetail(err, t('restocking.loadError'))
        console.error('Failed to load restock recommendations:', err)
      } finally {
        if (requestId === latestRequestId) refreshing.value = false
      }
    }

    // Debounce refetches while the slider is dragged: each input event resets
    // the timer, so only the value at rest (after DEBOUNCE_MS) hits the API.
    let debounceTimer = null
    watch(budget, (value) => {
      if (loading.value) return
      confirmation.value = null
      submitError.value = null
      // Mark as refreshing immediately so "Place Order" is disabled during the wait
      refreshing.value = true
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => fetchRecommendations(value), DEBOUNCE_MS)
    })

    const init = async () => {
      try {
        loading.value = true
        error.value = null
        // Initial call with budget 0 only to learn full_restock_cost (returned
        // regardless of budget), which determines the slider range.
        const probe = await api.getRestockRecommendations(0)
        fullRestockCost.value = probe.full_restock_cost
        maxBudget.value = Math.max(
          BUDGET_ROUNDING,
          Math.ceil(probe.full_restock_cost / BUDGET_ROUNDING) * BUDGET_ROUNDING
        )
        // Default to roughly half of the max, snapped to the slider step
        budget.value = Math.round(maxBudget.value / 2 / BUDGET_STEP) * BUDGET_STEP
        await fetchRecommendations(budget.value)
      } catch (err) {
        error.value = extractErrorDetail(err, t('restocking.loadError'))
        console.error('Failed to initialise restocking:', err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (!canPlaceOrder.value) return
      submitting.value = true
      submitError.value = null
      confirmation.value = null
      try {
        // Submit exactly what is displayed, with the budget those
        // recommendations were computed for.
        confirmation.value = await api.createRestockOrder({
          budget: data.value.budget,
          items: recommendations.value.map(rec => ({
            item_sku: rec.item_sku,
            quantity: rec.recommended_quantity
          }))
        })
      } catch (err) {
        submitError.value = extractErrorDetail(err, t('restocking.submitError'))
        console.error('Failed to place restock order:', err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(init)
    onBeforeUnmount(() => clearTimeout(debounceTimer))

    return {
      t,
      BUDGET_STEP,
      loading,
      refreshing,
      error,
      data,
      budget,
      maxBudget,
      fullRestockCost,
      recommendations,
      estimatedLeadTime,
      canPlaceOrder,
      submitting,
      submitError,
      confirmation,
      formatMoney,
      formatDate,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
}

.budget-row {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.budget-label {
  font-weight: 600;
  color: #0f172a;
  font-size: 0.938rem;
}

.budget-slider {
  flex: 1;
  accent-color: #3b82f6;
  cursor: pointer;
}

.budget-value {
  min-width: 110px;
  text-align: right;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}

.budget-hint {
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.refreshing {
  margin-left: 0.5rem;
  font-size: 0.813rem;
  font-weight: 400;
  color: #64748b;
}

.place-order-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #2563eb;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.confirmation {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #065f46;
  padding: 1rem 1.25rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
}

.confirmation-title {
  font-weight: 600;
  font-size: 0.938rem;
}

.confirmation-details {
  font-size: 0.875rem;
  margin-top: 0.25rem;
}

.confirmation-link {
  color: #065f46;
  font-weight: 600;
  font-size: 0.875rem;
  white-space: nowrap;
}

.empty-state {
  padding: 2.5rem 1rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.restock-table {
  width: 100%;
}

.restock-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.item-name {
  font-weight: 500;
  color: #0f172a;
}

.item-sku {
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 0.125rem;
}

.partial-row {
  background: #fffbeb;
}

.partial-badge {
  margin-left: 0.5rem;
  vertical-align: middle;
}
</style>
