mdq CLI
=======

The ``mdq`` command-line tool. Every command reads or writes files on
disk; the commands themselves are not part of the Python API -- import
``mdq`` directly for that (see :doc:`mdq`).

mdq validate
------------

Load a question or exam document (``.mdq.md``, ``.md``, ``.mdq``, ``.yaml``,
``.yml`` or ``.json``) and print one line per diagnostic: parse
failures, schema violations and lint warnings/info. ``--level strict``
also prints info-level diagnostics; the default level prints only
errors and warnings. Every lint rule always runs -- the level only
changes what gets printed. Exits 1 only when some diagnostic is
``error``-severity. Pass ``-`` as the file to read from stdin.

Exit codes
----------

Every command uses the same codes:

* ``0``: success. Warnings do not change it.
* ``1``: the document is invalid, or a converter cannot convert it.
* ``2``: usage or I/O: a bad option, a missing, unreadable or non-UTF-8
  input, an unknown file suffix or format, an output path that cannot be
  written (including a missing directory) or that ``new`` refuses to
  overwrite.

Errors print as ``error: <message>`` on stderr, with color only when stderr
is a terminal. No command prints a traceback. ``validate`` prints every
diagnostic of an invalid document; ``show`` and ``export`` print only the
first error.

mdq new
-------

Scaffold a new question document for one of the supported question
types. ``--complete`` writes a feature-complete example instead of a
bare-bones one. ``-o``/``--output`` picks the destination file
(default: ``<type>.mdq.md``); the command refuses to overwrite an
existing file (exit 2). A missing output directory is also exit 2.

mdq import
----------

Import a question from an external format (Aiken, GIFT, Moodle XML)
into MDQ Markdown. ``--format`` picks the source format explicitly; by
default it is inferred from the input file's extension. ``-`` reads stdin
(``--format`` is then required). ``-o``/``--output`` writes the result to
a file instead of stdout, overwriting it.

mdq export
----------

Export an MDQ question document to an external format. ``--format``
picks the target format explicitly; by default it is inferred from
``-o``'s extension, falling back to Aiken. The input format comes from
the file's suffix (``.mdq.md``, ``.md``, ``.mdq``, ``.yaml``, ``.yml`` or
``.json``) and any other suffix exits 2; ``-`` reads MDQ from stdin.
``-o``/``--output`` writes the result to a file instead of stdout,
overwriting it.

mdq show
--------

Render a question or exam document for a human at a terminal, as a
card like a quiz page would show it: a badge with the question type,
rich-text fields (stem, choices, feedback, ...) as Markdown,
choices as radio buttons and checkboxes, typed answers as empty input
fields, and the rest of the metadata as chips. ``--no-answer-key`` hides
anything that would reveal the correct answer, as when previewing a
question for a student. ``--width`` sets the console width (default:
the terminal's own width). ``--theme`` picks the colors and symbols:
``dark``, ``light``, ``plain`` (ASCII borders, no colors, no emoji) or
``auto`` (the default: ``light`` if ``COLORFGBG`` says the terminal
background is light, ``dark`` otherwise). Pass ``-`` as the file to read
from stdin.
