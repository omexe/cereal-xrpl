"""Feature routers the React app calls, one module per feature, included by cereal/service.py.

Each module owns its endpoints; shared state comes from cereal.deployments and, lazily inside handlers, cereal.service
(the main-wallet lock `service._main_wallet`, `service.deploy`, `service.reclaim`, `service._with_balance`).
Import cereal.service inside functions, never at module top: service imports these routers.
"""
