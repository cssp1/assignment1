const { app, BrowserWindow, dialog, session, screen } = require('electron');
const ipc = require('electron').ipcMain;
let main_window;

// listener for shutdown message. Shuts down on receipt
ipc.on('message', (event, message) => {
    if(message === 'electron-shutdown-game') {
        shutdown_app();
    } else if(message === 'electron-cancel-fullscreen' && main_window && main_window.isFullScreen()) {
        main_window.setFullScreen(false);
        main_window.center();
    } else if (message === 'electron-request-fullscreen' && main_window && !main_window.isFullScreen()) {
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
    var mainScreen = screen.getPrimaryDisplay();
    var new_width = Math.floor(mainScreen.workArea['width']);
    var new_height = Math.floor(mainScreen.workArea['height']);
    main_window = new BrowserWindow({
        webPreferences: {
            nodeIntegration: true,
            preload: __dirname + '/listener.js'
        },
        width: new_width,
        height: new_height,
        frame: false
    });
    main_window.on('closed', () => {
        main_window = null;
    });
    main_window.loadURL('https://www.battlehouse.com/play/thunderrun/');
    const menu = new Menu();
    Menu.setApplicationMenu(menu);

    // waits until app is ready, then shows the window
    main_window.once('ready-to-show', () => {
        main_window.show();
        main_window.center();
    })
}

app.whenReady().then(createMainWindow);
app.on('window-all-closed', () => {
  app.quit();
})
