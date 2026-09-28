mdq CLI
=======

The ``mdq`` command-line tool. Every command reads or writes files on
disk; the commands themselves are not part of the Python API -- import
``mdq`` directly for that (see :doc:`mdq`).

mdq validate
------------

Load a question or exam document (``.mdq.md``, ``.mdq``, ``.yaml``,
``.yml`` or ``.json``) and print one line per diagnostic: parse
failures, schema violations and lint warnings/info. ``--level strict``
also prints info-level diagnostics; the default level prints only
errors and warnings. Every lint rule always runs -- the level only
changes what gets printed. Exits non-zero only when some diagnostic is
``error``-severity.

mdq new
-------

Scaffold a new question document for one of the supported question
types. ``--complete`` writes a feature-complete example instead of a
bare-bones one. ``-o``/``--output`` picks the destination file
(default: ``<type>.mdq.md``); the command refuses to overwrite an
existing file.

mdq import
----------

Import a question from an external format (Aiken, GIFT, Moodle XML)
into MDQ Markdown. ``--format`` picks the source format explicitly; by
default it is inferred from the input file's extension. ``-o``/
``--output`` writes the result to a file instead of stdout.

mdq export
----------

Export an MDQ question document to an external format. ``--format``
picks the target format explicitly; by default it is inferred from
``-o``'s extension, falling back to Aiken. ``-o``/``--output`` writes
the result to a file instead of stdout.

mdq show
--------

Render a question or exam document for a human at a terminal:
rich-text fields (preamble, stem, choices, feedback, ...) as Markdown,
everything else as structured metadata. ``--no-answer-key`` hides
anything that would reveal the correct answer, as when previewing a
question for a student. ``--width`` sets the console width (default:
the terminal's own width). Pass ``-`` as the file to read from stdin.
