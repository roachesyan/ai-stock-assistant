<script setup lang="ts">
import type { RiskReview, RiskVerdict } from "../types";

defineProps<{
  review?: RiskReview | null;
  verdict?: RiskVerdict | null;
  riskRounds?: number;
  evidenceRounds?: number;
}>();
</script>

<template>
  <a-card title="AI 风控结论" size="small">
    <a-alert
      v-if="verdict === 'REJECTED_AT_LIMIT'"
      type="warning"
      show-icon
      message="风控未通过，但已按 EXECUTE_AND_FLAG 策略执行，请人工复核。"
      style="margin-bottom: 12px"
    />
    <a-space style="margin-bottom: 12px">
      <a-tag :color="review?.approved ? 'green' : 'orange'">
        {{ review?.approved ? "风控通过" : "风控未通过" }}
      </a-tag>
      <span>风控轮次: {{ riskRounds ?? 0 }}</span>
      <span>证据轮次: {{ evidenceRounds ?? 0 }}</span>
    </a-space>

    <div v-if="review?.overall_notes" style="margin-bottom: 8px">
      <strong>总体意见：</strong>{{ review.overall_notes }}
    </div>

    <a-list
      v-if="review?.issues?.length"
      size="small"
      bordered
      :data-source="review.issues"
    >
      <template #renderItem="{ item }">
        <a-list-item>
          <a-tag>{{ item.ticker }}</a-tag>
          {{ item.issue }}
        </a-list-item>
      </template>
    </a-list>
    <a-empty v-else-if="!review" description="无风控数据" />
  </a-card>
</template>
