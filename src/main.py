"""Main orchestrator for HL7 Community Digest generation."""

import logging
from datetime import datetime
from typing import Optional

import pytz

from .config import Config, get_config
from .delivery import SESSender
from .formatters import DigestFormatter
from .models import Digest
from .scrapers import ConfluenceScraper

logger = logging.getLogger(__name__)


class DigestOrchestrator:
    """Orchestrates the complete digest generation and delivery process."""
    
    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialize the orchestrator.
        
        Args:
            config: Application configuration. Loads from env if not provided.
        """
        self.config = config or get_config()
        
        # Initialize components
        self.confluence_scraper = ConfluenceScraper()
        self.formatter = DigestFormatter(self.config.processing)
        self.email_sender = SESSender(self.config.email)
        
        # Timezone for scheduling
        self.timezone = pytz.timezone(self.config.processing.timezone)
    
    def scrape_sources(self) -> dict:
        """Scrape all configured sources.
        
        Returns:
            Dict with 'confluence' and 'zulip' content lists.
        """
        result = {
            "confluence": [],
            "zulip": [],
        }
        
        # Scrape Confluence if enabled
        if self.config.processing.enable_confluence:
            logger.info("Scraping Confluence sources...")
            result["confluence"] = self.confluence_scraper.scrape_all(
                self.config.sources.confluence
            )
            logger.info(f"Scraped {len(result['confluence'])} Confluence pages")
        else:
            logger.info("Confluence scraping disabled")
        
        # Scrape Zulip if enabled
        if self.config.processing.enable_zulip:
            logger.info("Scraping Zulip sources...")
            from .scrapers import ZulipScraper
            zulip_scraper = ZulipScraper()
            result["zulip"] = zulip_scraper.scrape_all(self.config.sources.zulip)
            logger.info(f"Scraped {len(result['zulip'])} Zulip channels with activity")
        else:
            logger.info("Zulip scraping disabled")
        
        return result
    
    def generate_digest(
        self,
        confluence_content: list,
        zulip_content: Optional[list] = None,
        digest_date: Optional[datetime] = None,
    ) -> Digest:
        """Generate digest from scraped content.
        
        Args:
            confluence_content: Scraped Confluence pages.
            zulip_content: Scraped Zulip threads (optional).
            digest_date: Date for the digest.
            
        Returns:
            Formatted Digest object.
        """
        if digest_date is None:
            digest_date = datetime.now(self.timezone)
        
        return self.formatter.create_digest(
            confluence_content=confluence_content,
            zulip_content=zulip_content,
            digest_date=digest_date,
        )
    
    def send_digest(
        self,
        digest: Digest,
        recipients: Optional[list[str]] = None,
        dry_run: Optional[bool] = None,
        use_html: bool = True,
    ) -> dict:
        """Send digest email.
        
        Args:
            digest: The digest to send.
            recipients: Override recipients list.
            dry_run: Override dry_run setting.
            use_html: Whether to send HTML email (default True).
            
        Returns:
            Dict with delivery result.
        """
        if dry_run is None:
            dry_run = self.config.dry_run
        
        subject = self.formatter.format_subject(digest)
        body_text = self.formatter.format_plain_text(digest)
        
        # Generate HTML version if requested
        body_html = None
        if use_html:
            body_html = self.formatter.format_html(digest)
        
        return self.email_sender.send_digest(
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            recipients=recipients,
            dry_run=dry_run,
        )
    
    def run(
        self,
        dry_run: Optional[bool] = None,
        recipients: Optional[list[str]] = None,
        use_html: bool = True,
    ) -> dict:
        """Run the complete digest generation and delivery pipeline.
        
        Args:
            dry_run: If True, generate but don't send email.
            recipients: Override recipients list.
            use_html: Whether to send HTML email (default True).
            
        Returns:
            Dict with results including 'digest', 'delivery', and 'stats'.
        """
        logger.info("Starting digest generation...")
        start_time = datetime.now()
        
        # Step 1: Scrape sources
        scraped = self.scrape_sources()
        
        # Step 2: Generate digest
        digest = self.generate_digest(
            confluence_content=scraped["confluence"],
            zulip_content=scraped["zulip"] if scraped["zulip"] else None,
        )
        
        # Step 3: Send digest
        delivery_result = self.send_digest(
            digest=digest,
            recipients=recipients,
            dry_run=dry_run,
            use_html=use_html,
        )
        
        # Calculate stats
        elapsed = (datetime.now() - start_time).total_seconds()
        
        result = {
            "success": delivery_result.get("success", False),
            "digest": digest,
            "delivery": delivery_result,
            "stats": {
                "confluence_pages_scraped": len(scraped["confluence"]),
                "zulip_threads_scraped": len(scraped["zulip"]),
                "elapsed_seconds": elapsed,
            },
        }
        
        logger.info(
            f"Digest generation complete. "
            f"Scraped {result['stats']['confluence_pages_scraped']} pages "
            f"in {elapsed:.1f}s"
        )
        
        return result


def run_daily_digest(
    dry_run: bool = False,
    recipients: Optional[list[str]] = None,
    use_html: bool = True,
) -> dict:
    """Convenience function to run daily digest.
    
    Args:
        dry_run: If True, generate but don't send email.
        recipients: Override recipients list.
        use_html: Whether to send HTML email (default True).
        
    Returns:
        Dict with results.
    """
    orchestrator = DigestOrchestrator()
    return orchestrator.run(dry_run=dry_run, recipients=recipients, use_html=use_html)
