/*
 * UmbraEdit - macOS app launcher
 *
 * This is a small C program that serves as the CFBundleExecutable for
 * the UmbraEdit .app bundle. It is a compiled binary named "UmbraEdit",
 * so macOS shows "UmbraEdit" (not "Python") in the menu bar.
 *
 * It locates the UmbraEdit.py script relative to the app bundle and
 * execs the Python interpreter to run it.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach-o/dyld.h>

#define PYTHON_PATH "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python"

int main(int argc, char *argv[]) {
    char exe_path[4096];
    uint32_t size = (uint32_t)sizeof(exe_path);

    if (_NSGetExecutablePath(exe_path, &size) != 0) {
        fprintf(stderr, "UmbraEdit: could not get executable path\n");
        return 1;
    }

    // exe_path is like: .../UmbraEdit.app/Contents/MacOS/UmbraEdit
    // We want: .../UmbraEdit.app/Contents/Resources/UmbraEdit/UmbraEdit.py
    char *contents = strstr(exe_path, "Contents/MacOS");
    if (!contents) {
        fprintf(stderr, "UmbraEdit: unexpected executable path: %s\n", exe_path);
        return 1;
    }

    // Truncate at "Contents/MacOS"
    *contents = '\0';

    // Build script path
    char script_path[4096];
    snprintf(script_path, sizeof(script_path),
             "%sContents/Resources/UmbraEdit/UmbraEdit.py", exe_path);

    // Build argument list for Python.
    // argv[0] = "UmbraEdit" so macOS shows the correct name.
    // argv[1] = script path
    // argv[2..] = user arguments (skip argc[0] which is our own name)
    int new_argc = argc; // argv[0] + script + (argc-1) user args
    char **new_argv = malloc((new_argc + 1) * sizeof(char *));
    if (!new_argv) {
        fprintf(stderr, "UmbraEdit: out of memory\n");
        return 1;
    }

    new_argv[0] = "UmbraEdit";  // process name for macOS menu bar
    new_argv[1] = script_path;
    for (int i = 1; i < argc; i++) {
        new_argv[i + 1] = argv[i];
    }
    new_argv[new_argc] = NULL;

    // Set working directory to Resources/UmbraEdit
    char *dir_end = strstr(exe_path, "Contents/MacOS");
    *dir_end = '\0';
    char res_dir[4096];
    snprintf(res_dir, sizeof(res_dir), "%sContents/Resources/UmbraEdit", exe_path);
    if (chdir(res_dir) != 0) {
        fprintf(stderr, "UmbraEdit: could not chdir to %s\n", res_dir);
    }

    execv(PYTHON_PATH, new_argv);

    // execv only returns on error
    fprintf(stderr, "UmbraEdit: could not exec %s\n", PYTHON_PATH);
    free(new_argv);
    return 1;
}
