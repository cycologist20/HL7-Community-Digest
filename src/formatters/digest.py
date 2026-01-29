"""Digest formatter for HL7 Community Digest."""

import logging
import re
from datetime import datetime, timedelta
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
    
    # Number of days to consider content "recent"
    RECENT_DAYS = 7
    
    def __init__(self, config: Optional[ProcessingConfig] = None) -> None:
        """Initialize the formatter.
        
        Args:
            config: Processing configuration. Loads from env if not provided.
        """
        if config is None:
            config = get_config().processing
        
        self.config = config
        self.timezone = pytz.timezone(config.timezone)
    
    def _is_ai_summary(self, content: str) -> bool:
        """Check if content appears to be an AI-generated summary.
        
        AI summaries typically start with **Date**: or contain multiple
        meeting summaries separated by newlines.
        
        Args:
            content: The content to check.
            
        Returns:
            True if this looks like an AI summary.
        """
        if not content:
            return False
        
        # AI summaries start with **Mon DD**: pattern
        if re.match(r'\*\*[A-Z][a-z]{2}\s+\d{1,2}\*\*:', content):
            return True
        
        # Or contain multiple such patterns (multi-meeting summaries)
        if len(re.findall(r'\*\*[A-Z][a-z]{2}\s+\d{1,2}\*\*:', content)) >= 1:
            return True
        
        return False
    
    def _clean_content(self, content: str) -> str:
        """Clean up scraped content for better readability.
        
        Args:
            content: Raw scraped content.
            
        Returns:
            Cleaned content string.
        """
        if not content:
            return ""
        
        # Don't clean AI-generated summaries - they're already formatted
        if self._is_ai_summary(content):
            return content
        
        # Pattern to detect concatenated meeting titles (dates followed by text without spaces)
        date_pattern = r'\d{4}-\d{2}-\d{2}'
        date_matches = re.findall(date_pattern, content[:500])
        
        if len(date_matches) >= 3:
            # This looks like an index page with many meeting links
            return self._summarize_index_page(content)
        
        # Clean up common noise patterns
        cleaned = content
        
        # Remove "Create Agenda" and similar task management noise
        cleaned = re.sub(r'Create Agenda\s*Tasks\s*Description\s*Due date\s*Assignee\s*Task appears on', '', cleaned)
        
        # Remove repeated date patterns that look like task lists
        cleaned = re.sub(r'(\d{1,2}\s+\w{3}\s+\d{4}[^.]*){3,}', '[Task list removed]', cleaned)
        
        # Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Truncate if still too long (only for non-AI content)
        if len(cleaned) > 500:
            # Try to find a sentence boundary
            sentence_end = cleaned[:500].rfind('. ')
            if sentence_end > 100:
                cleaned = cleaned[:sentence_end + 1]
            else:
                cleaned = cleaned[:500] + "..."
        
        return cleaned
    
    def _summarize_index_page(self, content: str) -> str:
        """Summarize an index page that lists multiple meetings."""
        date_pattern = r'(\d{4}-\d{2}-\d{2})'
        dates = re.findall(date_pattern, content)
        
        if dates:
            unique_dates = sorted(set(dates), reverse=True)
            recent_dates = unique_dates[:3]
            formatted_dates = []
            for d in recent_dates:
                try:
                    dt = datetime.strptime(d, '%Y-%m-%d')
                    formatted_dates.append(dt.strftime('%b %d'))
                except ValueError:
                    formatted_dates.append(d)
            
            if len(unique_dates) > 3:
                return f"Meeting index with links to {len(unique_dates)} sessions. Most recent: {', '.join(formatted_dates)}. Click to view individual meeting notes."
            else:
                return f"Meeting index with links for: {', '.join(formatted_dates)}. Click to view individual meeting notes."
        
        return "Index page containing links to meeting minutes. Click to view details."
    
    def _extract_most_recent_date_from_content(self, content: str) -> Optional[datetime]:
        """Try to extract the most recent date mentioned in the content."""
        date_pattern = r'(\d{4}-\d{2}-\d{2})'
        dates = re.findall(date_pattern, content)
        
        if dates:
            try:
                parsed_dates = []
                for d in dates:
                    try:
                        parsed_dates.append(datetime.strptime(d, '%Y-%m-%d'))
                    except ValueError:
                        continue
                
                if parsed_dates:
                    return max(parsed_dates)
            except Exception:
                pass
        
        return None
    
    def _is_recent(self, date: Optional[datetime], reference_date: Optional[datetime] = None) -> bool:
        """Check if a date is within the recent window."""
        if date is None:
            return False
        
        if reference_date is None:
            reference_date = datetime.now(self.timezone)
        
        if date.tzinfo is None:
            date = self.timezone.localize(date)
        
        if reference_date.tzinfo is None:
            reference_date = self.timezone.localize(reference_date)
        
        cutoff = reference_date - timedelta(days=self.RECENT_DAYS)
        return date >= cutoff
    
    def _get_freshness_label(self, date: Optional[datetime]) -> str:
        """Get a human-readable freshness label for a date."""
        if date is None:
            return ""
        
        now = datetime.now(self.timezone)
        
        if date.tzinfo is None:
            date = self.timezone.localize(date)
        
        delta = now - date
        
        if delta.days == 0:
            return "🟢 Updated today"
        elif delta.days == 1:
            return "🟢 Updated yesterday"
        elif delta.days <= 7:
            return f"🟢 Updated {delta.days} days ago"
        elif delta.days <= 30:
            return f"🟡 Updated {delta.days} days ago"
        else:
            return f"⚪ Last updated {date.strftime('%B %d, %Y')}"
    
    def _summarize_confluence_content(
        self, 
        content: ConfluencePageContent
    ) -> ContentSummary:
        """Create a summary from Confluence page content."""
        # Clean up the content (preserves AI summaries)
        cleaned_content = self._clean_content(content.content)
        
        # Determine the effective date
        effective_date = content.last_modified
        if effective_date is None:
            effective_date = self._extract_most_recent_date_from_content(content.content)
        
        is_recent = self._is_recent(effective_date)
        
        # Build summary text
        summary_parts = []
        
        # Add freshness indicator if we have a date
        if effective_date:
            freshness = self._get_freshness_label(effective_date)
            if freshness:
                summary_parts.append(freshness)
        
        # Add the cleaned content
        if cleaned_content:
            summary_parts.append(cleaned_content)
        else:
            summary_parts.append("No content preview available.")
        
        # Add action items / decisions if found (and not already in AI summary)
        if content.decisions and not self._is_ai_summary(content.content):
            summary_parts.append(f"✅ {len(content.decisions)} decision(s) recorded.")
        
        # Mark as trending if has decisions
        is_trending = is_recent and bool(content.decisions)
        
        summary = " ".join(summary_parts)
        
        return ContentSummary(
            source_type=SourceType.CONFLUENCE,
            source_name=content.source_name,
            work_group=content.work_group,
            url=content.url,
            summary=summary,
            is_trending=is_trending,
            has_updates=is_recent,
            last_activity=effective_date,
        )
    
    def _summarize_zulip_content(
        self, 
        content: ZulipThreadContent
    ) -> ContentSummary:
        """Create a summary from Zulip thread content."""
        # The content field contains the AI-generated topic summaries
        # Format: **Topic** (N new): Summary\n\n**Topic2** (N new): Summary2
        
        summary_parts = []
        
        # Add channel stats header
        stats = f"📌 **{content.source_name}** ({content.message_count} messages, {content.participant_count} participants)"
        summary_parts.append(stats)
        
        # Add the AI-generated content summaries
        if content.content:
            summary_parts.append(content.content)
        else:
            summary_parts.append("No significant activity in the lookback period.")
        
        summary = "\n\n".join(summary_parts)
        
        return ContentSummary(
            source_type=SourceType.ZULIP,
            source_name=content.source_name,
            work_group=content.work_group,
            url=content.url,
            summary=summary,
            is_trending=content.is_trending,
            has_updates=content.message_count > 0,
            last_activity=content.scrape_timestamp,
            participant_count=content.participant_count,
        )
    
    def create_digest(
        self,
        confluence_content: list[ConfluencePageContent],
        zulip_content: Optional[list[ZulipThreadContent]] = None,
        digest_date: Optional[datetime] = None,
    ) -> Digest:
        """Create a complete digest from scraped content."""
        if digest_date is None:
            digest_date = datetime.now(self.timezone)
        
        sections = []
        
        # Confluence section
        if confluence_content:
            confluence_summaries = [
                self._summarize_confluence_content(content)
                for content in confluence_content
            ]
            
            # Sort: recent first, then by work group
            confluence_summaries.sort(key=lambda x: (not x.has_updates, x.work_group))
            
            sections.append(DigestSection(
                title="Confluence Updates",
                source_type=SourceType.CONFLUENCE,
                summaries=confluence_summaries,
            ))
        else:
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
        """Generate email subject line for digest."""
        date_str = digest.date.strftime("%A, %B %d, %Y")
        
        recent_count = sum(
            1 for section in digest.sections 
            for summary in section.summaries 
            if summary.has_updates
        )
        
        if recent_count > 0:
            return f"HL7 Community Digest - {date_str} ({recent_count} recent updates)"
        else:
            return f"HL7 Community Digest - {date_str}"
    
    def format_plain_text(self, digest: Digest) -> str:
        """Format digest as plain text email body."""
        return digest.to_plain_text()
    
    def format_html(self, digest: Digest) -> str:
        """Format digest as HTML email body."""
        date_str = digest.date.strftime("%A, %B %d, %Y")
        
        total_pages = sum(len(s.summaries) for s in digest.sections if s.source_type == SourceType.CONFLUENCE)
        total_threads = sum(len(s.summaries) for s in digest.sections if s.source_type == SourceType.ZULIP)
        recent_count = sum(
            1 for section in digest.sections 
            for summary in section.summaries 
            if summary.has_updates
        )
        
        if recent_count > 0:
            stat_message = f"Found <strong>{recent_count} page(s) with recent activity</strong> (updated within {self.RECENT_DAYS} days) across {total_pages} monitored Confluence pages."
        else:
            stat_message = f"Monitored {total_pages} Confluence pages. No pages updated within the last {self.RECENT_DAYS} days."
        
        html_parts = [
            self._get_html_header(),
            f'''
    <h1>HL7 Community Digest</h1>
    <p style="color: #718096;">{date_str}</p>
    
    <div class="stat-box">
        <strong>📊 Today's Scan</strong><br>
        {stat_message}<br>
        <em>Helping ASTP standards team stay current with Da Vinci, CDS Hooks, and Argonaut discussions.</em>
    </div>
'''
        ]
        
        for section in digest.sections:
            html_parts.append(self._format_section_html(section))
        
        html_parts.append(f'''
    <div class="footer">
        <p>Confluence pages scanned: {total_pages} | Zulip channels monitored: {total_threads}</p>
        <p>Generated by HL7 Community Intelligence System</p>
        <p style="font-size: 0.8em;">Questions or feedback? Contact: jim@mosaiclifetech.com</p>
    </div>
</body>
</html>
''')
        
        return "".join(html_parts)
    
    def _get_html_header(self) -> str:
        """Get the HTML document header with styles."""
        return '''<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            line-height: 1.6; 
            color: #333; 
            max-width: 800px; 
            margin: 0 auto; 
            padding: 20px; 
        }
        h1 { 
            color: #1a365d; 
            border-bottom: 3px solid #3182ce; 
            padding-bottom: 10px; 
        }
        h2 { 
            color: #2c5282; 
            margin-top: 30px; 
        }
        h3 {
            color: #2d3748;
            margin-top: 20px;
            margin-bottom: 10px;
            font-size: 1.1em;
        }
        .stat-box { 
            background: #ebf8ff; 
            border-left: 4px solid #3182ce; 
            padding: 15px; 
            margin: 20px 0; 
        }
        .article { 
            background: #f7fafc; 
            padding: 15px; 
            margin: 15px 0; 
            border-radius: 5px; 
        }
        .article-recent {
            background: #f0fff4;
            border-left: 4px solid #38a169;
        }
        .article-stale {
            background: #f7fafc;
            border-left: 4px solid #cbd5e0;
        }
        .article-trending { 
            border-left: 4px solid #d69e2e !important;
            background: #fffff0 !important;
        }
        .source { 
            color: #718096; 
            font-size: 0.9em; 
        }
        a { 
            color: #3182ce; 
        }
        .footer { 
            margin-top: 40px; 
            padding-top: 20px; 
            border-top: 1px solid #e2e8f0; 
            color: #718096; 
            font-size: 0.9em; 
        }
        .category { 
            margin-bottom: 30px; 
        }
        .no-updates {
            color: #718096;
            font-style: italic;
            padding: 10px;
            background: #f7fafc;
            border-radius: 5px;
        }
        .section-header {
            display: flex;
            align-items: center;
            margin-top: 20px;
            margin-bottom: 15px;
            padding-bottom: 5px;
            border-bottom: 1px solid #e2e8f0;
        }
        .work-group-header {
            color: #4a5568;
            font-size: 1em;
            margin-top: 15px;
            margin-bottom: 10px;
        }
        .meeting-summary {
            margin: 10px 0;
            padding: 10px;
            background: #fff;
            border-radius: 4px;
            border: 1px solid #e2e8f0;
        }
        .meeting-date {
            font-weight: bold;
            color: #2c5282;
        }
        .trending-badge {
            display: inline-block;
            background: #feebc8;
            color: #c05621;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.8em;
            font-weight: bold;
            margin-left: 8px;
        }
        details {
            margin: 8px 0;
            padding: 8px 12px;
            background: #fff;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
        }
        details[open] {
            background: #f8fafc;
        }
        summary {
            cursor: pointer;
            font-weight: 500;
            color: #2d3748;
            padding: 4px 0;
        }
        summary:hover {
            color: #3182ce;
        }
        .topic-content {
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #e2e8f0;
            font-size: 0.95em;
            line-height: 1.5;
        }
        .channel-header {
            font-weight: 600;
            color: #2c5282;
            margin-bottom: 8px;
        }
    </style>
</head>
<body>
'''
    
    def _format_section_html(self, section: DigestSection) -> str:
        """Format a single section as HTML."""
        if section.source_type == SourceType.CONFLUENCE:
            icon = "📄"
            section_title = "Confluence Updates"
        else:
            icon = "💬"
            section_title = "Zulip Discussions"
        
        html_parts = [f'''
    <div class="category">
        <h2>{icon} {section_title}</h2>
''']
        
        if not section.summaries:
            html_parts.append('''
        <p class="no-updates">No pages configured for this section.</p>
''')
        else:
            recent_summaries = [s for s in section.summaries if s.has_updates]
            stale_summaries = [s for s in section.summaries if not s.has_updates]
            
            if recent_summaries:
                html_parts.append('''
        <div class="section-header">
            <h3 style="margin: 0; color: #276749;">🟢 Recent Activity (Last 7 Days)</h3>
        </div>
''')
                work_groups: dict[str, list[ContentSummary]] = {}
                for summary in recent_summaries:
                    if summary.work_group not in work_groups:
                        work_groups[summary.work_group] = []
                    work_groups[summary.work_group].append(summary)
                
                for work_group, summaries in work_groups.items():
                    html_parts.append(f'''
        <p class="work-group-header"><strong>🏢 {work_group}</strong></p>
''')
                    for summary in summaries:
                        html_parts.append(self._format_summary_html(summary, is_recent=True))
            
            if stale_summaries:
                if recent_summaries:
                    html_parts.append('''
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 25px 0;">
''')
                
                html_parts.append('''
        <div class="section-header">
            <h3 style="margin: 0; color: #718096;">⚪ Older Content</h3>
        </div>
        <p style="color: #718096; font-size: 0.9em; margin-bottom: 15px;">These pages have not been updated in the last 7 days:</p>
''')
                work_groups: dict[str, list[ContentSummary]] = {}
                for summary in stale_summaries:
                    if summary.work_group not in work_groups:
                        work_groups[summary.work_group] = []
                    work_groups[summary.work_group].append(summary)
                
                for work_group, summaries in work_groups.items():
                    html_parts.append(f'''
        <p class="work-group-header" style="color: #a0aec0;"><strong>🏢 {work_group}</strong></p>
''')
                    for summary in summaries:
                        html_parts.append(self._format_summary_html(summary, is_recent=False))
        
        html_parts.append('''
    </div>
''')
        
        return "".join(html_parts)
    
    def _format_summary_html(self, summary: ContentSummary, is_recent: bool = True) -> str:
        """Format a single content summary as HTML."""
        # Determine article class
        if summary.is_trending:
            article_class = "article article-trending"
        elif is_recent:
            article_class = "article article-recent"
        else:
            article_class = "article article-stale"
        
        # Trending badge
        trending_badge = ""
        if summary.is_trending:
            trending_badge = '<span class="trending-badge">🔥 ACTIVE</span>'
        
        # Different format for Zulip vs Confluence
        if summary.source_type == SourceType.ZULIP:
            return self._format_zulip_summary_html(summary, article_class, trending_badge)
        else:
            return self._format_confluence_summary_html(summary, article_class, trending_badge)
    
    def _format_confluence_summary_html(self, summary: ContentSummary, article_class: str, trending_badge: str) -> str:
        """Format Confluence content as HTML."""
        summary_text = summary.summary
        summary_text = summary_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        summary_text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', summary_text)
        summary_text = summary_text.replace('\n\n', '</p><p style="margin: 10px 0;">')
        summary_text = summary_text.replace('\n', '<br>')
        
        return f'''
        <div class="{article_class}">
            <a href="{summary.url}"><strong>{summary.source_name}</strong></a>{trending_badge}
            <div class="source">{summary.work_group} • {summary.source_type.value.title()}</div>
            <p style="margin: 10px 0 0 0;">{summary_text}</p>
        </div>
'''
    
    def _format_zulip_summary_html(self, summary: ContentSummary, article_class: str, trending_badge: str) -> str:
        """Format Zulip content with collapsible topics."""
        # Parse the summary to extract channel header and individual topics
        content = summary.summary
        
        # Split by the channel header pattern: 📌 **Channel Name** (N messages, N participants)
        # The content field contains: header + topics separated by \n\n
        lines = content.split('\n\n')
        
        html_parts = [f'''
        <div class="{article_class}">
            <div class="source">{summary.work_group} • Zulip</div>
''']
        
        # First line should be the channel header
        if lines:
            header = lines[0]
            header = header.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            header = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', header)
            html_parts.append(f'            <p class="channel-header">{header}</p>\n')
        
        # Remaining lines are topics - make each collapsible
        topics = lines[1:] if len(lines) > 1 else []
        
        for topic in topics:
            if not topic.strip():
                continue
            
            # Extract topic name from the beginning (pattern: **Topic Name** (N new):)
            topic_match = re.match(r'\*\*([^*]+)\*\*\s*\((\d+)\s+new(?:,\s*([^\)]+))?\):', topic)
            if topic_match:
                topic_name = topic_match.group(1)
                msg_count = topic_match.group(2)
                relative_time = topic_match.group(3)
                # Get the rest as the detail content
                detail_content = topic[topic_match.end():].strip()
                
                # Escape and format the detail content
                detail_content = detail_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                detail_content = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', detail_content)
                detail_content = detail_content.replace('\n', '<br>')
                
                # Escape topic name
                topic_name_safe = topic_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                time_suffix = f" ({relative_time})" if relative_time else ""
                
                html_parts.append(f'''
            <details>
                <summary>💬 {topic_name_safe}{time_suffix} <span style="color: #718096; font-weight: normal;">({msg_count} messages)</span></summary>
                <div class="topic-content">{detail_content}</div>
            </details>
''')
            else:
                # Fallback: just show as regular text if pattern doesn't match
                fallback_text = topic.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                fallback_text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', fallback_text)
                html_parts.append(f'            <p style="margin: 8px 0;">{fallback_text}</p>\n')
        
        html_parts.append(f'''
            <p style="margin: 10px 0 0 0;"><a href="{summary.url}">→ View channel</a>{trending_badge}</p>
        </div>
''')
        
        return "".join(html_parts)

