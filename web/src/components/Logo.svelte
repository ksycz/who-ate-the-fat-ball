<script lang="ts">
  let { size = 32, variant = "tile" }: { size?: number; variant?: "tile" | "mark" } = $props();
</script>

{#if variant === "tile"}
  <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
    <rect width="64" height="64" rx="15" fill="#B4491A"></rect>
    <path d="M11 29L32 15l21 14" fill="none" stroke="#FFFFFF" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"></path>
    <circle cx="32" cy="37.5" r="13.5" fill="#FFFFFF"></circle>
    <circle cx="27" cy="35.3" r="2.6" fill="#B4491A"></circle>
    <circle cx="37" cy="35.3" r="2.6" fill="#B4491A"></circle>
    <path d="M29.3 39.4H34.7L32 43.8Z" fill="#B4491A" stroke="#B4491A" stroke-width="1.5" stroke-linejoin="round"></path>
  </svg>
{:else}
  <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
    <path d="M8 28L32 12l24 16" fill="none" stroke="#FFFFFF" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"></path>
    <circle cx="32" cy="38" r="15" fill="#FFFFFF"></circle>
    <circle cx="26.5" cy="35.5" r="2.9" fill="#B4491A"></circle>
    <circle cx="37.5" cy="35.5" r="2.9" fill="#B4491A"></circle>
    <path d="M29 40.5H35L32 45.2Z" fill="#B4491A" stroke="#B4491A" stroke-width="1.6" stroke-linejoin="round"></path>
  </svg>
{/if}
