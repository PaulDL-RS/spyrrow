API
===

Public API of `spyrrow`.

Problem definition
------------------

.. autoclass:: spyrrow.Item
    :members:

.. autoclass:: spyrrow.StripPackingInstance
    :members:

Configuration
-------------

.. autoclass:: spyrrow.StripPackingConfig
    :members:

Solution
--------

.. autoclass:: spyrrow.StripPackingSolution
    :members:

.. autoclass:: spyrrow.PlacedItem
    :members:

Progress monitoring
-------------------

.. autoclass:: spyrrow.ProgressQueue
    :members:

.. autoclass:: spyrrow.ReportType
    :members:

.. autoclass:: spyrrow.OptimizationPhase
    :members:

Detailed progress events, returned by :meth:`ProgressQueue.drain_events` for a queue created with ``detailed=True``:

.. autoclass:: spyrrow.PhaseEvent
    :members:

.. autoclass:: spyrrow.SeparationProgressEvent
    :members:

.. autoclass:: spyrrow.SeparationResultEvent
    :members:

.. autoclass:: spyrrow.CompressionProgressEvent
    :members:
