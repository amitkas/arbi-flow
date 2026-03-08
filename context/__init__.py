from context.base import BaseContext
from context.video import VideoContext

# Backward compatibility: agents import `from context import PipelineContext`
PipelineContext = VideoContext

__all__ = ["BaseContext", "VideoContext", "PipelineContext"]
