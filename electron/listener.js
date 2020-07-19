// preloaded for listener code

const ipcRenderer = require('electron').ipcRenderer;
window.ipcRenderer = ipcRenderer;
const customTitlebar = require('custom-electron-titlebar');
window.customTitlebar = customTitlebar;
