# UmbraEdit

<img align="left" style="margin: 0 0 4px 0;" src="https://git.umbratools.com/umbragit/UmbraEdit/raw/main/umbraedit/assets/icons/umbraedit.svg">

UmbraEdit is a plain text editor designed for writing novels assembled from many smaller text
documents. It uses a minimal formatting syntax inspired by Markdown, and adds a meta data syntax
for comments, synopsis, and cross-referencing. It's designed to be a simple text editor that allows
for easy organisation of text and notes, using human readable text files as storage for robustness.
The project format is well suited both for version control software and file synchronisation tools.

UmbraEdit is based on novelWrite 2026.02 by Veronica Berglyd Olsen (novelWriter.io) and is
licensed under the same GPL v3.0 license.

B.D. Murphy is modifying the original using AI to make it part of his Umbratools publishing system.

The ideas:

1) Write the novel. Make it simple while writing. Formatting is later.
2) Have the entire project together. Not the novel text here and metadata you need somewhere else. All together. 2.a) ePub, paperback (print pdf), audio all start with the same story text, but each needs something different. Put everything into one project ISBN, book blurb, search terms, genere/categories BISAC codes, cover, etc
3) With everything together publishing is simpler
4) The goal is to write (human written) a novel, then use AI to help with everything else. At the end of the process there will be ePub, Paperback/Hard cover, audio versions in 10 languages.

For more details, and how to install and use UmbraEdit, please see the main website and documentation.

This project is a fork of novelWrite. Taking the great start and extending it. I use AI to help.

**Project Links**

* Website: [UmbraEdit](https://umbratools.com/umbraedit)
* Documentation: [UmbraEdit Docs](https://umbratools.com/umbraedit/docs)

This project is a fork of novelWrite. Taking the great start and extending it. I use AI to help._

## Implementation

UmbraEdit is written in Python and uses Qt6 with PyQt6 Python binding as the UI framework. It
runs on Linux, Windows and MacOS. It can in principle run on any Operating System that also
supports Qt, PyQt and Python.

<p align="center">
  <img width="80%" src="https://raw.githubusercontent.com/saga-soft/UmbraEdit/main/setup/screenshot.png">
</p>


## Project Contributions

Please don't make feature pull requests without first having discussed them with the maintainer.
You can make a feature request in the [issues tracker](https://github.com/saga-soft/UmbraEdit/issues),
or if the idea isn't fully formed, start a [discussion](https://github.com/saga-soft/UmbraEdit/discussions).
Please also don't make pull requests to reformat or rewrite existing code unless there is a very
good reason for doing so. Please do not submit AI generated content.
See our [AI Policy](https://github.com/saga-soft/UmbraEdit/blob/main/AI_POLICY.md) for details.

Fixes and patches are welcome. Contributions related to packaging and installing UmbraEdit will
also be appreciated. Before contributing any code, please read the full
[Contributing Guide](https://github.com/saga-soft/UmbraEdit/blob/main/CONTRIBUTING.md).

## Original Credits

Project credits are available in [CREDITS.md](https://github.com/saga-soft/novelwriter/blob/main/CREDITS.md).

**Note:** New features and most pre-releases are made on the `main` branch. Full releases are made
from the `release` branch. So if you're submitting a fix to a current release, **including changes
to documentation**, they must be made to the `release` branch.


## Licence

This is Open Source software, and UmbraEdit is licensed under GPLv3. See the
[GNU General Public License website](https://www.gnu.org/licenses/gpl-3.0.en.html) for more
details, or consult the [License](https://github.com/saga-soft/UmbraEdit/blob/main/LICENSE.md)
document. Bundled assets and their licenses are listed in the
[Credits](https://github.com/saga-soft/UmbraEdit/blob/main/CREDITS.md) document.
