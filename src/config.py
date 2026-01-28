"""Configuration management for HL7 Community Digest."""

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# Load environment variables from .env file
load_dotenv()


class ConfluenceSource(BaseModel):
    """Configuration for a Confluence page source."""
    
    name: str
    work_group: str
    url: str
    description: Optional[str] = None


class ZulipSource(BaseModel):
    """Configuration for a Zulip channel source."""
    
    name: str
    work_group: str
    stream_name: str
    stream_id: int
    description: Optional[str] = None


class SourcesConfig(BaseModel):
    """Configuration for all data sources."""
    
    confluence: list[ConfluenceSource] = Field(default_factory=list)
    zulip: list[ZulipSource] = Field(default_factory=list)


class EmailConfig(BaseModel):
    """Email delivery configuration."""
    
    sender_email: str = Field(default="hl7-digest@mosaiclifetech.com")
    recipients: list[str] = Field(default_factory=lambda: ["jyounkin.ai@gmail.com"])
    aws_region: str = Field(default="us-east-1")


class ZulipConfig(BaseModel):
    """Zulip API configuration."""
    
    site: str = Field(default="https://chat.fhir.org")
    email: Optional[str] = None
    api_key: Optional[str] = None


class ProcessingConfig(BaseModel):
    """Content processing configuration."""
    
    timezone: str = Field(default="America/New_York")
    lookback_hours: int = Field(default=24)
    enable_confluence: bool = Field(default=True)
    enable_zulip: bool = Field(default=False)
    enable_ai_summarization: bool = Field(default=False)


class Config(BaseModel):
    """Main application configuration."""
    
    email: EmailConfig = Field(default_factory=EmailConfig)
    zulip: ZulipConfig = Field(default_factory=ZulipConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    log_level: str = Field(default="INFO")
    dry_run: bool = Field(default=False)
    anthropic_api_key: Optional[str] = None


def load_sources(config_path: Optional[Path] = None) -> SourcesConfig:
    """Load source configuration from YAML file.
    
    Args:
        config_path: Path to sources.yaml. Defaults to config/sources.yaml.
        
    Returns:
        SourcesConfig with all configured sources.
    """
    if config_path is None:
        # Look for config relative to project root
        project_root = Path(__file__).parent.parent
        config_path = project_root / "config" / "sources.yaml"
    
    if not config_path.exists():
        return SourcesConfig()
    
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    
    return SourcesConfig(
        confluence=[ConfluenceSource(**src) for src in data.get("confluence", [])],
        zulip=[ZulipSource(**src) for src in data.get("zulip", [])]
    )


def load_config() -> Config:
    """Load application configuration from environment and files.
    
    Returns:
        Config object with all settings.
    """
    # Load sources from YAML
    sources = load_sources()
    
    # Parse recipients from comma-separated string
    recipients_str = os.getenv("DIGEST_RECIPIENTS", "jyounkin.ai@gmail.com")
    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    
    return Config(
        email=EmailConfig(
            sender_email=os.getenv("SES_SENDER_EMAIL", "hl7-digest@mosaiclifetech.com"),
            recipients=recipients,
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
        ),
        zulip=ZulipConfig(
            site=os.getenv("ZULIP_SITE", "https://chat.fhir.org"),
            email=os.getenv("ZULIP_EMAIL"),
            api_key=os.getenv("ZULIP_API_KEY"),
        ),
        processing=ProcessingConfig(
            timezone=os.getenv("DIGEST_TIMEZONE", "America/New_York"),
            lookback_hours=int(os.getenv("SCRAPE_LOOKBACK_HOURS", "24")),
            enable_confluence=os.getenv("ENABLE_CONFLUENCE", "true").lower() == "true",
            enable_zulip=os.getenv("ENABLE_ZULIP", "false").lower() == "true",
            enable_ai_summarization=os.getenv("ENABLE_AI_SUMMARIZATION", "false").lower() == "true",
        ),
        sources=sources,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
    )


# Singleton config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the application configuration (singleton).
    
    Returns:
        Config object.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config
