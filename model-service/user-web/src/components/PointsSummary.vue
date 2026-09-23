<script setup lang="ts">
import { usePortal } from '../stores/portal'
import { prettyPoints } from '../utils/financial'
const store = usePortal()
</script>
<template>
  <section v-if="store.user?.quota" class="points-summary" aria-label="积分账户概览">
    <div class="available">
      <p>本月可用积分</p>
      <strong>{{ prettyPoints(store.user.quota.available_points) }}</strong
      ><small>1 积分 = ¥0.01</small>
    </div>
    <div class="quota-tiles">
      <div>
        <span>月度总额度</span><strong>{{ prettyPoints(store.user.quota.monthly_points) }}</strong>
      </div>
      <div>
        <span>本月已用</span><strong>{{ prettyPoints(store.user.quota.spent_points) }}</strong>
      </div>
      <div>
        <span>预占积分</span><strong>{{ prettyPoints(store.user.quota.reserved_points) }}</strong>
      </div>
    </div>
    <p class="summary-note">积分每月1日更新</p>
  </section>
</template>
<style scoped>
.points-summary {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 28px;
  align-items: center;
  padding: 32px;
  background: var(--primary);
  color: var(--panel);
  border-radius: var(--radius-lg);
}
.available p {
  margin: 0 0 12px;
}
.available > strong {
  display: block;
  font-size: clamp(38px, 5vw, 56px);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  margin-bottom: 12px;
}
.available small {
  opacity: 0.9;
}
.quota-tiles {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.quota-tiles div {
  background: var(--hero-tile);
  border-radius: var(--radius-sm);
  padding: 18px;
  min-width: 0;
}
.quota-tiles strong {
  display: block;
  margin-top: 12px;
  font-size: 24px;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.quota-tiles span {
  font-size: 13px;
}
.summary-note {
  grid-column: 1/-1;
  font-size: 12px;
  margin: 0;
  opacity: 0.9;
}
@media (max-width: 600px) {
  .points-summary {
    grid-template-columns: 1fr;
    padding: 24px;
    gap: 22px;
  }
  .quota-tiles {
    gap: 8px;
  }
  .quota-tiles div {
    padding: 12px 8px;
  }
  .quota-tiles strong {
    font-size: 20px;
  }
}
</style>
