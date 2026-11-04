<script lang="ts">
  // Outline icons from the design prototypes (24px grid), drawn in the current text colour.
  const ICONS = {
    Today: '<circle cx="12" cy="13" r="4"></circle><path d="M12 4v2M5.6 6.6l1.4 1.4M18.4 6.6L17 8M3 13h2M19 13h2M3 18h18M7 21h10"></path>',
    Videos: '<path d="M3 10.5L12 4l9 6.5"></path><path d="M5 9.5V20h14V9.5"></path><path d="M10.5 11.5l4.5 3-4.5 3z"></path>',
    Birds: '<path d="M4 16c4 0 6-2.5 7-5.5C12.3 6.8 15.5 5 18.5 7L21 8l-2.5.8C18 15 13 19 7 18.5L4 20l1-3z"></path>',
    Stats: '<path d="M5 21v-8M12 21V8M19 21v-5"></path><circle cx="5" cy="10.5" r="2"></circle><circle cx="12" cy="5.5" r="2"></circle><circle cx="19" cy="13.5" r="2"></circle>',
    More: '<ellipse cx="6" cy="12" rx="1.7" ry="2.6" transform="rotate(-20 6 12)"></ellipse><ellipse cx="12" cy="12" rx="1.7" ry="2.6"></ellipse><ellipse cx="18" cy="12" rx="1.7" ry="2.6" transform="rotate(20 18 12)"></ellipse>',
    Star: '<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"></path>',
    Camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"></path><circle cx="12" cy="13" r="3.5"></circle>',
  } as const;

  let { name, size = 22 }: { name: keyof typeof ICONS; size?: number } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.9"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  {@html ICONS[name]}
</svg>
