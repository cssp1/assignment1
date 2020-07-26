Initial setup:

Install yarn for your dev environment.

Initialize yarn in the electron folder with the command `yarn install`.

Run the test build with `yarn start`

Compile command: `electron-packager ./ --platform=win32 --arch=x64`

(note: requires electron-packager in the global yarn environment)

Need https://github.com/electron-userland/electron-builder#WinBuildOptions-certificateSubjectName
for EV code signing
