<script lang="ts">
  import { navigate } from "../lib/router";
</script>

<h1>Page not found</h1>
<p>
  <a
    href="/"
    onclick={(e) => {
      e.preventDefault();
      navigate("/");
    }}>Go to Today</a
  >
</p>
