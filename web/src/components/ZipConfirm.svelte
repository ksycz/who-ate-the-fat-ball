<script lang="ts">
  import { plural, sizeText } from "../lib/format";
  import { showToast } from "../lib/session";
  import { startDownload, type ZipPlan } from "../lib/zip";
  import ConfirmSheet from "./ConfirmSheet.svelte";

  let { info, ondone }: { info: ZipPlan; ondone: () => void } = $props();

  const summary = $derived(`${plural(info.visits, "visit")} (${sizeText(info.size_bytes)})`);

  function download() {
    startDownload(info.token, info.filename);
    showToast(`Downloading ${summary}…`);
    ondone();
  }
</script>

<ConfirmSheet title={`Download ${summary}?`} action="Download" onconfirm={download} oncancel={ondone} />
