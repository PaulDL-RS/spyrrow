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

   rectangle1 = spyrrow.Item(
         0, [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], demand=4, allowed_orientations=[0]
      )
   triangle1 = spyrrow.Item(
         1,
         [(0, 0), (1, 0), (1, 1), (0, 0)],
         demand=6,
         allowed_orientations=[0, 90, 180, -90],
      )

   instance = spyrrow.StripPackingInstance("test", strip_height=2.001, items=[rectangle1,triangle1])
   sol:spyrrow.StripPackingSolution = instance.solve(30)
   print(sol.width)
   print(sol.density)
   print("\n")
   for pi in sol.placed_items:
      print(pi.id)
      print(pi.rotation)
      print(pi.translation)
      print("\n")