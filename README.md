# Who Ate the Fat Ball? 🐦

A free, local app for bird-feeder cameras that finds out who's been visiting your feeder: no ads, no cloud, no false alarms.

> **Status: early days.** The connection to the camera works, and the app itself is being built. There's nothing to install yet.

## Why

Cheap outdoor Wi-Fi cameras (iCSee, XMEye and other Xiongmai-based models) are great for watching a bird feeder, but their phone apps:

- are full of **ads**
- send **alerts for everything**: wind, leaves, shadows, the dog
- have **no idea which bird** is on the feeder
- make it **hard to find** the photos and clips you care about

## What it will do

- 📥 **Fetch clips automatically** from the camera's memory card over your home Wi-Fi, even from battery cameras that sleep between visits
- 🐦 **Keep only clips with birds** and drop the empty ones
- 🔎 **Name the species** using a bird-recognition model that runs on your own computer
- 🖼️ **Gallery** of every visit, searchable by bird and date ("all great tits this week"), with video playback
- 🔒 **Everything stays at home**: no account, no cloud, no subscription

## Cameras

First target: **iCSee / Xiongmai** cameras, including battery and solar models, which are reached over their local network protocol (port 34567). More cameras may follow, such as ones with a standard RTSP/ONVIF feed.

## Licence

[MIT](LICENSE)
