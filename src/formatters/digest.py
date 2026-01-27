"""Digest formatter for HL7 Community Digest."""

import logging
from datetime import datetime
from typing import Optional

import pytz

from ..config import ProcessingConfig, get_config
from ..models import (
    ConfluencePageContent,
    ContentSummary,
    Digest,
    DigestSection,
    SourceType,
    ZulipThreadContent,
)

logger = logging.getLogger(__name__)


class DigestFormatter:
    """Formats scraped content into a digest for delivery."""
    
    def __init__(self, config: Optional[ProcessingConfig] = None) -> None:
        """Initialize the formatter.
        
        Args:
            config: Processing configuration. Loads from env if not provided.
        """
        if config is None:
            config = get_config().processing
        
        self.config = config
        self.timezone = pytz.timezone(config.timezone)
    
    def _summarize_confluence_content(
        self, 
        content: ConfluencePageContent
    ) -> ContentSummary:
        """Create a summary from Confluence page content.
        
        For POC, this creates a simple summary without AI.
        Phase 2 will add Claude-powered summarization.
        
        Args:
            content: Scraped Confluence page content.
            
        Returns:
            ContentSummary for the digest.
        """
        # For POC: Create a simple summary from the content
        # Extract first ~200 chars as preview, or use title if content is short
        preview = content.content[:500].strip() if content.content else ""
        
        # Try to get a meaningful first sentence or paragraph
        first_para_end = preview.find("\n\n")
        if first_para_end > 50:
            preview = preview[:first_para_end]
        elif len(preview) > 200:
            # Find a sentence boundary
            sentence_end = preview[:200].rfind(". ")
            if sentence_end > 50:
                preview = preview[:sentence_end + 1]
            else:
                preview = preview[:200] + "..."
        
        # Build summary text
        summary_parts = []
        
        if content.meeting_date:
            date_str = content.meeting_date.strftime("%B %d")
            summary_parts.append(f"Meeting from {date_str}.")
        
        if preview:
            summary_parts.append(preview)
        else:
            summary_parts.append(f"Page updated: {content.title}")
        
        # Add action items or decisions if found
        if content.action_items:
            summary_parts.append(f"Action items: {len(content.action_items)} identified.")
        
        if content.decisions:
            summary_parts.append(f"Decisions: {len(content.decisions)} recorded.")
        
        summary = " ".join(summary_parts)
        
        return ContentSummary(
            source_type=SourceType.CONFLUENCE,
            source_name=content.source_name,
            work_group=content.work_group,
            url=content.url,
            summary=summary,
            is_trending=False,
            has_updates=bool(content.content),
            last_activity=content.last_modified,
        )
    
    def _summarize_zulip_content(
        self, 
        content: ZulipThreadContent
    ) -> ContentSummary:
        """Create a summary from Zulip thread content.
        
        For POC, this creates a simple summary without AI.
        Phase 2 will add Claude-powered summarization.
        
        Args:
            content: Scraped Zulip thread content.
            
        Returns:
            ContentSummary for the digest.
        """
        # Build summary with activity metrics
        summary_parts = []
        
        if content.message_count > 0:
            summary_parts.append(
                f"Active discussion ({content.message_count} messages, "
                f"{content.participant_count} participants) about {content.topic}."
            )
        else:
            summary_parts.append("No significant activity in last 24 hours.")
        
        # Preview first message if available
        if content.messages:
            first_msg = content.messages[0].content[:150]
            if len(content.messages[0].content) > 150:
                first_msg += "..."
            summary_parts.append(f'"{first_msg}"')
        
        summary = " ".join(summary_parts)
        
        return ContentSummary(
            source_type=SourceType.ZULIP,
            source_name=content.source_name,
            work_group=content.work_group,
            url=content.url,
            summary=summary,
            is_trending=content.is_trending,
            has_updates=content.message_count > 0,
            last_activity=content.messages[-1].timestamp if content.messages else None,
            participant_count=content.participant_count,
        )
    
    def create_digest(
        self,
        confluence_content: list[ConfluencePageContent],
        zulip_content: Optional[list[ZulipThreadContent]] = None,
        digest_date: Optional[datetime] = None,
    ) -> Digest:
        """Create a complete digest from scraped content.
        
        Args:
            confluence_content: List of scraped Confluence pages.
            zulip_content: List of scraped Zulip threads (optional for POC).
            digest_date: Date for the digest. Defaults to today.
            
        Returns:
            Formatted Digest object.
        """
        if digest_date is None:
            digest_date = datetime.now(self.timezone)
        
        sections = []
        
        # Confluence section
        if confluence_content:
            confluence_summaries = [
                self._summarize_confluence_content(content)
                for content in confluence_content
            ]
            
            sections.append(DigestSection(
                title="Confluence Updates",
                source_type=SourceType.CONFLUENCE,
                summaries=confluence_summaries,
            ))
        else:
            # Add empty section to show we checked
            sections.append(DigestSection(
                title="Confluence Updates",
                source_type=SourceType.CONFLUENCE,
                summaries=[],
            ))
        
        # Zulip section (if enabled)
        if zulip_content is not None:
            zulip_summaries = [
                self._summarize_zulip_content(content)
                for content in zulip_content
            ]
            
            # Sort with trending first
            zulip_summaries.sort(key=lambda x: (not x.is_trending, not x.has_updates))
            
            sections.append(DigestSection(
                title="Zulip Discussions",
                source_type=SourceType.ZULIP,
                summaries=zulip_summaries,
            ))
        
        return Digest(
            date=digest_date,
            sections=sections,
            generated_at=datetime.now(self.timezone),
        )
    
    def format_subject(self, digest: Digest) -> str:
        """Generate email subject line for digest.
        
        Args:
            digest: The digest to format.
            
        Returns:
            Subject line string.
        """
        date_str = digest.date.strftime("%A, %B %d, %Y")
        return f"HL7 Community Digest - {date_str}"
    
    def format_plain_text(self, digest: Digest) -> str:
        """Format digest as plain text email body.
        
        Args:
            digest: The digest to format.
            
        Returns:
            Plain text email body.
        """
        return digest.to_plain_text()
