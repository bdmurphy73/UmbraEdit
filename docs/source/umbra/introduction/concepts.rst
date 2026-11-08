.. _umbra-what-is-umbraedit-concepts:

Concepts
========

Overview
========

What it is
    The core concepts of UmbraEdit: how a project is organised, what
    documents and entities are, and how editions, assets, and checks
    work.

What it does
    Explains the mental model you need to use UmbraEdit effectively.

Why it exists
    Understanding these concepts makes every later feature easier to
    use.

Concepts
========

Project
    A **project** is a folder on disk containing your novel text,
    character and location notes, publishing metadata, and UmbraEdit
    data. The project folder is self-contained: you can copy it, sync
    it, or put it in version control.

Document
    A **document** is a single plain text file in the project,
    typically one scene or one chapter. Documents use a minimal
    formatting syntax inspired by Markdown.

Entity
    An **entity** is a character, place, object, or other story
    element that has its own note document and can be referenced with
    ``@`` keywords.

Edition
    An **edition** is a variant of your book for a specific output
    format or language. The main edition is the original text;
    translation editions and audio editions are derived from it.

Asset
    An **asset** is a binary file (image, cover, voice matrix, audio
    sample) that belongs to the project. Assets are stored in a
    content-addressed store at ``<project>/umbra/assets/``.

Check
    A **check** is an automated validation that runs before an
    operation produces output. Checks can **block** the operation or
    produce an **advisory** warning.

Reference
=========

.. umbra-catalog:: checks

See also
========

* :doc:`what-is-umbraedit` — What UmbraEdit is.
* :doc:`first-book` — Create your first project.
