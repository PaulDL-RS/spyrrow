.. spyrrow documentation master file, created by
   sphinx-quickstart on Mon May 19 14:10:17 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

spyrrow documentation
=====================

`spyrrow` is a Python wrapper on the Rust project `sparrow <https://github.com/JeroenGar/sparrow>`_.
It enables to solve 2D `Strip packing problems <https://en.wikipedia.org/wiki/Strip_packing_problem>`_. 

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   api

Installation
============

Spyrrow is hosted on `PyPI <https://pypi.org/project/spyrrow/>`_.

You can install with the package manager of your choice, using the PyPI package index.

For example, with `pip`, the default Python package:

.. code-block:: bash

   pip install spyrrow

Examples
========

.. code-block:: python

   import spyrrow
   from spyrrow import Item, SolverConfig, StripPackingInstance

   rectangle = Item("rectangle", [(0, 0), (1, 0), (1, 1), (0, 1)], demand=4)
   triangle = Item(
      "triangle",
      [(0, 0), (1, 0), (1, 1)],
      demand=6,
      rotation=[0, 90, 180, -90],
   )

   instance = StripPackingInstance(strip_height=2.001, items=[rectangle, triangle])
   config = SolverConfig(time_limit=60, num_workers=3, seed=0)
   solution = instance.solve(config)
   print(solution.width)  # 4.0 +/- 5%
   print(solution.density)
   for pi in solution.placed_items:
      print(pi.item_id, pi.reflected, pi.rotation, pi.translation)

The rotations an item may take are explicit: ``Rotation.none()`` (the default), a list of angles,
``Rotation.stepped(45)`` or ``Rotation.continuous()`` for a free rotation. Mirroring is allowed with
``reflection_axes=[0]``.

Early termination is on by default. ``SolverConfig.from_preset(Preset.EXHAUSTIVE)`` uses the whole time
budget. Further options are available through the nested configuration objects of ``spyrrow.config``;
you may refer to `sparrow <https://github.com/JeroenGar/sparrow>`_ for more precise explanations.

Progress, warm start and Ctrl-C
===============================

.. code-block:: python

   from spyrrow import events

   def on_event(event):
      if isinstance(event, events.SolutionReported) and event.feasible:
         print(event.elapsed, event.solution.width)

   solution = instance.solve(config, on_event=on_event)
   better = instance.solve(config, initial_solution=solution)   # warm start

Ctrl-C raises ``SolveInterrupted`` (a ``KeyboardInterrupt``) holding the best solution found so far.

Coming from spyrrow 0.x
=======================

The API changed, see the migration guide (``MIGRATION.md`` in the repository). To keep running 0.x code unchanged:

.. code-block:: python

   import spyrrow.v0 as spyrrow   # deprecated, removed in spyrrow 2.0
