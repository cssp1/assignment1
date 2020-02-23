const { app, BrowserWindow, dialog } = require('electron');
const electronLocalshortcut = require('electron-localshortcut');

// this fullscreen window always shows the main game page
function createGameWindow () {
    // use game_win as the BrowserWindow object that holds the main game interface
    let game_win = new BrowserWindow({
        webPreferences: { nodeIntegration: true },
        frame: false
    })
    game_win.setFullScreen(true); // sets full screen
    game_win.on('closed', () => {
        game_win = null; // clears memory when the window is closed
    })

    // this keypress listener will open the menu when the appropriate keys are pressed
    electronLocalshortcut.register(game_win, 'Esc', () => {
        app.whenReady().then(createMenuWindow) // launch the menu page (local, compiled into the distributed package)
    });

    // set the URL the game will load. Must be changed before compiling
    // also be sure to change the userAgent value to the distribution channel (bh_electron_kartridge, bh_electron_steam, etc)
    game_win.loadURL('https://www.battlehouse.com/play/firestrike/', {userAgent: 'bh_electron_windows'})
    //game_win.loadURL('http://localhost:9091', {userAgent: 'bh_electron_windows'})

    // waits until app is ready, then shows the window
    game_win.once('ready-to-show', () => {
        game_win.show();
    })
}

// this window will display a local settings menu and include account and exit controls
function createMenuWindow () {
    // use menu_win as the BrowserWindow object that holds the menu interface
    let menu_win = new BrowserWindow({ frame: false })
    menu_win.setFullScreen(true); // sets full screen
    menu_win.on('closed', () => {
        menu_win = null;
    })
    electronLocalshortcut.register(menu_win, 'Esc', () => {
        menu_win.close();
        //app.quit();
    });

    // url for the menu controls (placeholder for now).
    menu_win.loadURL('https://www.google.com/', {userAgent: 'bh_electron_windows'})
    menu_win.once('ready-to-show', () => {
        menu_win.show();
    })
}

app.whenReady().then(createGameWindow) // launches the main game when everything is ready -- this should probably launch the menu/welcome screen instead
app.on('window-all-closed', () => {
  app.quit();
})
