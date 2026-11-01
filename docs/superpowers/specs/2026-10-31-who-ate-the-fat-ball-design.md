# Who Ate the Fat Ball? Design spec

**Date:** 2026-10-31 · **Status:** draft, waiting for the owner's review · **Owner:** Katarzyna Vaňous

**Supporting material**
- `HANDOFF.md`: camera protocol details and the decision log.
- `design/changes-combined.md`: the merged design critiques.
- Prototypes: a Claude Design canvas at https://claude.ai/artifact/QoKs9VQb9qFngqkMK7vPx2 (private). Source copies are in `design/prototypes/`.
- Logo: `design/logo.svg`.

---

## 1. Summary

The owner has a battery- and solar-powered iCSee outdoor camera pointed at a bird feeder. Its phone app shows ads, raises false alerts (wind, shadows, the dogs), can't identify birds, and makes photos hard to find.

**Who Ate the Fat Ball?** is a local app that runs on the owner's Mac at home. It:

1. notices when the camera wakes and downloads the new clips over home Wi-Fi, so nobody touches iCSee or the SD card;
2. decides for each clip whether it shows a **bird** (and which species), **another animal**, or **nothing / a dog**;
3. shows everything in a calm, ad-free **web gallery**. The gallery opens in the browser on the Mac, an Android phone and an iPad, and can be installed to the home screen.

## 2. Goals, non-goals, success criteria

**Goals (phase 1)**
- No ads, no cloud, no subscription. Everything stays on the home network.
- Only real bird visits appear in the main gallery. Everything else goes to Other animals or Other, and the owner can review and move it.
- Every bird visit gets an English species name with a confidence level, and the owner can correct it.
- Photos and videos are quick to find, watch and download, one at a time or as a .zip.
- The app feels fast, looks like the agreed prototypes, and is covered by automated tests, including Playwright end-to-end tests.

**Non-goals (phase 1)**
- Working away from home (no remote access, no hosting).
- Phone push notifications. The Mac shows a banner instead.
- The app learning from corrections. Corrections are stored for a later phase.
- Czech or Polish names. English only for now; the data model is ready for other languages.
- Supporting cameras other than this iCSee/Xiongmai model. The design keeps a clean seam for adding them.

**Success criteria**
- After a bird visits, the visit appears in the gallery within about 30 s of the clip being downloaded, without the owner doing anything.
- In a typical week, at most about 1 in 10 bird visits needs a manual correction. The bird-recognition spike (§13) will confirm what's realistic.
- The gallery opens in under 1 s on home Wi-Fi with thousands of visits stored.
- All screens in the prototypes exist in the app and behave as shown.

## 3. Users and devices

- **The owner** checks the gallery on an **Android phone** (main device), an **iPad** and a **Mac**. She isn't a developer and cares a lot about visuals.
- **Someone else in the house** may look at the gallery on the same home Wi-Fi. They can **view only**; editing needs the owner's edit PIN.
- **The Mac** runs the background service, and it must be on and at home for clips to arrive. Clips missed while it was off are fetched later, because they stay on the camera's SD card.

## 4. Architecture

```
iCSee camera (sleeps; wakes on motion)        Mac (always the same process)
  └─ port 34567 (Xiongmai DVRIP) ◄──────────  Camera link ─ Watcher ─ Downloader
                                                    │
                                              Converter (raw → H.265 original + H.264 web copy, frames)
                                                    │
                                              Bird spotter (detector → classifier → category, best frame)
                                                    │
                                              Library (SQLite + media folder)
                                                    │                    └─ Notifier (Mac banner)
                                              Web server (API + gallery files) ◄── browsers on Mac / Android / iPad
```

- **One Python service** runs in the background as a macOS LaunchAgent, so it starts at login and restarts if it crashes. It holds every part: watcher, processing queue, web server and notifier. If a Raspberry Pi takes over later, the same code moves there.
- **The gallery** is a TypeScript web app, built to static files and served by the same process. It's a PWA, so it can be installed to the home screen on Android and iPad.
- **Clean boundaries:**
  - The *camera link* is the only code that speaks the Xiongmai protocol. An interface lets a future RTSP/ONVIF camera plug in.
  - The *library* is the only code that touches SQLite and media files.
  - The *gallery* talks to the service through a JSON API only. That keeps a later move to hosting possible: only the gallery and a copy of the library would move, and the camera part must always stay at home.

### Technology
| Part | Choice |
|---|---|
| Service | Python 3.12 (installed with `uv`), FastAPI + Uvicorn, a background task queue inside the same process |
| Storage | SQLite (WAL mode) plus a media folder, by default `~/Library/Application Support/WhoAteTheFatBall/` |
| Media | ffmpeg: converts the camera's H.265 to an H.264 MP4 for web playback, extracts frames, builds thumbnails and 3 s preview loops |
| Bird recognition | Runs on the Mac, never in the cloud. Step 1 is an animal detector; step 2 is a nature classifier that recognises European birds and common garden mammals. The models are chosen in a spike (§13), and only licences compatible with MIT are allowed. |
| Gallery | TypeScript, Svelte + Vite, built to static files. No CSS framework: the design tokens are CSS variables (§9). |
| Tests | pytest for the service; Playwright for end-to-end tests (Chromium, WebKit, mobile Chrome emulation) |

## 5. Camera integration

These are proven facts; the details are in `HANDOFF.md`.
- **Connection:** the camera answers on TCP **34567** (Xiongmai DVRIP) only while it's awake. Login, file listing, and download (the claim goes on a second connection, DownloadStart on the main one) all work.
- **Format:** clips are H.265, 2560×1440 at 12 fps, about 6–11 s long. Photos are 800×448 JPEGs.

**Watcher**
- Every 5 s it tries a cheap TCP connect to port 34567. This doesn't wake the camera.
- When the camera is reachable, it logs in, lists files for today (and yesterday right after midnight), and downloads any not yet in the library. It works newest first.
- It records `last_seen` for the camera status.
- On start-up it catches up: it lists the last 7 days, one day at a time, because each list request returns at most 64 files.
- Downloads are idempotent. A file's identity is its SD-card path plus begin time; a partly downloaded file is thrown away and fetched again.

**Clock fix:** at each connection, if the camera's clock differs from the Mac's by more than 2 minutes, the service sets the camera's time. Times stored in the library always come from the Mac's timezone.

**Password:**
- The camera password is stored in the macOS **Keychain** and set once on a first-run Setup screen. It is never written to files or logs.
- If the camera has no password, the setup screen recommends setting one and can do it.

**Address:** the camera is found by its MAC address or by scanning port 34567, because its IP address may change. The current address is cached.

**Open risk:** how long the camera stays awake after motion. If it's too short to download everything, the downloader takes the newest clip first and catches the rest on later wake-ups.

## 6. Processing pipeline

1. **Convert.** The raw download is unwrapped into an H.265 original and an H.264 web MP4. The service also makes a poster frame, a 3 s muted preview loop (for the "moving previews" on cards), and thumbnails.
2. **Detect and classify.**
   - Frames are sampled at about 2 fps and run through the detector.
   - Bird crops go to the species classifier. Each clip gets its top species, the confidence, and the top 3 guesses.
   - Category rules:
     - bird → **Birds**
     - squirrel, cat, hedgehog, other wild mammal → **Other animals**
     - dog, person, or nothing detected → **Other**. The family's dogs aren't interesting, and any dog is treated as theirs.
   - The **best frame** is the sharpest frame with the biggest, most confident bird. It becomes the visit's photo.
3. **Group clips into visits.** A clip joins the latest visit if it starts less than 60 s after that visit's last clip, has the **same category**, and has the **same top species**. Clips with no confident species (below the "sure" threshold) join the visit they fall into. Otherwise the clip starts a new **visit**. A visit's time is its first clip; its length is first clip to last clip.
4. **Save** to the library. "New species" is raised the first time a species appears.
5. **Notify.** The Mac banner groups notifications, for example "3 new visits: great tit, robin".

While processing, a visit shows **"Checking who it is…"**. When processing fails, the visit stays in the library with an error state and a Retry option.

## 7. Data model (SQLite)

| Table | Key fields |
|---|---|
| `camera` | id, name, mac, last_ip, last_seen_at, last_error, clock_offset_s |
| `clip` | id, camera_id, sd_path, begin_at, end_at, kind (video/photo), status (downloaded/processing/ready/failed), original_path, web_path, poster_path, preview_path, size_bytes |
| `visit` | id, started_at, ended_at, category (birds/other_animals/other), species_id (nullable), confidence, best_clip_id, best_frame_path, is_favourite, moved_by_user |
| `visit_clip` | visit_id, clip_id |
| `species` | id, scientific_name (unique key), group (bird/mammal), first_seen_at |
| `species_name` | species_id, lang (en for now; cs and pl later), name |
| `guess` | visit_id, species_id, confidence, rank |
| `correction` | id, visit_id, from_species_id, to_species_id, from_category, to_category, created_at. Kept for the later learning phase. |
| `setting` | key, value |

Every user action that changes data (correct, move, favourite) is reversible. The API returns enough to support **Undo**.

## 8. Gallery: pages and behaviour

The prototypes are the reference for layout. This section fixes the behaviour.

### Navigation
- **Phone:** a floating bottom menu: **Today · Videos · Birds · Stats · More**.
- **iPad and Mac:** a side menu, in this order:
  1. Today, Videos, Favourites
  2. a **"Sorted into"** box: **Birds / Other animals / Other**, each with a coloured dot and a count
  3. **Stats**, then **App status**
  
  The camera status sits at the bottom of the menu.
- **Back** returns to the screen you came from.

### Pages
- **Today**
  - A header with the logo and the camera status.
  - The **New species** banner, when there is one.
  - A **"Today's fat-ball champion"** card: the species with the most visits today, its count, and its first visit time.
  - Today's visits, newest first.
  - States: empty ("Quiet so far…"), processing ("Checking who it is…"), "1 clip couldn't be fetched · Retry", and a camera-problem notice.
- **Videos:** a full-screen feed.
  - Filter chips: All birds, plus the most common species.
  - Favourite, **What is it?** and Download buttons.
  - Both swipe and Previous / Next.
  - "What is it?" opens on top of the video, so you keep your place in the feed.
- **Birds:** a switch between **All visits | By species**.
  - *All visits* is grouped by day, with **Select** for **Move to… / Download .zip** and Undo.
  - *By species* shows species cards with visit counts and **"Last seen"**, plus a period filter (This week / This month / All time) that appears only in this view.
  - On the Mac, the page is reached through **Sorted into › Birds**.
- **Other animals / Other**
  - On the Mac they're side-menu categories; on the phone they're under More.
  - **Other** has the filters **All · Only dogs · Empty clips**.
  - Empty clips can be deleted in bulk by the owner. Nothing is ever deleted automatically in phase 1.
- **Visit**
  - A player and the visit's clips. The one playing is marked "playing".
  - The name, plus a **"94% sure"** chip and a **"Not right? Change"** button.
  - "Or maybe" guesses, which can be tapped.
  - Favourite, and **Download ▾** (video / photo).
- **The "What is it?" picker** (a bottom sheet on the phone, a dialog on the Mac)
  - Search, then **Birds seen at your feeder**, then **Not a bird?**: Other animal / Dog / Nothing.
  - Choosing an option saves at once and shows **"Changed to …"** or **"Moved to … · Undo"**.
- **Stats**
  - Totals: visits, species, and the busiest time (e.g. "8–10 am").
  - A **busiest times** heatmap by day and 2-hour slot, in Robin colours. Tapping a square shows "Tue 8–10 am · 12 visits".
  - Visits per bird.
- **More** (phone): Favourites, the Sorted-into box, and App status.
- **App status**
  - Camera reachable or not, last seen time, last error.
  - The processing queue, disk space used, and a link to Setup (camera address and password).
- **Mac cards**
  - Drag a card onto a category to move it.
  - A corner **⋯** menu also offers **Move to…** and works with the keyboard.
  - **Select** mode handles bulk actions.
  - The cards have no visible move control under the photo.

### Rules shared by every page
- **Camera status:**
  - "Camera seen 5 min ago", with a **green dot** if seen in the last hour.
  - A **sand dot** when it's asleep but was seen today.
  - An **orange dot** with "Camera not seen since … · Check App status" otherwise.
- **The "New species" banner**
  - Dark robin orange, with the **white logo mark** (roof and bird face, no tile).
  - A small pale-peach "New species" heading, regular-weight white text, and one white **Watch** button.
  - It appears at the top of Today on the phone and at the top of Birds on the Mac, and it stays until the visit has been watched.
- **Formats:**
  - Time: "09:12 · stayed 2 min". Add "Yesterday" or a date only for older visits.
  - Clip badge: dark, "▶ 0:24 · 3 clips".
  - Confidence chip: blue-grey, "94% sure".
  - Species card: "42 visits", with the period shown once.
  - A corrected visit shows "Corrected by you".
  - Bird names are always the full English name from the species list.
- **Downloads:**
  - A single video or photo downloads directly.
  - A .zip of several visits, or of a whole day, shows its size first and confirms when done.

## 9. Visual design system ("Robin")

| Token | Value | Use |
|---|---|---|
| `--robin` | #B4491A | Primary actions, banner, active accents. Text on it is white. |
| `--robin-dark` | #8F3712 | Links, text accents, selected outline |
| `--robin-tint` | #F7E1D3 | Active menu pill, soft highlights |
| `--peach` | #FFEDE3 | Small heading on the banner |
| `--sand` | #F1E8DC | App background |
| `--ink` | #2E2116 | Main text |
| `--ink-2` | #5E5040 | Secondary text |
| `--olive` | #6E5B3A | Inactive icons |
| `--line` | #E9E0D4 / `--line-strong` #E0D5C6 / `--field` #A8998A | Borders and input fields |
| `--chip` | #E3EBF0 / text #34505F | Confidence chips |
| `--dot-animals` | #8FA6B4 | Other animals dot |
| `--dot-other` | #C9BBA8 | Other dot |
| `--ok` | #2E8B57 | "Camera seen recently" dot (stays green, by decision) |
| heatmap | #F1E8DC → #F7E1D3 → #E39A72 → #B4491A → #8F3712 | Busiest times |

**Type**
- Plus Jakarta Sans, everywhere.
- Weights: **800** for page titles and big numbers; **600** for names, buttons, chips and badges; **400–500** for everything else. **Never 700**, and no bold text on banners.
- Smallest text: 11px.

**Shape:** cards on white with a 16–18px radius, pills of 999px, and a floating menu bar of 24px.

**Icons:** themed outline icons at 1.9px stroke.
- Today: sun over a feeder
- Videos: birdhouse with a play button
- Birds: a bird
- Stats: bar chart topped with fat balls
- More: three seeds

**Logo:** N4b. A robin-orange tile with a white roof line over a white round "fat ball" bird face, with orange eyes and a beak. The SVG is `design/logo.svg`. It needs a small-size version (16–32px) with a thicker roof.

**Imagery**
- Real camera photos and videos only.
- No hand-drawn birds in the interface.
- Never show fat balls in mesh nets, because nets are unsafe for birds.

**Accessibility (WCAG 2.1 AA)**
- Text contrast of at least 4.5:1, and 3:1 for icons and borders.
- Tap targets of at least 44px on phone.
- Selected states announced to screen readers (`aria-pressed` / `aria-current`) and shown by more than colour alone.
- Everything works by keyboard on the Mac, drag and drop included.
- Dialogs keep focus and close with Esc.
- Heatmap values are available by tap or focus, not hover only.

## 10. API (JSON over HTTP, local network)

| Method and path | Purpose |
|---|---|
| `GET /api/status` | Camera status, queue, disk use |
| `GET /api/today` | Champion, new-species banner, today's visits, states |
| `GET /api/visits?category=&species=&day=&q=&cursor=` | Paginated visit lists for Birds, Other animals, Other and Favourites |
| `GET /api/visits/{id}` | Visit details: clips, guesses, actions |
| `PATCH /api/visits/{id}` | Set species, category or favourite. Returns an undo token. |
| `POST /api/visits/bulk` | Move or favourite many at once. Returns an undo token. |
| `POST /api/undo/{token}` | Undo the last change |
| `GET /api/species?period=` | Species cards |
| `GET /api/stats?weeks=4` | Totals, heatmap, per-species counts |
| `GET /api/videos?filter=` | Feed for the Videos page |
| `GET /media/...` | Posters, previews and web MP4s, with HTTP range support for streaming |
| `POST /api/downloads/zip` | Build a .zip of visits or a whole day, with its size given first |
| `POST /api/retry/{clip_id}` | Retry a failed clip |
| `GET/PUT /api/setup` | Camera address, password (goes into the Keychain) and edit PIN (stored as a salted hash). Local only. |
| `POST /api/unlock` | Check the edit PIN and set the editor cookie |
| `GET /api/me` | `{can_edit}`, so the gallery knows whether to show edit controls |

**Access:**
- The server listens on the home network only.
- **Viewing is open** to anyone on the home Wi-Fi with no login: browse, watch and download. This lets the owner share the gallery with someone in the same house.
- **Editing needs a 4-digit edit PIN.** That covers correcting species, moving between categories, favourites, undo, retry and deleting empty clips.
  - The owner sets the PIN in Setup. It is stored only as a salted hash.
  - A device unlocks once with `POST /api/unlock {pin}`, which sets a long-lived, HTTP-only cookie.
  - Requests from the Mac itself never need the PIN.
  - Five wrong PINs from a device lock unlocking for 15 minutes.
- **On a locked device**, edit controls are hidden, not just disabled. The menu has a small "Unlock editing" entry instead.
- The Setup screen and its API answer only to requests from the Mac itself.

## 11. Performance

- Gallery first load under 1 s on home Wi-Fi. This comes from static files, pre-built thumbnails, and lists loaded in pages as you scroll (cursor pagination).
- A downloaded clip appears in the gallery within about 30 s on an Apple-silicon Mac.
- Videos start within 1 s, streamed by byte range rather than downloaded in full.
- The service stays light when idle. The watcher's check every 5 s is a single TCP connect.

## 12. Errors and edge cases

- **Camera unreachable for more than 1 hour:** the status turns orange and App status shows the last error. The watcher keeps checking.
- **Download interrupted:** the partial file is deleted and fetched again on the next wake-up.
- **Conversion or recognition fails:** the clip is marked *failed* and appears as "1 clip couldn't be fetched · Retry". The original raw file is kept.
- **Wrong password or locked account:** retries pause for 10 minutes (the camera locks after repeated failures), and App status explains how to fix it.
- **Disk nearly full:** App status shows a warning. Phase 1 never deletes anything on its own.
- **First run:** Setup asks for the camera's address and password, then catches up on the last 7 days. Until then, Today shows the empty state.

## 13. Spikes before building (each gets a short written result)

1. **Wake window:** how long the camera stays reachable after a motion event, and whether one clip can be downloaded in that time.
2. **Bird recognition models:**
   - Compare 2–3 detector and classifier pairs on about 50 real clips from the feeder: birds, the dogs, empty clips and any squirrels.
   - Measure accuracy, speed on the Mac, and licence compatibility with MIT.
   - Choose the pair and set the confidence threshold that counts as "sure".
3. **Video playback:** confirm that H.264 MP4 plays on the owner's Android phone, iPad and Mac browsers. Measure how long ffmpeg takes per clip.

## 14. Testing strategy

**Test-driven development.** For every feature, the tests are written first.

**Unit tests (pytest)**
- protocol encoding and decoding, including the password hash
- frame unwrapping
- visit grouping
- category rules
- the "new species" and champion logic
- the undo logic
- API responses

**Fake camera**
- An in-process fake Xiongmai server that serves recorded sample files.
- It can sleep, wake, drop the connection mid-download and reject the password.
- The watcher and downloader are tested against it.

**Sample clips:** a small set of real clips (bird, dog, empty, squirrel if one appears) with expected results, as regression tests for bird recognition.

**Playwright end-to-end tests**, against the real service with the fake camera and a seeded library, in Chromium, WebKit (for the iPad) and mobile Chrome emulation (for Android):
- Today states
- a visit opened from Today
- correcting the species, then undoing it
- moving a visit to Other from Birds Select, then undoing it
- dragging a card onto Other animals on the Mac, and the same move done with the keyboard
- the Videos picker used without leaving the feed
- downloading a single photo and a .zip
- Stats heatmap values shown on tap
- the More page navigation
- accessibility checks with axe on every page

**Visual checks:** screenshot tests of the key screens against the approved prototype look.

## 15. Phases

| Phase | Scope |
|---|---|
| **1 (this spec)** | Everything above: Mac service, iCSee camera, gallery on Mac, Android and iPad, English names, Mac banner |
| 2 | Raspberry Pi, always on; phone notifications for new birds only |
| 3 | Learning from the owner's corrections; Czech and Polish names |
| Later | Optional hosted gallery, other cameras (RTSP/ONVIF), dark mode |

## 16. Portfolio use (added 2026-10-31)

The owner will also use this project as a **portfolio piece**. That adds these requirements:
- **Demo mode:** `fatball demo` runs the full app with a **fake camera and generated sample clips**, so anyone can try it without the hardware. The demo also powers screenshots and any later hosted demo.
- **Privacy:**
  - Real footage, camera serial numbers, IP and MAC addresses, and passwords are **never committed**.
  - Test fixtures are generated (synthetic video) or hand-made.
- **Code quality that shows:** CI on GitHub runs linting and every test on each push, and the badges appear in the README.
- **README:** the problem, screenshots taken from demo mode, an architecture diagram, how to run the demo, and the design process (prototypes, critiques, decisions) as a short case study.
- The repository stays **private** until the owner decides to make it public.

## 17. Decisions already made (do not reopen without the owner)

- **Look:** the Robin style; the N4b logo; the logo mark on the banner; Plus Jakarta Sans; no 700 weight; no bold on banners.
- **Menus:**
  - Phone: Today · Videos · Birds · Stats · More.
  - Mac: categories marked with dots, not icons, in a "Sorted into" group.
  - Stats sits just above App status.
- **Pages:**
  - Birds and Species are merged into one page with a switch.
  - The Videos tab stays.
  - The banner placement stays as it is.
- **Behaviour:**
  - Any dog goes to Other.
  - Other has an "Only dogs" filter.
  - The "camera OK" dot stays green.
  - Videos keeps both swipe and Previous / Next.
  - The "Today's fat-ball champion" card is in.
- **Wording:** "App status", not "Status". "Last seen", not "First seen".
