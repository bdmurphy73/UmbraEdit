if (Test-Path .\build) {
    Remove-Item .\build -Recurse
}
New-Item -Path . -Name build -ItemType Directory
# The resource compiler resolves the icon path relative to the folder the
# project is built in, so the icon is copied there before the project is
# configured. The file name also has to match the one in the resource file.
Copy-Item .\umbraedit.ico .\build\UmbraEdit.ico -Force
Set-Location .\build
cmake -S .. -B .
cmake --build . --config Release

Set-Location ..
Copy-Item .\build\Release\UmbraEdit.exe . -Force
