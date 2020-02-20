const { app, BrowserWindow } = require('electron')

function createWindow () {
  // Create the browser window.
  let win = new BrowserWindow({
    width: 1600,
    height: 1000,
    webPreferences: {
      nodeIntegration: true
    }
  })
  win.on('closed', () => {
    win = null
  })

  // and load the index.html of the app.
  win.loadURL('https://www.battlehouse.com/play/firestrike/', {userAgent: 'Chrome'})
  //win.loadURL('http://localhost:9091/')
  win.once('ready-to-show', () => {
    win.show()
  })
}

app.whenReady().then(createWindow)
