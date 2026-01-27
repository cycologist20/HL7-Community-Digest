"""Confluence page scraper for HL7 meeting minutes."""

import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import ConfluenceSource
from ..models import ConfluencePageContent, ScrapedContent

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Exception raised when scraping fails."""
    
    pass


class ConfluenceScraper:
    """Scrapes HL7 Confluence pages for meeting minutes and updates."""
    
    # Use a real browser User-Agent to avoid being blocked
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    def __init__(self, timeout: int = 60) -> None:
        """Initialize the scraper.
        
        Args:
            timeout: Request timeout in seconds.
        """
        self.timeout = timeout
        self.session = requests.Session()
        
        # Set headers to mimic a real browser
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def _fetch_page(self, url: str) -> str:
        """Fetch a page with retry logic.
        
        Args:
            url: The URL to fetch.
            
        Returns:
            HTML content of the page.
            
        Raises:
            ScraperError: If the page cannot be fetched after retries.
        """
        try:
            logger.debug(f"Fetching URL: {url}")
            response = self.session.get(url, timeout=self.timeout)
            
            logger.debug(f"Response status: {response.status_code}")
            
            if response.status_code == 405:
                # Method not allowed - try with different approach
                logger.warning(f"Got 405 for {url}, trying without some headers...")
                # Create a fresh session with minimal headers
                simple_session = requests.Session()
                simple_session.headers.update({
                    "User-Agent": self.USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                })
                response = simple_session.get(url, timeout=self.timeout)
                logger.debug(f"Retry response status: {response.status_code}")
            
            response.raise_for_status()
            return response.text
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            raise ScraperError(f"Failed to fetch page: {e}") from e
    
    def _parse_confluence_page(self, html: str, url: str) -> tuple[str, str, Optional[datetime]]:
        """Parse Confluence page HTML to extract content.
        
        Args:
            html: Raw HTML content.
            url: Source URL (for logging).
            
        Returns:
            Tuple of (title, content, last_modified).
        """
        soup = BeautifulSoup(html, "lxml")
        
        # Extract page title
        title_elem = soup.find("title")
        title = title_elem.get_text(strip=True) if title_elem else "Untitled Page"
        
        # Remove " - ... - Confluence" suffix if present
        title = re.sub(r"\s*-\s*.*\s*-\s*Confluence\s*$", "", title)
        
        # Find the main content area
        # Confluence uses different content containers depending on the view
        content_selectors = [
            "#main-content",
            ".wiki-content", 
            "#content .page-content",
            ".confluence-content",
            "#main",
            "article",
            ".content-body",
        ]
        
        content_elem = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                logger.debug(f"Found content using selector: {selector}")
                break
        
        if not content_elem:
            # Fallback to body if no content container found
            logger.debug("Using body as fallback content container")
            content_elem = soup.find("body")
        
        # Extract text content, preserving some structure
        content = self._extract_text_content(content_elem) if content_elem else ""
        
        # Try to find last modified date
        last_modified = self._extract_last_modified(soup)
        
        return title, content, last_modified
    
    def _extract_text_content(self, element: Tag) -> str:
        """Extract readable text from an HTML element.
        
        Preserves paragraph structure while removing navigation and metadata.
        
        Args:
            element: BeautifulSoup Tag to extract from.
            
        Returns:
            Cleaned text content.
        """
        # Make a copy to avoid modifying the original
        element = BeautifulSoup(str(element), "lxml")
        
        # Remove unwanted elements
        for tag in element.find_all(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        
        # Also remove Confluence-specific navigation and metadata
        unwanted_classes = [
            "page-metadata", "breadcrumb", "page-sidebar", "navigation",
            "aui-nav", "space-shortcuts", "page-tree", "footer",
            "confluence-information-macro", "expand-container"
        ]
        for class_name in unwanted_classes:
            for tag in element.find_all(class_=re.compile(class_name, re.I)):
                tag.decompose()
        
        # Remove elements by ID
        unwanted_ids = ["footer", "header", "navigation", "sidebar"]
        for elem_id in unwanted_ids:
            tag = element.find(id=re.compile(elem_id, re.I))
            if tag:
                tag.decompose()
        
        # Get text with some structure preservation
        lines = []
        
        for elem in element.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "div"]):
            text = elem.get_text(strip=True)
            if text and len(text) > 2:  # Skip very short strings
                # Add header markers
                if elem.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    lines.append(f"\n## {text}\n")
                elif elem.name == "li":
                    lines.append(f"• {text}")
                elif elem.name in ["td", "th"]:
                    # Skip table cells as they often duplicate content
                    continue
                else:
                    # Only add if not a duplicate of the last line
                    if not lines or text != lines[-1].strip("• \n#"):
                        lines.append(text)
        
        # Join and clean up whitespace
        content = "\n".join(lines)
        content = re.sub(r"\n{3,}", "\n\n", content)
        
        return content.strip()
    
    def _extract_last_modified(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract last modified date from Confluence page.
        
        Args:
            soup: Parsed HTML.
            
        Returns:
            Last modified datetime if found, None otherwise.
        """
        # Confluence often has this in a meta tag or in page metadata
        meta_selectors = [
            'meta[name="ajs-last-modified-date"]',
            'meta[name="last-modified"]',
        ]
        
        for selector in meta_selectors:
            meta = soup.select_one(selector)
            if meta and meta.get("content"):
                try:
                    # Try parsing ISO format
                    return datetime.fromisoformat(meta["content"].replace("Z", "+00:00"))
                except ValueError:
                    pass
        
        # Look for "last updated on" text in the page
        update_patterns = [
            r"last updated on\s+(\w+\s+\d+,?\s+\d{4})",
            r"last modified[:\s]+(\w+\s+\d+,?\s+\d{4})",
            r"Updated:\s*(\w+\s+\d+,?\s+\d{4})",
        ]
        
        text = soup.get_text()
        for pattern in update_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                try:
                    from dateutil import parser as date_parser
                    return date_parser.parse(match.group(1))
                except (ValueError, ImportError):
                    pass
        
        return None
    
    def _extract_meeting_info(self, content: str) -> dict:
        """Extract structured meeting information from content.
        
        Args:
            content: Page content text.
            
        Returns:
            Dict with meeting_date, attendees, action_items, decisions.
        """
        result = {
            "meeting_date": None,
            "attendees": [],
            "action_items": [],
            "decisions": [],
        }
        
        # Extract date patterns (e.g., "January 15, 2025" or "2025-01-15")
        date_patterns = [
            r"(\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b)",
            r"(\b\d{4}-\d{2}-\d{2}\b)",
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, content)
            if match:
                try:
                    from dateutil import parser as date_parser
                    result["meeting_date"] = date_parser.parse(match.group(1))
                    break
                except (ValueError, ImportError):
                    pass
        
        # Extract action items (common patterns in meeting notes)
        action_patterns = [
            r"(?:Action|TODO|Action Item)[:\s]+(.+?)(?:\n|$)",
            r"•\s*(?:Action)[:\s]*(.+?)(?:\n|$)",
        ]
        
        for pattern in action_patterns:
            matches = re.findall(pattern, content, re.I)
            result["action_items"].extend([m.strip() for m in matches if m.strip()])
        
        # Extract decisions
        decision_patterns = [
            r"(?:Decision|Decided|Agreed)[:\s]+(.+?)(?:\n|$)",
            r"(?:DECISION)[:\s]*(.+?)(?:\n|$)",
        ]
        
        for pattern in decision_patterns:
            matches = re.findall(pattern, content, re.I)
            result["decisions"].extend([m.strip() for m in matches if m.strip()])
        
        return result
    
    def scrape_page(
        self, 
        url: str, 
        work_group: str,
        source_name: Optional[str] = None
    ) -> Optional[ConfluencePageContent]:
        """Scrape a single Confluence page.
        
        Args:
            url: The Confluence page URL.
            work_group: The HL7 work group name (e.g., "Da Vinci").
            source_name: Optional friendly name for the source.
            
        Returns:
            ConfluencePageContent if successful, None if failed.
        """
        logger.info(f"Scraping {work_group} page: {url}")
        
        try:
            html = self._fetch_page(url)
            title, content, last_modified = self._parse_confluence_page(html, url)
            
            # Extract meeting-specific information
            meeting_info = self._extract_meeting_info(content)
            
            return ConfluencePageContent(
                source_name=source_name or title,
                work_group=work_group,
                url=url,
                title=title,
                content=content,
                last_modified=last_modified,
                scrape_timestamp=datetime.utcnow(),
                meeting_date=meeting_info["meeting_date"],
                attendees=meeting_info["attendees"],
                action_items=meeting_info["action_items"],
                decisions=meeting_info["decisions"],
            )
            
        except ScraperError as e:
            logger.error(f"Failed to scrape {url}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error scraping {url}: {e}")
            return None
    
    def scrape_source(self, source: ConfluenceSource) -> Optional[ConfluencePageContent]:
        """Scrape a configured Confluence source.
        
        Args:
            source: ConfluenceSource configuration.
            
        Returns:
            ConfluencePageContent if successful, None if failed.
        """
        return self.scrape_page(
            url=source.url,
            work_group=source.work_group,
            source_name=source.name,
        )
    
    def scrape_all(self, sources: list[ConfluenceSource]) -> list[ConfluencePageContent]:
        """Scrape all configured Confluence sources.
        
        Args:
            sources: List of ConfluenceSource configurations.
            
        Returns:
            List of successfully scraped content.
        """
        results = []
        
        for source in sources:
            content = self.scrape_source(source)
            if content:
                results.append(content)
            else:
                logger.warning(f"Failed to scrape source: {source.name}")
        
        logger.info(f"Successfully scraped {len(results)}/{len(sources)} Confluence pages")
        return results
