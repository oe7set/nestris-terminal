import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

// Touch kiosk: no context menu, no text selection drag, no pinch zoom gestures.
addEventListener("contextmenu", (e) => e.preventDefault());
addEventListener("gesturestart", (e) => e.preventDefault());

export default mount(App, { target: document.getElementById("app")! });
