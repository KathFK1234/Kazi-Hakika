// Applies a saved light/dark choice before the page paints (no flash).
// Loaded as a plain script from <head>; mirrors src/theme.ts.
;(function () {
  try {
    var saved = window.localStorage.getItem('kh-theme')
    if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved
  } catch {
    // Storage blocked: follow the device setting.
  }
})()
