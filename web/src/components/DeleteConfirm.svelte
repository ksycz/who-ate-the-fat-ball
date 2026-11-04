<script lang="ts">
  import { plural } from "../lib/format";
  import ConfirmSheet from "./ConfirmSheet.svelte";

  let { count, ondelete, ondone }: { count: number; ondelete: () => void; ondone: () => void } = $props();
</script>

<!-- Cancel has focus first: nothing can bring a deleted clip back. -->
<ConfirmSheet
  title={`Delete ${plural(count, "empty clip")}? This can't be undone.`}
  action="Delete"
  danger
  focus="cancel"
  onconfirm={ondelete}
  oncancel={ondone}
/>
