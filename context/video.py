from dataclasses import dataclass, field

from context.base import BaseContext


@dataclass
class VideoContext(BaseContext):
    """State for the full video pipeline."""

    # Agent: Video Finder
    source_video_url: str = ""
    source_video_path: str = ""
    first_frame_path: str = ""

    # Agent: Video Analyzer
    video_analysis: str = ""
    scene_prompt: str = ""
    character_gender: str = ""
    character_outfit: str = ""
    num_people: int = 0
    video_keywords: list = field(default_factory=list)

    # Agent: Animation Director
    animation_direction: str = ""
    video_script: str = ""

    # Agent: Voice Actor
    voiceover_path: str = ""
    word_timestamps: list = field(default_factory=list)

    # Agent: Subtitle Burner
    subtitle_path: str = ""

    # Agent: YouTube Uploader
    youtube_video_id: str = ""
    youtube_video_url: str = ""
