"""The views of the four Stages, one module each."""

from termrenamer.tui.stages.applied import AppliedStage
from termrenamer.tui.stages.base import StageView
from termrenamer.tui.stages.plan import PlanStage
from termrenamer.tui.stages.preview import PreviewStage
from termrenamer.tui.stages.queue import QueueStage

__all__ = ["AppliedStage", "PlanStage", "PreviewStage", "QueueStage", "StageView"]
