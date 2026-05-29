<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ value: string }>();

const color = computed(() => {
  switch (props.value) {
    case "BUY":
      return "green";
    case "SELL":
      return "red";
    case "HOLD":
      return "blue";
    default:
      return "default";
  }
});
</script>

<template>
  <a-tag :color="color">{{ value }}</a-tag>
</template>
