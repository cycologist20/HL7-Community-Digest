"""Zulip channel scraper for HL7 community discussions."""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import requests

from ..config import ZulipSource
from ..models import ZulipMessage, ZulipThreadContent

logger = logging.getLogger(__name__)


class ZulipScraper:
    """Scrapes Zulip channels for recent discussions."""
    
    def __init__(
        self,
        site: Optional[str] = None,
        email: Optional[str] = None,
        api_key: Optional[str] = None,
        lookback_days: int = 7,
        recent_hours: int = 24,
    ) -> None:
        """Initialize the Zulip scraper.
        
        Args:
            site: Zulip server URL (default: from env ZULIP_SITE)
            email: Bot email (default: from env ZULIP_EMAIL)
            api_key: Bot API key (default: from env ZULIP_API_KEY)
            lookback_days: Days of history to fetch (default: 7)
            recent_hours: Hours to consider "recent" activity (default: 24)
        """
        self.site = site or os.getenv("ZULIP_SITE", "https://chat.fhir.org")
        self.email = email or os.getenv("ZULIP_EMAIL")
        self.api_key = api_key or os.getenv("ZULIP_API_KEY")
        self.lookback_days = int(os.getenv("ZULIP_LOOKBACK_DAYS", lookback_days))
        self.recent_hours = int(os.getenv("ZULIP_RECENT_HOURS", recent_hours))
        
        if not self.email or not self.api_key:
            raise ValueError("ZULIP_EMAIL and ZULIP_API_KEY must be set")
        
        self.auth = (self.email, self.api_key)
        
        # Check for Anthropic API key for summarization
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self.use_ai_summary = bool(self.anthropic_api_key)
        if self.use_ai_summary:
            logger.info("Zulip AI summarization enabled")
    
    def _api_get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make authenticated GET request to Zulip API."""
        url = f"{self.site}/api/v1/{endpoint}"
        response = requests.get(url, auth=self.auth, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _get_stream_id(self, stream_name: str) -> Optional[int]:
        """Get stream ID by name."""
        try:
            data = self._api_get("users/me/subscriptions")
            for sub in data.get("subscriptions", []):
                if sub["name"].lower() == stream_name.lower():
                    return sub["stream_id"]
            
            # Try to find in all streams if not subscribed
            data = self._api_get("streams")
            for stream in data.get("streams", []):
                if stream["name"].lower() == stream_name.lower():
                    return stream["stream_id"]
            
            return None
        except Exception as e:
            logger.error(f"Failed to get stream ID for {stream_name}: {e}")
            return None
    
    def _get_messages(
        self, 
        stream_name: str, 
        since: datetime,
    ) -> list[dict]:
        """Get messages from a stream since a given datetime."""
        messages = []
        anchor = "newest"
        seen_oldest = False
        
        # Convert since to timestamp for comparison
        since_ts = since.timestamp()
        logger.debug(f"Fetching messages from '{stream_name}' since {since} (ts: {since_ts})")
        
        while not seen_oldest:
            try:
                params = {
                    "anchor": anchor,
                    "num_before": 100,
                    "num_after": 0,
                    "narrow": json.dumps([{"operator": "channel", "operand": stream_name}]),
                    "apply_markdown": "false",
                }
                
                data = self._api_get("messages", params)
                batch = data.get("messages", [])
                
                logger.debug(f"Received {len(batch)} messages from API")
                
                if not batch:
                    break
                
                # Process all messages in the batch
                for msg in batch:
                    msg_ts = msg.get("timestamp", 0)
                    if msg_ts >= since_ts:
                        messages.append(msg)
                    else:
                        # Found a message older than our window
                        seen_oldest = True
                
                # If we've seen all messages or hit oldest, stop
                if seen_oldest:
                    break
                
                # Check if we should continue pagination
                oldest_msg = batch[-1]
                if oldest_msg.get("timestamp", 0) < since_ts:
                    break
                
                # Prevent infinite loop - if anchor doesn't change
                new_anchor = oldest_msg["id"]
                if new_anchor == anchor:
                    break
                anchor = new_anchor
                
                # Safety limit
                if len(messages) >= 500:
                    logger.warning(f"Hit message limit for {stream_name}")
                    break
                    
            except Exception as e:
                logger.error(f"Failed to get messages from {stream_name}: {e}")
                break
        
        logger.debug(f"Found {len(messages)} messages within time window for {stream_name}")
        return messages
    
    def _group_by_topic(self, messages: list[dict]) -> dict[str, list[dict]]:
        """Group messages by topic."""
        topics = {}
        for msg in messages:
            topic = msg.get("subject", "")
            if topic not in topics:
                topics[topic] = []
            topics[topic].append(msg)
        return topics
    
    def _filter_recent_topics(
        self, 
        topics: dict[str, list[dict]], 
        recent_since: datetime
    ) -> dict[str, list[dict]]:
        """Filter to only topics with recent activity."""
        recent_ts = recent_since.timestamp()
        
        filtered = {}
        for topic, messages in topics.items():
            # Check if any message is recent
            has_recent = any(msg.get("timestamp", 0) >= recent_ts for msg in messages)
            if has_recent:
                filtered[topic] = messages
        
        return filtered
    
    def _build_thread_url(self, stream_name: str, topic: str) -> str:
        """Build URL to Zulip thread."""
        # Zulip URL encoding for topics
        encoded_stream = quote(stream_name.replace(" ", "-"), safe="")
        encoded_topic = quote(topic.replace(" ", ".20"), safe="")
        return f"{self.site}/#narrow/channel/{encoded_stream}/topic/{encoded_topic}"
    
    def _summarize_topic(
        self, 
        topic: str, 
        messages: list[dict], 
        stream_name: str
    ) -> str:
        """Generate AI summary for a topic's messages."""
        if not self.use_ai_summary or not messages:
            return self._fallback_summary(messages)
        
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            
            # Build conversation text
            conversation = []
            for msg in sorted(messages, key=lambda m: m.get("timestamp", 0)):
                sender = msg.get("sender_full_name", "Unknown")
                content = msg.get("content", "")[:500]  # Limit per message
                conversation.append(f"{sender}: {content}")
            
            conversation_text = "\n".join(conversation[-20:])  # Last 20 messages
            
            prompt = f"""Summarize this Zulip discussion thread for a daily digest email. 
Focus on: key questions asked, answers/solutions provided, decisions made, and action items.

Channel: {stream_name}
Topic: {topic}
Messages ({len(messages)} total):

{conversation_text}

Provide a brief summary (2-3 sentences, max 100 words). Start directly with the content."""

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text.strip()
            
        except Exception as e:
            logger.warning(f"AI summarization failed for {topic}: {e}")
            return self._fallback_summary(messages)
    
    def _fallback_summary(self, messages: list[dict]) -> str:
        """Create basic summary without AI."""
        if not messages:
            return "No messages in this thread."
        
        # Get first and last message preview
        sorted_msgs = sorted(messages, key=lambda m: m.get("timestamp", 0))
        first_msg = sorted_msgs[0].get("content", "")[:150]
        
        # Clean up markdown
        first_msg = re.sub(r'<[^>]+>', '', first_msg)
        first_msg = re.sub(r'\s+', ' ', first_msg).strip()
        
        if len(first_msg) > 100:
            first_msg = first_msg[:100] + "..."
        
        return f"Discussion started: \"{first_msg}\""
    
    def scrape_source(self, source: ZulipSource) -> Optional[ZulipThreadContent]:
        """Scrape a Zulip channel for recent discussions.
        
        Returns a ZulipThreadContent for the most active recent topic,
        or aggregated content if multiple topics are active.
        """
        logger.info(f"Scraping Zulip channel: {source.name} ({source.stream_name})")
        
        now = datetime.now(timezone.utc)
        lookback_since = now - timedelta(days=self.lookback_days)
        recent_since = now - timedelta(hours=self.recent_hours)
        
        logger.debug(f"Lookback: {self.lookback_days} days, Recent: {self.recent_hours} hours")
        logger.debug(f"Looking for messages since: {lookback_since}")
        
        # Get all messages in lookback window
        messages = self._get_messages(source.stream_name, lookback_since)
        
        if not messages:
            logger.info(f"No messages found in {source.stream_name} within {self.lookback_days} days")
            return None
        
        logger.info(f"Found {len(messages)} total messages in {source.stream_name}")
        
        # Group by topic
        topics = self._group_by_topic(messages)
        logger.debug(f"Messages grouped into {len(topics)} topics")
        
        # Filter to only topics with recent activity
        recent_topics = self._filter_recent_topics(topics, recent_since)
        
        if not recent_topics:
            logger.info(f"No recent activity (within {self.recent_hours}h) in {source.stream_name}")
            return None
        
        logger.info(f"Found {len(recent_topics)} active topic(s) in {source.stream_name}")
        
        # Build summaries for each active topic
        topic_summaries = []
        all_participants = set()
        total_messages = 0
        recent_messages = 0
        
        for topic, topic_messages in recent_topics.items():
            # Count messages
            total_messages += len(topic_messages)
            recent_count = sum(
                1 for m in topic_messages 
                if m.get("timestamp", 0) >= recent_since.timestamp()
            )
            recent_messages += recent_count
            
            # Get participants
            for msg in topic_messages:
                all_participants.add(msg.get("sender_full_name", "Unknown"))
            
            # Generate summary
            summary = self._summarize_topic(topic, topic_messages, source.stream_name)
            thread_url = self._build_thread_url(source.stream_name, topic)
            
            topic_summaries.append({
                "topic": topic,
                "summary": summary,
                "message_count": len(topic_messages),
                "recent_count": recent_count,
                "url": thread_url,
            })
        
        # Sort by recent activity
        topic_summaries.sort(key=lambda t: t["recent_count"], reverse=True)
        
        # Build combined content
        content_parts = []
        for ts in topic_summaries[:5]:  # Top 5 topics
            content_parts.append(
                f"**{ts['topic']}** ({ts['recent_count']} new): {ts['summary']}"
            )
        
        combined_content = "\n\n".join(content_parts)
        
        # Build URL to channel
        channel_url = f"{self.site}/#narrow/channel/{source.stream_id}-{quote(source.stream_name.replace(' ', '-'), safe='')}"
        
        # Get most recent message timestamp
        latest_msg = max(messages, key=lambda m: m.get("timestamp", 0))
        latest_timestamp = datetime.fromtimestamp(
            latest_msg.get("timestamp", 0), 
            tz=timezone.utc
        )
        
        return ZulipThreadContent(
            source_name=source.name,
            work_group=source.work_group,
            url=channel_url,
            stream_name=source.stream_name,
            stream_id=source.stream_id,
            topic=f"{len(recent_topics)} active topic(s)",
            messages=[],  # We don't need individual messages in output
            message_count=total_messages,
            participant_count=len(all_participants),
            is_trending=recent_messages >= 5,
            scrape_timestamp=now,
            content=combined_content,
            recent_message_count=recent_messages,
        )
    
    def scrape_all(self, sources: list[ZulipSource]) -> list[ZulipThreadContent]:
        """Scrape all configured Zulip sources."""
        results = []
        
        for source in sources:
            try:
                content = self.scrape_source(source)
                if content:
                    results.append(content)
            except Exception as e:
                logger.error(f"Failed to scrape {source.name}: {e}")
        
        logger.info(f"Scraped {len(results)}/{len(sources)} Zulip channels with activity")
        return results
