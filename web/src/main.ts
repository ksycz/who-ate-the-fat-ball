import { mount } from "svelte";
import "./lib/tokens.css";
import App from "./App.svelte";

mount(App, { target: document.getElementById("app")! });

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
