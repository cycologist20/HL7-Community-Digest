"""Confluence page scraper for HL7 meeting minutes with AI summarization."""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import ConfluenceSource
from ..models import ConfluencePageContent

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Exception raised when scraping fails."""
    pass


class ConfluenceScraper:
    """Scrapes HL7 Confluence pages for meeting minutes and updates."""
    
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    BASE_URL = "https://confluence.hl7.org"
    LOOKBACK_DAYS = 7
    
    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        
        # Check for Anthropic API key
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self.use_ai_summary = bool(self.anthropic_api_key)
        if self.use_ai_summary:
            logger.info("AI summarization enabled")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def _fetch_page(self, url: str) -> str:
        """Fetch a page with retry logic."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            raise ScraperError(f"Failed to fetch page: {e}") from e
    
    def _is_index_page(self, html: str) -> bool:
        """Detect if a page is an index page listing multiple meetings."""
        soup = BeautifulSoup(html, "lxml")
        main_content = soup.select_one("#main-content") or soup.find("body")
        if not main_content:
            return False
        
        # Count links that look like meeting dates
        date_link_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')
        meeting_links = [a for a in main_content.find_all('a', href=True) 
                        if date_link_pattern.search(a.get_text())]
        
        return len(meeting_links) >= 2
    
    def _extract_meeting_links(self, html: str) -> list[dict]:
        """Extract links to individual meeting pages from an index page."""
        soup = BeautifulSoup(html, "lxml")
        main_content = soup.select_one("#main-content") or soup.find("body")
        if not main_content:
            return []
        
        meeting_links = []
        date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
        cutoff = datetime.now() - timedelta(days=self.LOOKBACK_DAYS)
        
        for link in main_content.find_all('a', href=True):
            link_text = link.get_text(strip=True)
            href = link['href']
            
            date_match = date_pattern.search(link_text)
            if date_match:
                date_str = date_match.group(1)
                try:
                    meeting_date = datetime.strptime(date_str, '%Y-%m-%d')
                    if meeting_date >= cutoff:
                        # Resolve relative URL
                        if href.startswith('/'):
                            full_url = self.BASE_URL + href
                        else:
                            full_url = href
                        
                        meeting_links.append({
                            'url': full_url,
                            'date': meeting_date,
                            'title': link_text,
                        })
                except ValueError:
                    continue
        
        # Sort by date, most recent first, limit to 3
        meeting_links.sort(key=lambda x: x['date'], reverse=True)
        return meeting_links[:3]
    
    def _extract_meeting_text(self, html: str) -> str:
        """Extract clean text from a meeting notes page."""
        soup = BeautifulSoup(html, "lxml")
        
        # Remove unwanted elements
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        
        main_content = soup.select_one("#main-content") or soup.find("body")
        if not main_content:
            return ""
        
        # Get text with some structure
        text = main_content.get_text(separator='\n', strip=True)
        
        # Clean up excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text[:15000]  # Limit to ~15k chars for API
    
    def _summarize_with_claude(self, meeting_text: str, meeting_title: str) -> str:
        """Use Claude API to summarize meeting content."""
        if not self.anthropic_api_key:
            return self._fallback_summary(meeting_text)
        
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            
            prompt = f"""Summarize this HL7 FHIR meeting notes in 2-3 concise sentences for a daily digest email. Focus on:
- Key decisions made (especially JIRA tickets marked "ready for vote")
- Important announcements  
- Major discussion topics

IMPORTANT: Start your summary with [IGs discussed] in brackets, listing which Implementation Guides were covered (e.g., [PAS, DTR] or [CRD, PAS, DTR] or [All IGs]). Then provide the summary.

Meeting: {meeting_title}

Content:
{meeting_text[:10000]}

Provide a brief, informative summary (max 150 words). Start directly with the content, no preamble."""

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            summary = response.content[0].text.strip()
            logger.debug(f"AI summary generated: {summary[:100]}...")
            return summary
            
        except Exception as e:
            logger.warning(f"AI summarization failed: {e}, using fallback")
            return self._fallback_summary(meeting_text)
    
    def _fallback_summary(self, text: str) -> str:
        """Create a basic summary without AI."""
        # Count JIRA tickets
        jira_tickets = re.findall(r'FHIR-\d+', text)
        unique_tickets = list(set(jira_tickets))
        
        # Count votes
        vote_count = len(re.findall(r'marked ready for vote', text, re.I))
        
        # Count attendees
        attendee_match = re.search(r'Attendees via Zoom[^\n]*\n([\s\S]*?)(?=\n\n|\Z)', text)
        attendee_count = 0
        if attendee_match:
            attendee_count = len([l for l in attendee_match.group(1).split('\n') if l.strip()])
        
        parts = []
        if attendee_count > 0:
            parts.append(f"{attendee_count} attendees")
        if unique_tickets:
            parts.append(f"Discussed {len(unique_tickets)} JIRA tickets ({', '.join(unique_tickets[:3])})")
        if vote_count > 0:
            parts.append(f"{vote_count} ticket(s) marked ready for vote")
        
        if parts:
            return " | ".join(parts)
        return "Meeting notes available - click to view details."
    
    def scrape_source(self, source: ConfluenceSource) -> Optional[ConfluencePageContent]:
        """Scrape a configured Confluence source, following links if index page."""
        logger.info(f"Scraping {source.work_group} page: {source.url}")
        
        try:
            html = self._fetch_page(source.url)
            
            # Check if this is an index page
            if self._is_index_page(html):
                logger.info(f"Detected index page, looking for meeting links...")
                meeting_links = self._extract_meeting_links(html)
                
                if meeting_links:
                    logger.info(f"Found {len(meeting_links)} recent meeting(s), fetching content...")
                    
                    meeting_summaries = []
                    most_recent_date = None
                    all_decisions = []
                    
                    for meeting in meeting_links:
                        try:
                            meeting_html = self._fetch_page(meeting['url'])
                            meeting_text = self._extract_meeting_text(meeting_html)
                            
                            # Get summary (AI or fallback)
                            summary = self._summarize_with_claude(meeting_text, meeting['title'])
                            
                            date_str = meeting['date'].strftime('%b %d')
                            meeting_summaries.append(f"**{date_str}**: {summary}")
                            
                            if most_recent_date is None or meeting['date'] > most_recent_date:
                                most_recent_date = meeting['date']
                            
                            # Extract decisions for metadata
                            vote_count = len(re.findall(r'marked ready for vote', meeting_text, re.I))
                            if vote_count > 0:
                                all_decisions.append(f"{vote_count} tickets ready for vote")
                                
                        except Exception as e:
                            logger.warning(f"Failed to fetch meeting {meeting['url']}: {e}")
                            continue
                    
                    if meeting_summaries:
                        combined_content = "\n\n".join(meeting_summaries)
                        
                        return ConfluencePageContent(
                            source_name=source.name,
                            work_group=source.work_group,
                            url=source.url,
                            title=f"{source.name}",
                            content=combined_content,
                            last_modified=most_recent_date,
                            scrape_timestamp=datetime.utcnow(),
                            meeting_date=most_recent_date,
                            attendees=[],
                            action_items=[],
                            decisions=all_decisions,
                        )
            
            # Not an index page - extract content directly
            soup = BeautifulSoup(html, "lxml")
            title_elem = soup.find("title")
            title = title_elem.get_text(strip=True) if title_elem else source.name
            title = re.sub(r"\s*-\s*.*\s*-\s*Confluence\s*$", "", title)
            
            main_content = soup.select_one("#main-content") or soup.find("body")
            content = main_content.get_text(separator=' ', strip=True)[:500] if main_content else ""
            
            # Try to find last modified
            last_modified = None
            mod_match = re.search(r'last updated[^\n]*on\s+(\w+\s+\d+,?\s+\d{4})', html, re.I)
            if mod_match:
                try:
                    from dateutil import parser as date_parser
                    last_modified = date_parser.parse(mod_match.group(1))
                except:
                    pass
            
            return ConfluencePageContent(
                source_name=source.name,
                work_group=source.work_group,
                url=source.url,
                title=title,
                content=content,
                last_modified=last_modified,
                scrape_timestamp=datetime.utcnow(),
                meeting_date=None,
                attendees=[],
                action_items=[],
                decisions=[],
            )
            
        except Exception as e:
            logger.error(f"Failed to scrape {source.url}: {e}")
            return None
    
    def scrape_all(self, sources: list[ConfluenceSource]) -> list[ConfluencePageContent]:
        """Scrape all configured Confluence sources."""
        results = []
        for source in sources:
            content = self.scrape_source(source)
            if content:
                results.append(content)
        
        logger.info(f"Successfully scraped {len(results)}/{len(sources)} Confluence pages")
        return results
