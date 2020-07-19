const { app, BrowserWindow, dialog, session } = require('electron');
const ipc = require('electron').ipcMain;
let main_window;

// listener for shutdown message. Shuts down on receipt
ipc.on('message', (event, message) => {
    if(message === 'electron-shutdown-game') {
        shutdown_app();
    } else if(message === 'electron-windowed-mode' && main_window && main_window.isFullScreen()) {
        main_window.setFullScreen(false);
    } else if(message === 'electron-fullscreen-mode' && main_window && !main_window.isFullScreen()) {
        main_window.setFullScreen(true);
    }
});

// allows delay before executing some functions
function sleep(millis) {
    return new Promise(resolve => setTimeout(resolve, millis));
}

async function shutdown_app() {
    await sleep(250);
    main_window.destroy();
}

function createMainWindow () {

    session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
        details.requestHeaders['User-Agent'] = 'bh_electron_microsoft';
        callback({ cancel: false, requestHeaders: details.requestHeaders });
    });
    main_window = new BrowserWindow({
        webPreferences: {
            nodeIntegration: true,
            preload: __dirname + '/listener.js'
        },
        frame: false
    });
    main_window.setFullScreen(true);
    main_window.on('closed', () => {
        main_window = null;
    });
    main_window.loadURL('https://www.battlehouse.com/play/thunderrun/');

    // waits until app is ready, then shows the window
    main_window.once('ready-to-show', () => {
        main_window.show();
    })
}

app.whenReady().then(createMainWindow);
app.on('window-all-closed', () => {
  app.quit();
})
