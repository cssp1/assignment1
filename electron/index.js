const { app, BrowserWindow, dialog } = require('electron');
const electronLocalshortcut = require('electron-localshortcut');

function createWindow () {
    // Create the browser window.
    let win = new BrowserWindow({
        width: 1600,
        height: 1000,
        webPreferences: {
            nodeIntegration: true
        }
    })

    win.setFullScreen(true);
    win.setMenu(null);
    win.on('closed', () => {
        win = null;
    })
    electronLocalshortcut.register(win, 'Esc', () => {
        app.quit();
        displayKeyPress();
    });

    // and load the index.html of the app.
    win.loadURL('https://www.battlehouse.com/play/firestrike/', {userAgent: 'bh_electron_windows'})
    //win.loadURL('http://localhost:9091', {userAgent: 'bh_electron_windows'})
    win.once('ready-to-show', () => {
        win.show();
    })
}

function displayKeyPress () {
    dialog.showMessageBox('Keypress detected');
}

app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
  app.quit();
})
