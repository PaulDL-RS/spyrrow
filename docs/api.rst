API
===

Public API of `spyrrow` 1.0. The 0.x API is documented at the end (:ref:`v0-api`).

Problem definition
------------------

.. autoclass:: spyrrow.Rotation
    :members: none, discrete, stepped, continuous, from_allowed_orientations, expand

.. autoclass:: spyrrow.Item
    :members: area, min_height

.. autoclass:: spyrrow.StripPackingInstance
    :members: solve, validate, to_dict, from_dict, to_json_str, from_json_str, total_demand, total_item_area

Solution
--------

.. autoclass:: spyrrow.StripPackingSolution
    :members: to_dict, from_dict, to_json_str, from_json_str

.. autoclass:: spyrrow.PlacedItem
    :members: transform

.. autofunction:: spyrrow.read_json

.. autofunction:: spyrrow.write_json

Configuration
-------------

.. autoclass:: spyrrow.SolverConfig
    :members: from_preset, from_phase_times, replace, exploration_time, compression_time

.. autoclass:: spyrrow.Preset
    :members:

.. automodule:: spyrrow.config
    :members: ExplorationConfig, CompressionConfig, SeparatorConfig, SampleConfig, ShrinkDecay, CDEConfig, ShapeConfig

Events
------

.. automodule:: spyrrow.events
    :members:

Errors
------

.. automodule:: spyrrow.errors
    :members:

.. _v0-api:

The 0.x API (``spyrrow.v0``, deprecated)
----------------------------------------

Removed in 2.0, see MIGRATION.md.

.. autoclass:: spyrrow.v0::Item

.. autoclass:: spyrrow.v0::StripPackingInstance
    :members: solve, to_json_str

.. autoclass:: spyrrow.v0::StripPackingConfig

.. autoclass:: spyrrow.v0::StripPackingSolution

.. autoclass:: spyrrow.v0::PlacedItem

.. autoclass:: spyrrow.v0::ProgressQueue

.. autoclass:: spyrrow.v0::ReportType
